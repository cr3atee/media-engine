from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.domain.offer_availability import OfferAvailabilityStatus
from app.models.canonical_product import CanonicalProduct
from app.repositories.provider import RepositoryProvider
from app.services.catalog_promotion_manifest import (
    CatalogPromotionManifest,
    CatalogPromotionManifestError,
    CatalogPromotionProduct,
    catalog_promotion_source_fingerprint,
)
from app.services.repository_scope import RepositoryScopeFactory


class CatalogPromotionPreflightStatus(StrEnum):
    """Deterministic outcome of a read-only target inspection."""

    READY = "ready"
    NO_CHANGES = "no_changes"
    BLOCKED = "blocked"


class CatalogPromotionProductActionType(StrEnum):
    """Allowed product operations in a later approved import."""

    CREATE = "create"
    REUSE = "reuse"


class CatalogPromotionLinkActionType(StrEnum):
    """Allowed offer-link operations in a later approved import."""

    LINK = "link"
    REUSE = "reuse"


class CatalogPromotionIssueCode(StrEnum):
    """Stable fail-closed reasons safe for operator reporting."""

    INVALID_MANIFEST = "invalid_manifest"
    TARGET_TENANT_NOT_FOUND = "target_tenant_not_found"
    TARGET_TENANT_INACTIVE = "target_tenant_inactive"
    PRODUCT_OWNED_BY_OTHER_TENANT = "product_owned_by_other_tenant"
    PRODUCT_DEFINITION_CONFLICT = "product_definition_conflict"
    SOURCE_REFRESH_REQUIRED = "source_refresh_required"
    SOURCE_EVIDENCE_MISMATCH = "source_evidence_mismatch"
    OFFER_RETIRED = "offer_retired"
    OFFER_LINK_CONFLICT = "offer_link_conflict"


@dataclass(slots=True, frozen=True, kw_only=True)
class CatalogPromotionProductAction:
    """One product operation proposed for a later approved import."""

    product_id: UUID
    action: CatalogPromotionProductActionType


@dataclass(slots=True, frozen=True, kw_only=True)
class CatalogPromotionLinkAction:
    """One marketplace-link operation proposed for a later approved import."""

    marketplace: str
    external_id: str
    canonical_product_id: UUID
    action: CatalogPromotionLinkActionType


@dataclass(slots=True, frozen=True, kw_only=True)
class CatalogPromotionIssue:
    """One sanitized blocking issue discovered in the target environment."""

    code: CatalogPromotionIssueCode
    resource: str
    detail: str


@dataclass(slots=True, frozen=True, kw_only=True)
class CatalogPromotionPreflightResult:
    """Immutable target plan produced without repository mutations."""

    target_tenant_id: UUID
    manifest_digest: str
    status: CatalogPromotionPreflightStatus
    product_actions: tuple[CatalogPromotionProductAction, ...]
    link_actions: tuple[CatalogPromotionLinkAction, ...]
    issues: tuple[CatalogPromotionIssue, ...]

    @property
    def required_mutations(self) -> int:
        """Return the number of writes a later approved import would require."""
        product_writes = sum(
            action.action is CatalogPromotionProductActionType.CREATE
            for action in self.product_actions
        )
        link_writes = sum(
            action.action is CatalogPromotionLinkActionType.LINK
            for action in self.link_actions
        )
        return product_writes + link_writes


class CatalogPromotionPreflightService:
    """Inspect one target tenant without applying a promotion manifest."""

    def __init__(self, repository_scope_factory: RepositoryScopeFactory) -> None:
        self._repository_scope_factory = repository_scope_factory

    async def inspect(
        self,
        manifest: CatalogPromotionManifest,
        *,
        target_tenant_id: UUID,
    ) -> CatalogPromotionPreflightResult:
        """Return a complete deterministic conflict report without writes."""
        async with self._repository_scope_factory() as repositories:
            return await inspect_catalog_promotion_target(
                repositories,
                manifest,
                target_tenant_id=target_tenant_id,
            )


async def inspect_catalog_promotion_target(
    repositories: RepositoryProvider,
    manifest: CatalogPromotionManifest,
    *,
    target_tenant_id: UUID,
) -> CatalogPromotionPreflightResult:
    """Inspect target state inside a caller-owned transaction scope."""
    if not manifest.has_valid_digest():
        return _blocked_result(
            target_tenant_id,
            manifest,
            CatalogPromotionIssue(
                code=CatalogPromotionIssueCode.INVALID_MANIFEST,
                resource="manifest",
                detail="Manifest digest does not match its payload.",
            ),
        )

    product_actions: list[CatalogPromotionProductAction] = []
    link_actions: list[CatalogPromotionLinkAction] = []
    issues: list[CatalogPromotionIssue] = []
    tenant = await repositories.tenants.get_by_id(target_tenant_id)
    if tenant is None:
        issues.append(
            CatalogPromotionIssue(
                code=CatalogPromotionIssueCode.TARGET_TENANT_NOT_FOUND,
                resource=f"tenant:{target_tenant_id}",
                detail="Target tenant does not exist.",
            )
        )
    elif not tenant.is_active:
        issues.append(
            CatalogPromotionIssue(
                code=CatalogPromotionIssueCode.TARGET_TENANT_INACTIVE,
                resource=f"tenant:{target_tenant_id}",
                detail="Target tenant is inactive.",
            )
        )

    for product in manifest.products:
        stored = await repositories.canonical_products.get_by_id(product.id)
        _inspect_product(
            product,
            stored,
            target_tenant_id,
            product_actions,
            issues,
        )

    for link in manifest.links:
        resource = f"offer:{link.marketplace}:{link.external_id}"
        availability = await repositories.offers.get_availability_state(
            target_tenant_id,
            link.marketplace,
            link.external_id,
        )
        if (
            availability is not None
            and availability.status is OfferAvailabilityStatus.RETIRED
        ):
            issues.append(
                CatalogPromotionIssue(
                    code=CatalogPromotionIssueCode.OFFER_RETIRED,
                    resource=resource,
                    detail="Target offer is manually retired.",
                )
            )
            continue

        offer = await repositories.offers.get_by_identity(
            target_tenant_id,
            link.marketplace,
            link.external_id,
        )
        if offer is None:
            issues.append(
                CatalogPromotionIssue(
                    code=CatalogPromotionIssueCode.SOURCE_REFRESH_REQUIRED,
                    resource=resource,
                    detail="Fresh target source evidence is required.",
                )
            )
            continue
        try:
            fingerprint = catalog_promotion_source_fingerprint(offer)
        except CatalogPromotionManifestError:
            fingerprint = ""
        if fingerprint != link.source_fingerprint:
            issues.append(
                CatalogPromotionIssue(
                    code=CatalogPromotionIssueCode.SOURCE_EVIDENCE_MISMATCH,
                    resource=resource,
                    detail="Target source evidence differs from the manifest.",
                )
            )
            continue
        if offer.canonical_product_id is None:
            action = CatalogPromotionLinkActionType.LINK
        elif offer.canonical_product_id == link.canonical_product_id:
            action = CatalogPromotionLinkActionType.REUSE
        else:
            issues.append(
                CatalogPromotionIssue(
                    code=CatalogPromotionIssueCode.OFFER_LINK_CONFLICT,
                    resource=resource,
                    detail="Target offer is linked to another product.",
                )
            )
            continue
        link_actions.append(
            CatalogPromotionLinkAction(
                marketplace=link.marketplace,
                external_id=link.external_id,
                canonical_product_id=link.canonical_product_id,
                action=action,
            )
        )

    product_result = tuple(sorted(product_actions, key=_product_action_key))
    link_result = tuple(sorted(link_actions, key=_link_action_key))
    issue_result = tuple(sorted(issues, key=_issue_key))
    if issue_result:
        status = CatalogPromotionPreflightStatus.BLOCKED
    elif any(
        action.action is CatalogPromotionProductActionType.CREATE
        for action in product_result
    ) or any(
        action.action is CatalogPromotionLinkActionType.LINK for action in link_result
    ):
        status = CatalogPromotionPreflightStatus.READY
    else:
        status = CatalogPromotionPreflightStatus.NO_CHANGES
    return CatalogPromotionPreflightResult(
        target_tenant_id=target_tenant_id,
        manifest_digest=manifest.digest,
        status=status,
        product_actions=product_result,
        link_actions=link_result,
        issues=issue_result,
    )


def _inspect_product(
    product: CatalogPromotionProduct,
    stored: CanonicalProduct | None,
    target_tenant_id: UUID,
    actions: list[CatalogPromotionProductAction],
    issues: list[CatalogPromotionIssue],
) -> None:
    resource = f"product:{product.id}"
    if stored is None:
        actions.append(
            CatalogPromotionProductAction(
                product_id=product.id,
                action=CatalogPromotionProductActionType.CREATE,
            )
        )
        return
    if stored.tenant_id != target_tenant_id:
        issues.append(
            CatalogPromotionIssue(
                code=CatalogPromotionIssueCode.PRODUCT_OWNED_BY_OTHER_TENANT,
                resource=resource,
                detail="Product ID belongs to another target tenant.",
            )
        )
        return
    if (
        stored.name != product.name
        or stored.category != product.category
        or stored.aliases != product.aliases
    ):
        issues.append(
            CatalogPromotionIssue(
                code=CatalogPromotionIssueCode.PRODUCT_DEFINITION_CONFLICT,
                resource=resource,
                detail="Target product definition differs from the manifest.",
            )
        )
        return
    actions.append(
        CatalogPromotionProductAction(
            product_id=product.id,
            action=CatalogPromotionProductActionType.REUSE,
        )
    )


def _blocked_result(
    target_tenant_id: UUID,
    manifest: CatalogPromotionManifest,
    issue: CatalogPromotionIssue,
) -> CatalogPromotionPreflightResult:
    return CatalogPromotionPreflightResult(
        target_tenant_id=target_tenant_id,
        manifest_digest=manifest.digest,
        status=CatalogPromotionPreflightStatus.BLOCKED,
        product_actions=(),
        link_actions=(),
        issues=(issue,),
    )


def _product_action_key(
    action: CatalogPromotionProductAction,
) -> tuple[str, str]:
    return action.product_id.hex, action.action.value


def _link_action_key(
    action: CatalogPromotionLinkAction,
) -> tuple[str, str, str]:
    return action.marketplace, action.external_id, action.canonical_product_id.hex


def _issue_key(issue: CatalogPromotionIssue) -> tuple[str, str]:
    return issue.resource, issue.code.value
