from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID, uuid4

from app.catalog.hierarchy import (
    CatalogClassification,
    CatalogClassifier,
    CatalogHub,
    CatalogSourceRule,
)
from app.domain.admin_actions import utc_now
from app.domain.marketplace_integrations import MarketplaceIntegration
from app.parsers.models import ParsedOffer
from app.repositories.base import RepositoryIdentityConflictError
from app.repositories.provider import RepositoryProvider
from app.services.repository_scope import RepositoryScopeFactory

type Clock = Callable[[], datetime]
type RuleIdFactory = Callable[[], UUID]


@dataclass(slots=True, frozen=True, kw_only=True)
class CreateCatalogSourceRuleCommand:
    """Create one verified source-category classification rule."""

    tenant_id: UUID
    integration_id: UUID
    marketplace: str
    source_category_id: str
    hub_code: str
    section_code: str
    source_category_name: str | None = None


@dataclass(slots=True, frozen=True, kw_only=True)
class UpdateCatalogSourceRuleCommand:
    """Correct one existing source-category rule using optimistic concurrency."""

    tenant_id: UUID
    integration_id: UUID
    marketplace: str
    source_category_id: str
    hub_code: str
    section_code: str
    expected_version: int
    source_category_name: str | None = None


@dataclass(slots=True, frozen=True)
class CatalogOfferClassification:
    """Explicit classification result for one parsed marketplace offer."""

    offer: ParsedOffer
    classification: CatalogClassification | None
    rule_id: UUID | None

    def __post_init__(self) -> None:
        """Reject incomplete classification output before it reaches storage."""
        if (self.classification is None) != (self.rule_id is None):
            msg = "Catalog classification and source rule must be present together."
            raise ValueError(msg)

    def apply(self) -> ParsedOffer:
        """Return an offer carrying only a verified persisted classification."""
        if self.classification is None:
            return replace(
                self.offer,
                catalog_hub_code=None,
                catalog_section_code=None,
                catalog_source_rule_id=None,
            )
        return replace(
            self.offer,
            catalog_hub_code=self.classification.hub.code,
            catalog_section_code=self.classification.section.code,
            catalog_source_rule_id=self.rule_id,
        )


class CatalogClassificationServiceError(Exception):
    """Safe catalog-classification failure with stable API semantics."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = dict(details or {})
        super().__init__(message)


class CatalogClassificationService:
    """Manage verified rules and classify integration offers deterministically."""

    def __init__(
        self,
        repository_scope_factory: RepositoryScopeFactory,
        hubs: Sequence[CatalogHub],
        *,
        clock: Clock = utc_now,
        rule_id_factory: RuleIdFactory = uuid4,
    ) -> None:
        """Bind catalog classification to repositories and a verified taxonomy."""
        self._repository_scope_factory = repository_scope_factory
        self._hubs = tuple(hubs)
        self._hubs_by_code = _index_hubs(self._hubs)
        self._clock = clock
        self._rule_id_factory = rule_id_factory

    async def list_rules(
        self,
        tenant_id: UUID,
        integration_id: UUID,
    ) -> Sequence[CatalogSourceRule]:
        """Return verified rules for one tenant-owned integration."""
        async with self._repository_scope_factory() as repositories:
            await _require_integration(repositories, tenant_id, integration_id)
            return await repositories.catalog_source_rules.list_by_integration(
                tenant_id,
                integration_id,
            )

    async def create_rule(
        self,
        command: CreateCatalogSourceRuleCommand,
    ) -> CatalogSourceRule:
        """Create a rule without replacing an existing source identity."""
        self._require_target(command.hub_code, command.section_code)
        now = self._clock()
        try:
            rule = CatalogSourceRule(
                id=self._rule_id_factory(),
                tenant_id=command.tenant_id,
                integration_id=command.integration_id,
                marketplace=command.marketplace,
                source_category_id=command.source_category_id,
                source_category_name=command.source_category_name,
                hub_code=command.hub_code,
                section_code=command.section_code,
                created_at=now,
                updated_at=now,
            )
        except ValueError as exc:
            raise _service_error(
                "invalid_catalog_source_rule",
                "Catalog source rule payload is invalid.",
                status_code=422,
            ) from exc

        async with self._repository_scope_factory() as repositories:
            integration = await _require_integration(
                repositories,
                command.tenant_id,
                command.integration_id,
            )
            _require_marketplace(integration.marketplace, rule.marketplace)
            existing = await repositories.catalog_source_rules.get_by_source(
                command.tenant_id,
                command.integration_id,
                rule.marketplace,
                rule.source_category_id,
            )
            if existing is not None:
                raise _service_error(
                    "catalog_source_rule_conflict",
                    "Catalog source rule already exists.",
                )
            return await _save_rule(repositories, rule)

    async def update_rule(
        self,
        command: UpdateCatalogSourceRuleCommand,
    ) -> CatalogSourceRule:
        """Correct a rule only when its expected version is current."""
        if command.expected_version < 1:
            raise _service_error(
                "invalid_expected_version",
                "Expected version must be positive.",
                status_code=422,
            )
        self._require_target(command.hub_code, command.section_code)
        async with self._repository_scope_factory() as repositories:
            integration = await _require_integration(
                repositories,
                command.tenant_id,
                command.integration_id,
            )
            _require_marketplace(integration.marketplace, command.marketplace)
            existing = await repositories.catalog_source_rules.get_by_source(
                command.tenant_id,
                command.integration_id,
                command.marketplace,
                command.source_category_id,
            )
            if existing is None:
                raise _service_error(
                    "catalog_source_rule_not_found",
                    "Catalog source rule was not found.",
                    status_code=404,
                )
            if existing.version != command.expected_version:
                raise _service_error(
                    "optimistic_concurrency_conflict",
                    "Resource version does not match the expected version.",
                    details={"current_version": existing.version},
                )
            try:
                updated = replace(
                    existing,
                    source_category_name=command.source_category_name,
                    hub_code=command.hub_code,
                    section_code=command.section_code,
                    updated_at=self._clock(),
                    version=existing.version + 1,
                )
            except ValueError as exc:
                raise _service_error(
                    "invalid_catalog_source_rule",
                    "Catalog source rule payload is invalid.",
                    status_code=422,
                ) from exc
            return await _save_rule(repositories, updated)

    async def classify_offers(
        self,
        tenant_id: UUID,
        integration_id: UUID,
        offers: Sequence[ParsedOffer],
    ) -> tuple[CatalogOfferClassification, ...]:
        """Classify a batch using exact rules loaded once for its integration."""
        async with self._repository_scope_factory() as repositories:
            return await self.classify_with_repositories(
                repositories,
                tenant_id,
                integration_id,
                offers,
            )

    async def classify_with_repositories(
        self,
        repositories: RepositoryProvider,
        tenant_id: UUID,
        integration_id: UUID,
        offers: Sequence[ParsedOffer],
    ) -> tuple[CatalogOfferClassification, ...]:
        """Classify offers inside an existing repository transaction scope."""
        integration = await _require_integration(
            repositories,
            tenant_id,
            integration_id,
        )
        rules = await repositories.catalog_source_rules.list_by_integration(
            tenant_id,
            integration_id,
        )
        try:
            classifier = CatalogClassifier(
                self._hubs,
                tuple(rule.mapping() for rule in rules),
            )
        except ValueError as exc:
            raise _service_error(
                "catalog_classification_configuration_invalid",
                "Catalog classification configuration is invalid.",
                status_code=500,
            ) from exc

        rules_by_source = {
            (rule.marketplace, rule.source_category_id): rule for rule in rules
        }
        results: list[CatalogOfferClassification] = []
        for offer in offers:
            if offer.tenant_id != tenant_id:
                raise _service_error(
                    "catalog_offer_tenant_mismatch",
                    "Marketplace offer belongs to another tenant.",
                    status_code=422,
                )
            if offer.marketplace.strip().casefold() != integration.marketplace:
                raise _service_error(
                    "catalog_offer_marketplace_mismatch",
                    "Marketplace offer does not match its integration.",
                    status_code=422,
                )
            classification = classifier.classify(
                offer.marketplace,
                offer.source_category_id,
                integration_id=integration_id,
            )
            rule = (
                rules_by_source.get(
                    (
                        offer.marketplace.strip().casefold(),
                        offer.source_category_id.strip(),
                    )
                )
                if offer.source_category_id is not None
                else None
            )
            results.append(
                CatalogOfferClassification(
                    offer=offer,
                    classification=classification,
                    rule_id=rule.id if classification is not None and rule else None,
                )
            )
        return tuple(results)

    def _require_target(self, hub_code: str, section_code: str) -> None:
        normalized_hub = hub_code.strip().casefold()
        hub = self._hubs_by_code.get(normalized_hub)
        if hub is None:
            raise _service_error(
                "catalog_hub_not_found",
                "Catalog game or service was not found.",
                status_code=422,
            )
        try:
            section = hub.section(section_code)
        except ValueError as exc:
            raise _service_error(
                "catalog_section_not_found",
                "Catalog subsection was not found.",
                status_code=422,
            ) from exc
        if section is None:
            raise _service_error(
                "catalog_section_not_found",
                "Catalog subsection was not found.",
                status_code=422,
            )


def _index_hubs(hubs: Sequence[CatalogHub]) -> dict[str, CatalogHub]:
    indexed: dict[str, CatalogHub] = {}
    for hub in hubs:
        if hub.code in indexed:
            msg = f"Duplicate catalog hub code: {hub.code}."
            raise ValueError(msg)
        indexed[hub.code] = hub
    return indexed


async def _require_integration(
    repositories: RepositoryProvider,
    tenant_id: UUID,
    integration_id: UUID,
) -> MarketplaceIntegration:
    integration = await repositories.marketplace_integrations.get_by_tenant_and_id(
        tenant_id,
        integration_id,
    )
    if integration is None:
        raise _service_error(
            "marketplace_integration_not_found",
            "Marketplace integration was not found.",
            status_code=404,
        )
    return integration


def _require_marketplace(expected: str, actual: str) -> None:
    if expected != actual.strip().casefold():
        raise _service_error(
            "catalog_source_marketplace_mismatch",
            "Source category does not match its marketplace integration.",
            status_code=422,
        )


async def _save_rule(
    repositories: RepositoryProvider,
    rule: CatalogSourceRule,
) -> CatalogSourceRule:
    try:
        return await repositories.catalog_source_rules.save(rule)
    except RepositoryIdentityConflictError as exc:
        raise _service_error(
            "catalog_source_rule_conflict",
            "Catalog source rule already exists.",
        ) from exc


def _service_error(
    code: str,
    message: str,
    *,
    status_code: int = 409,
    details: Mapping[str, object] | None = None,
) -> CatalogClassificationServiceError:
    return CatalogClassificationServiceError(
        status_code,
        code,
        message,
        details=details,
    )
