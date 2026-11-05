from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from hmac import compare_digest
from uuid import UUID

from app.domain.canonical_offer_decisions import (
    CanonicalOfferDecision,
    CanonicalOfferDecisionType,
)
from app.domain.identity import normalize_utc, validate_sha256
from app.models.canonical_product import CanonicalProduct
from app.parsers.models import ParsedOffer
from app.services.repository_scope import RepositoryScopeFactory

CATALOG_PROMOTION_MANIFEST_SCHEMA = "mediaengine.catalog-promotion.v1"


@dataclass(slots=True, frozen=True, kw_only=True)
class CatalogPromotionSummary:
    """Source-state counts retained as promotion audit evidence."""

    active_offers: int
    canonical_products: int
    terminal_decisions: int
    confirmed_decisions: int
    rejected_decisions: int
    excluded_confirmed_decisions: int
    promoted_products: int
    promoted_links: int

    def to_payload(self) -> dict[str, int]:
        """Return a stable JSON-compatible representation."""
        return {
            "active_offers": self.active_offers,
            "canonical_products": self.canonical_products,
            "confirmed_decisions": self.confirmed_decisions,
            "excluded_confirmed_decisions": self.excluded_confirmed_decisions,
            "promoted_links": self.promoted_links,
            "promoted_products": self.promoted_products,
            "rejected_decisions": self.rejected_decisions,
            "terminal_decisions": self.terminal_decisions,
        }


@dataclass(slots=True, frozen=True, kw_only=True)
class CatalogPromotionProduct:
    """Canonical product definition required by promoted reviewed links."""

    id: UUID
    name: str
    category: str
    aliases: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        """Return a stable JSON-compatible representation."""
        return {
            "aliases": list(self.aliases),
            "category": self.category,
            "id": str(self.id),
            "name": self.name,
        }


@dataclass(slots=True, frozen=True, kw_only=True)
class CatalogPromotionLink:
    """One active source offer backed by an immutable confirmed decision."""

    marketplace: str
    external_id: str
    canonical_product_id: UUID
    source_title: str
    source_url: str
    source_category_id: str | None
    source_category_name: str | None
    catalog_hub_code: str | None
    catalog_section_code: str | None
    source_fingerprint: str
    decision_id: UUID
    decision_fingerprint: str
    decision_created_at: datetime
    decision_reason: str | None

    def __post_init__(self) -> None:
        """Validate immutable hashes and normalize the decision timestamp."""
        validate_sha256(
            self.source_fingerprint,
            field_name="Catalog promotion source fingerprint",
        )
        validate_sha256(
            self.decision_fingerprint,
            field_name="Catalog promotion decision fingerprint",
        )
        object.__setattr__(
            self,
            "decision_created_at",
            normalize_utc(
                self.decision_created_at,
                field_name="decision_created_at",
            ),
        )

    def to_payload(self) -> dict[str, object]:
        """Return a stable JSON-compatible representation."""
        return {
            "canonical_product_id": str(self.canonical_product_id),
            "catalog_hub_code": self.catalog_hub_code,
            "catalog_section_code": self.catalog_section_code,
            "decision_created_at": _utc_text(self.decision_created_at),
            "decision_fingerprint": self.decision_fingerprint,
            "decision_id": str(self.decision_id),
            "decision_reason": self.decision_reason,
            "external_id": self.external_id,
            "marketplace": self.marketplace,
            "source_category_id": self.source_category_id,
            "source_category_name": self.source_category_name,
            "source_fingerprint": self.source_fingerprint,
            "source_title": self.source_title,
            "source_url": self.source_url,
        }


@dataclass(slots=True, frozen=True, kw_only=True)
class CatalogPromotionManifest:
    """Deterministic read-only artifact for a reviewed catalog promotion."""

    source_tenant_id: UUID
    summary: CatalogPromotionSummary
    products: tuple[CatalogPromotionProduct, ...]
    links: tuple[CatalogPromotionLink, ...]
    digest: str
    schema: str = CATALOG_PROMOTION_MANIFEST_SCHEMA

    def __post_init__(self) -> None:
        """Reject unsupported schema identifiers and malformed digests."""
        if self.schema != CATALOG_PROMOTION_MANIFEST_SCHEMA:
            msg = f"Unsupported catalog promotion schema: {self.schema}."
            raise ValueError(msg)
        validate_sha256(
            self.digest,
            field_name="Catalog promotion manifest digest",
        )

    def unsigned_payload(self) -> dict[str, object]:
        """Return the canonical payload covered by the manifest digest."""
        return {
            "links": [link.to_payload() for link in self.links],
            "products": [product.to_payload() for product in self.products],
            "schema": self.schema,
            "source_tenant_id": str(self.source_tenant_id),
            "summary": self.summary.to_payload(),
        }

    def to_payload(self) -> dict[str, object]:
        """Return the complete JSON-compatible artifact."""
        payload = self.unsigned_payload()
        payload["digest"] = self.digest
        return payload

    def to_json(self) -> str:
        """Serialize the manifest for review without changing its digest."""
        return json.dumps(
            self.to_payload(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )

    def has_valid_digest(self) -> bool:
        """Return whether the current fields match the recorded digest."""
        return compare_digest(self.digest, _payload_digest(self.unsigned_payload()))


class CatalogPromotionManifestError(RuntimeError):
    """Raised when reviewed catalog state is unsafe to promote."""


class CatalogPromotionManifestService:
    """Build a read-only promotion artifact from one consistent tenant scope."""

    def __init__(self, repository_scope_factory: RepositoryScopeFactory) -> None:
        self._repository_scope_factory = repository_scope_factory

    async def build(self, tenant_id: UUID) -> CatalogPromotionManifest:
        """Return only active links backed by confirmed immutable decisions."""
        async with self._repository_scope_factory() as repositories:
            offers = tuple(await repositories.offers.list_by_tenant(tenant_id))
            products = tuple(
                await repositories.canonical_products.list_by_tenant(tenant_id)
            )
            decisions = tuple(
                await repositories.canonical_offer_decisions.list_by_tenant(tenant_id)
            )

        products_by_id = {product.id: product for product in products}
        decisions_by_pair = {
            (
                decision.marketplace,
                decision.external_id,
                decision.canonical_product_id,
            ): decision
            for decision in decisions
        }
        linked_offers = sorted(
            (offer for offer in offers if offer.canonical_product_id is not None),
            key=_offer_sort_key,
        )
        if not linked_offers:
            raise CatalogPromotionManifestError(
                "Catalog promotion requires at least one active reviewed link."
            )

        manifest_links: list[CatalogPromotionLink] = []
        referenced_product_ids: set[UUID] = set()
        for offer in linked_offers:
            marketplace = _required_offer_text(
                offer.marketplace,
                field_name="marketplace",
            ).lower()
            external_id = _required_offer_text(
                offer.external_id,
                field_name="external_id",
            )
            canonical_product_id = offer.canonical_product_id
            if canonical_product_id is None:
                raise AssertionError("Linked offer lost its canonical product ID.")
            product = products_by_id.get(canonical_product_id)
            if product is None:
                raise CatalogPromotionManifestError(
                    "Active offer link references an unavailable canonical product."
                )
            decision = decisions_by_pair.get(
                (marketplace, external_id, canonical_product_id)
            )
            if (
                decision is None
                or decision.decision is not CanonicalOfferDecisionType.CONFIRMED
            ):
                raise CatalogPromotionManifestError(
                    "Active offer link is not backed by a confirmed decision."
                )
            manifest_links.append(_promotion_link(offer, decision))
            referenced_product_ids.add(canonical_product_id)

        manifest_products = tuple(
            _promotion_product(products_by_id[product_id])
            for product_id in sorted(referenced_product_ids, key=lambda item: item.hex)
        )
        confirmed_decisions = tuple(
            decision
            for decision in decisions
            if decision.decision is CanonicalOfferDecisionType.CONFIRMED
        )
        active_pairs = {
            (link.marketplace, link.external_id, link.canonical_product_id)
            for link in manifest_links
        }
        excluded_confirmed = sum(
            (
                decision.marketplace,
                decision.external_id,
                decision.canonical_product_id,
            )
            not in active_pairs
            for decision in confirmed_decisions
        )
        summary = CatalogPromotionSummary(
            active_offers=len(offers),
            canonical_products=len(products),
            terminal_decisions=len(decisions),
            confirmed_decisions=len(confirmed_decisions),
            rejected_decisions=sum(
                decision.decision is CanonicalOfferDecisionType.REJECTED
                for decision in decisions
            ),
            excluded_confirmed_decisions=excluded_confirmed,
            promoted_products=len(manifest_products),
            promoted_links=len(manifest_links),
        )
        links = tuple(manifest_links)
        unsigned_payload = _unsigned_payload(
            tenant_id=tenant_id,
            summary=summary,
            products=manifest_products,
            links=links,
        )
        return CatalogPromotionManifest(
            source_tenant_id=tenant_id,
            summary=summary,
            products=manifest_products,
            links=links,
            digest=_payload_digest(unsigned_payload),
        )


def _promotion_product(product: CanonicalProduct) -> CatalogPromotionProduct:
    name = _required_manifest_text(
        product.name,
        field_name="canonical product name",
    )
    category = _required_manifest_text(
        product.category,
        field_name="canonical product category",
    )
    aliases = tuple(
        _required_manifest_text(alias, field_name="canonical product alias")
        for alias in product.aliases
    )
    return CatalogPromotionProduct(
        id=product.id,
        name=name,
        category=category,
        aliases=aliases,
    )


def _promotion_link(
    offer: ParsedOffer,
    decision: CanonicalOfferDecision,
) -> CatalogPromotionLink:
    marketplace = _required_offer_text(
        offer.marketplace,
        field_name="marketplace",
    ).lower()
    external_id = _required_offer_text(offer.external_id, field_name="external_id")
    title = _required_offer_text(offer.title, field_name="title")
    url = _required_offer_text(offer.url, field_name="url")
    canonical_product_id = offer.canonical_product_id
    if canonical_product_id is None:
        raise AssertionError("Linked offer lost its canonical product ID.")
    source_payload: dict[str, object] = {
        "catalog_hub_code": _optional_text(offer.catalog_hub_code),
        "catalog_section_code": _optional_text(offer.catalog_section_code),
        "external_id": external_id,
        "marketplace": marketplace,
        "source_category_id": _optional_text(offer.source_category_id),
        "source_category_name": _optional_text(offer.source_category_name),
        "title": title,
        "url": url,
    }
    return CatalogPromotionLink(
        marketplace=marketplace,
        external_id=external_id,
        canonical_product_id=canonical_product_id,
        source_title=title,
        source_url=url,
        source_category_id=_optional_text(offer.source_category_id),
        source_category_name=_optional_text(offer.source_category_name),
        catalog_hub_code=_optional_text(offer.catalog_hub_code),
        catalog_section_code=_optional_text(offer.catalog_section_code),
        source_fingerprint=_payload_digest(source_payload),
        decision_id=decision.id,
        decision_fingerprint=decision.request_fingerprint,
        decision_created_at=decision.created_at,
        decision_reason=decision.reason,
    )


def _unsigned_payload(
    *,
    tenant_id: UUID,
    summary: CatalogPromotionSummary,
    products: tuple[CatalogPromotionProduct, ...],
    links: tuple[CatalogPromotionLink, ...],
) -> dict[str, object]:
    return {
        "links": [link.to_payload() for link in links],
        "products": [product.to_payload() for product in products],
        "schema": CATALOG_PROMOTION_MANIFEST_SCHEMA,
        "source_tenant_id": str(tenant_id),
        "summary": summary.to_payload(),
    }


def _payload_digest(payload: dict[str, object]) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


def _offer_sort_key(offer: ParsedOffer) -> tuple[str, str, str]:
    return (
        offer.marketplace.strip().lower(),
        (offer.external_id or "").strip(),
        str(offer.canonical_product_id or ""),
    )


def _required_offer_text(value: str | None, *, field_name: str) -> str:
    try:
        return _required_text(value, field_name=f"offer {field_name}")
    except ValueError as error:
        raise CatalogPromotionManifestError(str(error)) from error


def _required_manifest_text(value: str | None, *, field_name: str) -> str:
    try:
        return _required_text(value, field_name=field_name)
    except ValueError as error:
        raise CatalogPromotionManifestError(str(error)) from error


def _required_text(value: str | None, *, field_name: str) -> str:
    normalized = (value or "").strip()
    if not normalized:
        msg = f"{field_name} must not be empty."
        raise ValueError(msg)
    return normalized


def _optional_text(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return normalized or None


def _utc_text(value: datetime) -> str:
    return (
        normalize_utc(value, field_name="datetime")
        .isoformat()
        .replace(
            "+00:00",
            "Z",
        )
    )
