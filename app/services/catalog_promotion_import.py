from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from hmac import compare_digest
from uuid import UUID, uuid4, uuid5

from app.domain.admin_actions import (
    AdminAction,
    AdminActionType,
    AdminResourceType,
    build_admin_request_fingerprint,
    utc_now,
)
from app.models.canonical_product import CanonicalProduct
from app.repositories.provider import RepositoryProvider
from app.services.admin_mutations import AdminCommandContext
from app.services.canonical_offer_linking import (
    LinkCanonicalOfferCommand,
    link_canonical_offer,
)
from app.services.catalog_promotion_manifest import CatalogPromotionManifest
from app.services.catalog_promotion_preflight import (
    CatalogPromotionLinkActionType,
    CatalogPromotionPreflightResult,
    CatalogPromotionPreflightStatus,
    CatalogPromotionProductActionType,
    inspect_catalog_promotion_target,
)
from app.services.repository_scope import RepositoryScopeFactory

type Clock = Callable[[], datetime]
type ActionIdFactory = Callable[[], UUID]

_IMPORT_NAMESPACE = UUID("d05b2379-30d1-48e0-8f6e-e0ed5df5758f")


@dataclass(slots=True, frozen=True, kw_only=True)
class CatalogPromotionImportCommand:
    """Explicitly approved command bound to one exact preflight plan."""

    manifest: CatalogPromotionManifest
    preflight: CatalogPromotionPreflightResult
    approval_phrase: str
    context: AdminCommandContext
    reason: str


@dataclass(slots=True, frozen=True, kw_only=True)
class CatalogPromotionImportResult:
    """Stable result of an applied or idempotently replayed import."""

    action_id: UUID
    target_tenant_id: UUID
    manifest_digest: str
    products_created: int
    links_created: int
    replayed: bool


class CatalogPromotionImportError(RuntimeError):
    """Fail-closed import error with a stable operator-facing code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CatalogPromotionImportService:
    """Apply one unchanged approved promotion plan in a single transaction."""

    def __init__(
        self,
        repository_scope_factory: RepositoryScopeFactory,
        *,
        clock: Clock = utc_now,
        action_id_factory: ActionIdFactory = uuid4,
    ) -> None:
        self._repository_scope_factory = repository_scope_factory
        self._clock = clock
        self._action_id_factory = action_id_factory

    async def apply(
        self,
        command: CatalogPromotionImportCommand,
    ) -> CatalogPromotionImportResult:
        """Re-check and atomically apply an exact READY plan."""
        target_tenant_id = command.preflight.target_tenant_id
        _validate_command(command)
        resource_id = catalog_promotion_resource_id(
            target_tenant_id,
            command.manifest.digest,
        )
        plan_digest = catalog_promotion_preflight_digest(command.preflight)
        metadata = (
            ("manifest_digest", command.manifest.digest),
            ("preflight_digest", plan_digest),
            (
                "products_created",
                str(
                    sum(
                        item.action is CatalogPromotionProductActionType.CREATE
                        for item in command.preflight.product_actions
                    )
                ),
            ),
            (
                "links_created",
                str(
                    sum(
                        item.action is CatalogPromotionLinkActionType.LINK
                        for item in command.preflight.link_actions
                    )
                ),
            ),
        )
        fingerprint = build_admin_request_fingerprint(
            actor_id=command.context.actor_id,
            tenant_id=target_tenant_id,
            actor_type=command.context.actor_type,
            elevated=command.context.elevated,
            action=AdminActionType.IMPORT_CATALOG_PROMOTION,
            resource_type=AdminResourceType.CATALOG_PROMOTION,
            resource_id=resource_id,
            expected_version=1,
            reason=command.reason,
            metadata=metadata,
        )

        async with self._repository_scope_factory() as repositories:
            await repositories.admin_actions.acquire_idempotency_lock(
                f"catalog-promotion:{resource_id}",
                target_tenant_id,
            )
            await repositories.admin_actions.acquire_idempotency_lock(
                command.context.idempotency_key,
                target_tenant_id,
            )
            existing = await repositories.admin_actions.get_by_idempotency_key(
                command.context.idempotency_key,
                target_tenant_id,
            )
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise CatalogPromotionImportError(
                        "idempotency_conflict",
                        "Idempotency key is bound to another promotion import.",
                    )
                return _result(existing, replayed=True)

            current = await inspect_catalog_promotion_target(
                repositories,
                command.manifest,
                target_tenant_id=target_tenant_id,
            )
            if current != command.preflight:
                raise CatalogPromotionImportError(
                    "preflight_drift",
                    "Target state changed after preflight; run preflight again.",
                )
            products_created, links_created = await _apply_plan(
                repositories,
                command,
            )
            action = AdminAction(
                id=self._action_id_factory(),
                tenant_id=target_tenant_id,
                action=AdminActionType.IMPORT_CATALOG_PROMOTION,
                resource_type=AdminResourceType.CATALOG_PROMOTION,
                resource_id=resource_id,
                previous_state=CatalogPromotionPreflightStatus.READY.value,
                resulting_state="imported",
                actor_id=command.context.actor_id,
                actor_type=command.context.actor_type,
                elevated=command.context.elevated,
                request_id=command.context.request_id,
                idempotency_key=command.context.idempotency_key,
                request_fingerprint=fingerprint,
                expected_version=1,
                resulting_version=2,
                created_at=self._clock(),
                reason=command.reason,
                metadata=metadata,
            )
            stored = await repositories.admin_actions.append(action)
            result = _result(stored, replayed=False)
            if (
                result.products_created != products_created
                or result.links_created != links_created
            ):
                raise CatalogPromotionImportError(
                    "audit_mismatch",
                    "Applied mutations do not match promotion audit metadata.",
                )
            return result


def catalog_promotion_approval_phrase(
    manifest: CatalogPromotionManifest,
    target_tenant_id: UUID,
) -> str:
    """Return the exact phrase required for one manifest and target tenant."""
    return f"APPROVE CATALOG PROMOTION {manifest.digest} TO {target_tenant_id}"


def catalog_promotion_resource_id(
    target_tenant_id: UUID,
    manifest_digest: str,
) -> UUID:
    """Return a deterministic audit identity for one target manifest."""
    return uuid5(_IMPORT_NAMESPACE, f"{target_tenant_id}:{manifest_digest}")


def catalog_promotion_preflight_digest(
    preflight: CatalogPromotionPreflightResult,
) -> str:
    """Hash the complete operator-reviewed preflight plan."""
    payload = {
        "issues": [
            {
                "code": issue.code.value,
                "detail": issue.detail,
                "resource": issue.resource,
            }
            for issue in preflight.issues
        ],
        "links": [
            {
                "action": action.action.value,
                "canonical_product_id": str(action.canonical_product_id),
                "external_id": action.external_id,
                "marketplace": action.marketplace,
            }
            for action in preflight.link_actions
        ],
        "manifest_digest": preflight.manifest_digest,
        "products": [
            {"action": action.action.value, "product_id": str(action.product_id)}
            for action in preflight.product_actions
        ],
        "status": preflight.status.value,
        "target_tenant_id": str(preflight.target_tenant_id),
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


def _validate_command(command: CatalogPromotionImportCommand) -> None:
    target_tenant_id = command.preflight.target_tenant_id
    expected_approval = catalog_promotion_approval_phrase(
        command.manifest,
        target_tenant_id,
    )
    if not compare_digest(command.approval_phrase, expected_approval):
        raise CatalogPromotionImportError(
            "approval_required",
            "Exact catalog promotion approval phrase is required.",
        )
    if command.context.tenant_id != target_tenant_id:
        raise CatalogPromotionImportError(
            "tenant_context_mismatch",
            "Command tenant does not match the preflight target.",
        )
    if command.preflight.manifest_digest != command.manifest.digest:
        raise CatalogPromotionImportError(
            "manifest_mismatch",
            "Preflight is bound to another manifest digest.",
        )
    if command.preflight.status is not CatalogPromotionPreflightStatus.READY:
        raise CatalogPromotionImportError(
            "preflight_not_ready",
            "Only an unchanged READY preflight can be imported.",
        )
    if not command.reason.strip():
        raise CatalogPromotionImportError(
            "reason_required",
            "A human import reason is required.",
        )


async def _apply_plan(
    repositories: RepositoryProvider,
    command: CatalogPromotionImportCommand,
) -> tuple[int, int]:
    target_tenant_id = command.preflight.target_tenant_id
    products_by_id = {product.id: product for product in command.manifest.products}
    products_created = 0
    for product_action in command.preflight.product_actions:
        if product_action.action is not CatalogPromotionProductActionType.CREATE:
            continue
        product = products_by_id[product_action.product_id]
        await repositories.canonical_products.save(
            CanonicalProduct(
                id=product.id,
                tenant_id=target_tenant_id,
                name=product.name,
                category=product.category,
                aliases=product.aliases,
            )
        )
        products_created += 1

    links_created = 0
    for link_action in command.preflight.link_actions:
        if link_action.action is not CatalogPromotionLinkActionType.LINK:
            continue
        await link_canonical_offer(
            repositories,
            LinkCanonicalOfferCommand(
                tenant_id=target_tenant_id,
                canonical_product_id=link_action.canonical_product_id,
                marketplace=link_action.marketplace,
                external_id=link_action.external_id,
            ),
        )
        links_created += 1
    return products_created, links_created


def _result(action: AdminAction, *, replayed: bool) -> CatalogPromotionImportResult:
    metadata = dict(action.metadata)
    return CatalogPromotionImportResult(
        action_id=action.id,
        target_tenant_id=action.tenant_id,
        manifest_digest=metadata["manifest_digest"],
        products_created=int(metadata["products_created"]),
        links_created=int(metadata["links_created"]),
        replayed=replayed,
    )
