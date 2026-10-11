"""Verify the guarded catalog decision path through the public catalog."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from httpx import ASGITransport, AsyncClient, Response

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_catalog_review_preview import (
    PREVIEW_EMAIL,
    PREVIEW_PASSWORD,
    TENANT_ID,
    prepare_preview,
)


@dataclass(slots=True)
class Verification:
    """Collect deterministic checks and fail with a useful diagnostic."""

    checks: int = 0

    def expect(self, condition: bool, label: str) -> None:
        """Record one successful check or stop at the first broken invariant."""
        if not condition:
            raise RuntimeError(f"Catalog onboarding verification failed: {label}.")
        self.checks += 1

    def status(self, response: Response, expected: int, label: str) -> None:
        """Require one HTTP response status while keeping the body diagnostic."""
        if response.status_code != expected:
            raise RuntimeError(
                f"Catalog onboarding verification failed: {label} returned "
                f"HTTP {response.status_code}: {response.text[:500]}"
            )
        self.checks += 1


async def verify() -> Verification:
    """Exercise one synthetic review decision through every public read view."""
    preview = await prepare_preview(saved_data=False)
    verification = Verification()
    async with AsyncClient(
        transport=ASGITransport(
            app=preview.application,
            raise_app_exceptions=False,
        ),
        base_url="http://catalog-onboarding.local",
    ) as client:
        review_document = await client.get("/terminal/review")
        public_document = await client.get("/terminal")
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": PREVIEW_EMAIL, "password": PREVIEW_PASSWORD},
        )
        verification.status(review_document, 200, "review document")
        verification.status(public_document, 200, "public document")
        verification.status(login, 200, "reviewer login")
        verification.expect(
            'id="proposalList"' in review_document.text,
            "review document has the proposal queue",
        )
        verification.expect(
            'id="productGrid"' in public_document.text,
            "public document has the product collection",
        )

        login_body = _body(login)
        headers = {
            "Authorization": f"Bearer {login_body['access_token']}",
        }
        workspace_url = (
            f"/api/v1/tenants/{TENANT_ID}/catalog/onboarding-workspace?limit=100"
        )
        workspace_before = await client.get(workspace_url, headers=headers)
        public_before = await client.get("/api/v1/public/products?q=Stardew")
        verification.status(workspace_before, 200, "initial onboarding workspace")
        verification.status(public_before, 200, "initial public product search")

        workspace_before_body = _body(workspace_before)
        proposals = cast(
            list[dict[str, Any]], workspace_before_body["product_proposals"]
        )
        verification.expect(len(proposals) == 1, "one synthetic proposal is actionable")
        verification.expect(
            _body(public_before)["items"] == [],
            "unreviewed proposal is absent from the public catalog",
        )

        proposal = proposals[0]
        proposal_id = str(proposal["proposal_id"])
        confirm_url = (
            f"/api/v1/tenants/{TENANT_ID}/catalog/product-proposals/"
            f"{proposal_id}/confirm"
        )
        command_headers = {
            **headers,
            "Idempotency-Key": "catalog-onboarding-end-to-end",
        }
        payload = {
            "marketplace": proposal["marketplace"],
            "external_id": proposal["external_id"],
            "reason": "Synthetic end-to-end verification",
        }
        confirmed = await client.post(
            confirm_url,
            headers=command_headers,
            json=payload,
        )
        replayed = await client.post(
            confirm_url,
            headers=command_headers,
            json=payload,
        )
        verification.status(confirmed, 200, "proposal confirmation")
        verification.status(replayed, 200, "idempotent proposal replay")

        confirmed_body = _body(confirmed)
        replayed_body = _body(replayed)
        product_id = str(confirmed_body["canonical_product_id"])
        verification.expect(
            confirmed_body["replayed"] is False,
            "first command is not marked as replayed",
        )
        verification.expect(
            replayed_body["replayed"] is True,
            "second command is marked as replayed",
        )
        verification.expect(
            replayed_body["decision_id"] == confirmed_body["decision_id"],
            "idempotent replay reuses the immutable decision",
        )

        workspace_after = await client.get(workspace_url, headers=headers)
        public_products = await client.get("/api/v1/public/products?q=Stardew")
        public_detail = await client.get(f"/api/v1/public/products/{product_id}")
        public_offers = await client.get(
            f"/api/v1/public/products/{product_id}/offers",
        )
        public_comparison = await client.get(
            f"/api/v1/public/products/{product_id}/comparison",
        )
        for response, label in (
            (workspace_after, "updated onboarding workspace"),
            (public_products, "public product search"),
            (public_detail, "public product detail"),
            (public_offers, "public product offers"),
            (public_comparison, "public product comparison"),
        ):
            verification.status(response, 200, label)

        summary = cast(dict[str, Any], _body(workspace_after)["summary"])
        verification.expect(summary["linked_offers"] == 1, "offer is linked")
        verification.expect(
            summary["product_proposals"] == 0,
            "resolved proposal leaves the queue",
        )
        verification.expect(
            summary["canonical_products"] == 2,
            "canonical product count increases once",
        )
        verification.expect(
            summary["terminal_decisions"] == 1,
            "one immutable review decision is recorded",
        )

        product_items = cast(list[dict[str, Any]], _body(public_products)["items"])
        verification.expect(
            len(product_items) == 1, "public search returns one product"
        )
        product = product_items[0]
        verification.expect(
            product["id"] == product_id, "public product identity matches"
        )
        verification.expect(
            product["name"] == "Stardew Valley Complete",
            "public product keeps the reviewed source name",
        )
        verification.expect(product["offer_count"] == 1, "public offer count is one")
        verification.expect(
            product["best_offer"]["price"] == "499.00",
            "public best price is source-backed",
        )

        detail = _body(public_detail)
        offer_items = cast(list[dict[str, Any]], _body(public_offers)["items"])
        comparison = _body(public_comparison)
        verification.expect(detail["id"] == product_id, "detail identity matches")
        verification.expect(
            len(offer_items) == 1, "offer list contains the linked offer"
        )
        verification.expect(
            offer_items[0]["marketplace"] == "playerok",
            "offer marketplace remains source-backed",
        )
        verification.expect(
            comparison["status"] == "complete",
            "single valid offer produces a complete comparison",
        )
        verification.expect(
            len(comparison["offers"]) == 1,
            "comparison contains the linked offer",
        )
    return verification


def _body(response: Response) -> dict[str, Any]:
    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError(
            "Catalog onboarding verification received a non-object JSON body."
        )
    return cast(dict[str, Any], body)


def main() -> int:
    """Run the isolated memory-only catalog onboarding verification."""
    _configure_stdout()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        verification = asyncio.run(verify())
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    print(
        "Catalog onboarding end-to-end verification passed: "
        f"{verification.checks}/{verification.checks} checks."
    )
    print(
        "Flow: reviewer proposal -> idempotent decision -> canonical link -> "
        "public product, offer, and comparison."
    )
    print("Dataset: synthetic, isolated, memory-only; no production data mutated.")
    return 0


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")


if __name__ == "__main__":
    raise SystemExit(main())
