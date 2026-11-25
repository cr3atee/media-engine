"""Stage source candidates for existing human review; never approve or publish."""

from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import UUID

from app.domain.marketplace_integrations import MarketplaceIntegrationStatus
from app.matching.confidence import MatchDecision
from app.matching.service import MatchingService
from app.repositories.offers import OfferObservationContext
from app.services.canonical_offer_review_queue import (
    build_canonical_product_proposal,
    resolve_unreviewed_offer_match,
)
from app.services.cheaper_offer_discovery import CheaperOfferSourceResult, _valid_quote
from app.services.repository_scope import RepositoryScopeFactory
from app.services.subscription_candidate_rules import LAUNCH_PRODUCTS, LAUNCH_SOURCES


@dataclass(slots=True, frozen=True)
class CandidateIntakeResult:
    """One staged or safely skipped source identity, not a review decision."""

    marketplace: str
    external_id: str
    status: str


class CheaperOfferReviewIntakeService:
    """Reuse repository scopes, source rules and the current matching/review path."""

    def __init__(self, repository_scope_factory: RepositoryScopeFactory) -> None:
        self._scope = repository_scope_factory
        self._matching = MatchingService()

    async def stage(
        self,
        tenant_id: UUID,
        reports: tuple[CheaperOfferSourceResult, ...],
    ) -> tuple[CandidateIntakeResult, ...]:
        """Insert new unlinked offers atomically, never overwrite reviewed state."""
        allowed = {
            **{("ggsel", spec.hub_code): spec.category_url for spec in LAUNCH_PRODUCTS},
            **{("funpay", spec.hub_code): spec.category_url for spec in LAUNCH_SOURCES},
        }
        incoming = [
            (report, item)
            for report in reports
            if report.error_code is None
            for item in report.candidates
        ]
        identities = [
            (item.offer.marketplace, item.offer.external_id) for _, item in incoming
        ]
        if (
            len(reports) > 6
            or any(len(item.candidates) > 3 for item in reports)
            or len({(item.marketplace, item.hub_code) for item in reports})
            != len(reports)
            or len(incoming) > 18
            or len(set(identities)) != len(identities)
        ):
            raise ValueError("Candidate intake must be bounded and unambiguous.")
        outcomes: list[CandidateIntakeResult] = []
        async with self._scope() as repositories:
            tenant = await repositories.tenants.get_by_id(tenant_id)
            if tenant is None or not tenant.is_active:
                raise ValueError("Active review tenant is required.")
            products = await repositories.canonical_products.list_by_tenant(tenant_id)
            rules = await repositories.catalog_source_rules.list_by_tenant(tenant_id)
            integrations = await repositories.marketplace_integrations.list_by_tenant(
                tenant_id
            )
            for report, item in sorted(
                incoming,
                key=lambda pair: (
                    pair[1].offer.marketplace,
                    pair[1].offer.external_id or "",
                ),
            ):
                offer = item.offer
                reference = report.reference_offer
                if (
                    report.source_url
                    != allowed.get((report.marketplace, report.hub_code))
                    or not _valid_quote(offer)
                    or not _valid_quote(reference)
                    or offer.tenant_id != tenant_id
                    or reference.tenant_id != tenant_id
                    or offer.marketplace != report.marketplace
                    or offer.canonical_product_id is not None
                    or offer.activation_conditions is not None
                    or reference.catalog_hub_code != report.hub_code
                    or reference.catalog_section_code != "subscriptions"
                    or reference.canonical_product_id not in {p.id for p in products}
                    or offer.currency != reference.currency
                    or offer.price is None
                    or reference.price is None
                    or offer.price >= reference.price
                ):
                    raise ValueError(
                        "Candidate differs from the captured review scope."
                    )
                assert offer.external_id is not None
                await repositories.canonical_offer_decisions.acquire_offer_lock(
                    tenant_id, offer.marketplace, offer.external_id
                )
                decisions = await repositories.canonical_offer_decisions.list_for_offer(
                    tenant_id, offer.marketplace, offer.external_id
                )
                state = await repositories.offers.get_availability_state(
                    tenant_id, offer.marketplace, offer.external_id
                )
                if decisions or state is not None:
                    outcomes.append(
                        CandidateIntakeResult(
                            offer.marketplace, offer.external_id, "already_known"
                        )
                    )
                    continue
                sources = [
                    (rule, integration)
                    for rule in rules
                    for integration in integrations
                    if rule.integration_id == integration.id
                    and rule.marketplace == offer.marketplace
                    and rule.source_category_id == offer.source_category_id
                    and rule.hub_code == report.hub_code
                    and rule.section_code == "subscriptions"
                    and integration.marketplace == offer.marketplace
                    and integration.source_url == report.source_url
                    and integration.enabled
                    and integration.status is MarketplaceIntegrationStatus.ACTIVE
                ]
                if len(sources) != 1:
                    outcomes.append(
                        CandidateIntakeResult(
                            offer.marketplace,
                            offer.external_id,
                            "source_mapping_unavailable",
                        )
                    )
                    continue
                match = resolve_unreviewed_offer_match(
                    offer, products, set(), self._matching
                )
                if (
                    match is None
                    or match.canonical_product is None
                    or match.canonical_product.id != reference.canonical_product_id
                    or match.decision is MatchDecision.AUTO_MATCH
                    or (
                        match.decision is MatchDecision.NO_MATCH
                        and build_canonical_product_proposal(tenant_id, offer, match)
                        is None
                    )
                ):
                    outcomes.append(
                        CandidateIntakeResult(
                            offer.marketplace,
                            offer.external_id,
                            "manual_target_review_needed",
                        )
                    )
                    continue
                rule, integration = sources[0]
                await repositories.offers.save_observed(
                    OfferObservationContext(
                        tenant_id=tenant_id,
                        integration_id=integration.id,
                        marketplace=offer.marketplace,
                        observed_at=report.observed_at,
                    ),
                    replace(
                        offer,
                        catalog_hub_code=rule.hub_code,
                        catalog_section_code=rule.section_code,
                        catalog_source_rule_id=rule.id,
                    ),
                )
                outcomes.append(
                    CandidateIntakeResult(
                        offer.marketplace, offer.external_id, "staged_for_review"
                    )
                )
        return tuple(outcomes)
