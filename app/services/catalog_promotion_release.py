from __future__ import annotations

from dataclasses import dataclass
from hmac import compare_digest
from uuid import UUID

from app.domain.admin_actions import (
    AdminActionType,
    AdminResourceType,
    normalize_optional_reason,
)
from app.services.admin_mutations import AdminCommandContext
from app.services.catalog_promotion_import import (
    CatalogPromotionImportCommand,
    CatalogPromotionImportResult,
    CatalogPromotionImportService,
    catalog_promotion_approval_phrase,
    catalog_promotion_resource_id,
)
from app.services.catalog_promotion_manifest import (
    CatalogPromotionManifest,
    CatalogPromotionManifestService,
)
from app.services.catalog_promotion_preflight import (
    CatalogPromotionPreflightResult,
    CatalogPromotionPreflightService,
    CatalogPromotionPreflightStatus,
)
from app.services.repository_scope import RepositoryScopeFactory


@dataclass(slots=True, frozen=True, kw_only=True)
class CatalogPromotionReleasePreview:
    """Read-only source artifact and target plan shown to an operator."""

    source_tenant_id: UUID
    target_tenant_id: UUID
    manifest: CatalogPromotionManifest
    preflight: CatalogPromotionPreflightResult
    approval_phrase: str


@dataclass(slots=True, frozen=True, kw_only=True)
class CatalogPromotionReleaseVerification:
    """Post-commit evidence for one target catalog promotion."""

    postflight: CatalogPromotionPreflightResult
    products_present: int
    links_present: int
    audit_present: bool

    @property
    def passed(self) -> bool:
        """Return whether all imported state and audit are durable."""
        return (
            self.postflight.status is CatalogPromotionPreflightStatus.NO_CHANGES
            and self.products_present == len(self.postflight.product_actions)
            and self.links_present == len(self.postflight.link_actions)
            and self.audit_present
        )


@dataclass(slots=True, frozen=True, kw_only=True)
class CatalogPromotionReleaseResult:
    """Atomic import result plus post-commit repository verification."""

    imported: CatalogPromotionImportResult
    verification: CatalogPromotionReleaseVerification

    @property
    def verified(self) -> bool:
        """Return whether the release postconditions all passed."""
        return self.verification.passed


class CatalogPromotionReleaseError(RuntimeError):
    """Fail-closed release orchestration error with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CatalogPromotionReleaseService:
    """Orchestrate source preview, target import, and durable verification."""

    def __init__(
        self,
        source_scope_factory: RepositoryScopeFactory,
        target_scope_factory: RepositoryScopeFactory,
    ) -> None:
        self._source_scope_factory = source_scope_factory
        self._target_scope_factory = target_scope_factory

    async def preview(
        self,
        *,
        source_tenant_id: UUID,
        target_tenant_id: UUID,
    ) -> CatalogPromotionReleasePreview:
        """Build a mutation-free source manifest and target preflight."""
        manifest = await CatalogPromotionManifestService(
            self._source_scope_factory
        ).build(source_tenant_id)
        preflight = await CatalogPromotionPreflightService(
            self._target_scope_factory
        ).inspect(manifest, target_tenant_id=target_tenant_id)
        return CatalogPromotionReleasePreview(
            source_tenant_id=source_tenant_id,
            target_tenant_id=target_tenant_id,
            manifest=manifest,
            preflight=preflight,
            approval_phrase=catalog_promotion_approval_phrase(
                manifest,
                target_tenant_id,
            ),
        )

    async def apply(
        self,
        preview: CatalogPromotionReleasePreview,
        *,
        approval_phrase: str,
        context: AdminCommandContext,
        reason: str,
    ) -> CatalogPromotionReleaseResult:
        """Apply a ready preview or verify an exact durable replay."""
        if not compare_digest(approval_phrase, preview.approval_phrase):
            raise CatalogPromotionReleaseError(
                "approval_required",
                "Exact catalog promotion approval phrase is required.",
            )
        if preview.preflight.status is CatalogPromotionPreflightStatus.READY:
            imported = await CatalogPromotionImportService(
                self._target_scope_factory
            ).apply(
                CatalogPromotionImportCommand(
                    manifest=preview.manifest,
                    preflight=preview.preflight,
                    approval_phrase=approval_phrase,
                    context=context,
                    reason=reason,
                )
            )
        elif preview.preflight.status is CatalogPromotionPreflightStatus.NO_CHANGES:
            imported = await self._load_replay(
                preview,
                context=context,
                reason=reason,
            )
        else:
            raise CatalogPromotionReleaseError(
                "preflight_blocked",
                "Target preflight is blocked; no release was attempted.",
            )

        verification = await self.verify(preview, action_id=imported.action_id)
        return CatalogPromotionReleaseResult(
            imported=imported,
            verification=verification,
        )

    async def verify(
        self,
        preview: CatalogPromotionReleasePreview,
        *,
        action_id: UUID,
    ) -> CatalogPromotionReleaseVerification:
        """Verify target state and immutable audit after commit or restart."""
        target_tenant_id = preview.target_tenant_id
        postflight = await CatalogPromotionPreflightService(
            self._target_scope_factory
        ).inspect(preview.manifest, target_tenant_id=target_tenant_id)
        products_present = 0
        links_present = 0
        async with self._target_scope_factory() as repositories:
            for product in preview.manifest.products:
                stored = await repositories.canonical_products.get_by_tenant_and_id(
                    target_tenant_id,
                    product.id,
                )
                if stored is not None:
                    products_present += 1
            for link in preview.manifest.links:
                offer = await repositories.offers.get_by_identity(
                    target_tenant_id,
                    link.marketplace,
                    link.external_id,
                )
                if (
                    offer is not None
                    and offer.canonical_product_id == link.canonical_product_id
                ):
                    links_present += 1
            audit = await repositories.admin_actions.list_for_resource(
                AdminResourceType.CATALOG_PROMOTION,
                catalog_promotion_resource_id(
                    target_tenant_id,
                    preview.manifest.digest,
                ),
            )
        return CatalogPromotionReleaseVerification(
            postflight=postflight,
            products_present=products_present,
            links_present=links_present,
            audit_present=any(action.id == action_id for action in audit),
        )

    async def _load_replay(
        self,
        preview: CatalogPromotionReleasePreview,
        *,
        context: AdminCommandContext,
        reason: str,
    ) -> CatalogPromotionImportResult:
        target_tenant_id = preview.target_tenant_id
        if context.tenant_id != target_tenant_id:
            raise CatalogPromotionReleaseError(
                "tenant_context_mismatch",
                "Command tenant does not match the release target.",
            )
        async with self._target_scope_factory() as repositories:
            action = await repositories.admin_actions.get_by_idempotency_key(
                context.idempotency_key,
                target_tenant_id,
            )
        resource_id = catalog_promotion_resource_id(
            target_tenant_id,
            preview.manifest.digest,
        )
        normalized_reason = normalize_optional_reason(reason)
        if (
            action is None
            or action.action is not AdminActionType.IMPORT_CATALOG_PROMOTION
            or action.resource_type is not AdminResourceType.CATALOG_PROMOTION
            or action.resource_id != resource_id
            or action.actor_id != context.actor_id
            or action.actor_type is not context.actor_type
            or action.elevated != context.elevated
            or normalized_reason is None
            or action.reason != normalized_reason
        ):
            raise CatalogPromotionReleaseError(
                "replay_not_found",
                "No matching durable catalog promotion exists for this command.",
            )
        metadata = dict(action.metadata)
        if metadata.get("manifest_digest") != preview.manifest.digest:
            raise CatalogPromotionReleaseError(
                "replay_manifest_mismatch",
                "Durable promotion audit is bound to another manifest.",
            )
        try:
            products_created = int(metadata["products_created"])
            links_created = int(metadata["links_created"])
        except (KeyError, ValueError) as error:
            raise CatalogPromotionReleaseError(
                "invalid_release_audit",
                "Durable promotion audit metadata is incomplete.",
            ) from error
        return CatalogPromotionImportResult(
            action_id=action.id,
            target_tenant_id=target_tenant_id,
            manifest_digest=preview.manifest.digest,
            products_created=products_created,
            links_created=links_created,
            replayed=True,
        )
