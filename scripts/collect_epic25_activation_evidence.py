"""Capture bounded public source descriptions, never conditions or approvals."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.http_client import HttpClient  # noqa: E402
from app.parsers.funpay_fetcher import FunPayFetcher, FunPayFetchError  # noqa: E402
from app.parsers.ggsel_fetcher import GGSelFetcher, GGSelFetchError  # noqa: E402

LIVE_ENV = "EPIC25_ACTIVATION_EVIDENCE_LIVE"
LIVE_GUARD = "I_UNDERSTAND_THIS_READS_PUBLIC_OFFER_PAGES"

# Observed identities, not a claim that these are equivalent or still cheapest.
SOURCES = (
    (
        "ExitLag",
        "ggsel",
        "5077855",
        "https://ggsel.net/en/catalog/product/podpiska-exitlag-30-dnei-kliuc-rossiia-157-stran-5077855",
    ),
    (
        "Duolingo",
        "ggsel",
        "103585387",
        "https://ggsel.net/en/catalog/product/kliuc-duolingo-super-1-mesiac-momentalnaia-avto-vydaca-103585387",
    ),
    (
        "Spotify",
        "ggsel",
        "102361507",
        "https://ggsel.net/en/catalog/product/premium-podpiska-dlia-individualnyx-polzovatelei-na-1-mesiac-v-spotify-10-legalno-102361507",
    ),
    ("ExitLag", "funpay", "82792757", "https://funpay.com/lots/offer?id=82792757"),
    ("ExitLag", "funpay", "19847269", "https://funpay.com/lots/offer?id=19847269"),
    ("Duolingo", "funpay", "82765333", "https://funpay.com/lots/offer?id=82765333"),
    ("Duolingo", "funpay", "81387965", "https://funpay.com/lots/offer?id=81387965"),
    ("Spotify", "funpay", "21964871", "https://funpay.com/lots/offer?id=21964871"),
    ("Spotify", "funpay", "48132628", "https://funpay.com/lots/offer?id=48132628"),
)


@dataclass(frozen=True, slots=True)
class SourceSection:
    """Uninterpreted visible text from one observed source-page section."""

    label: str
    text: str


class EvidenceStructureError(ValueError):
    """A detail page does not expose the expected unambiguous source blocks."""


class _Sections(HTMLParser):
    """Collect only source title/description blocks, excluding scripts/reviews."""

    _VOID = frozenset(
        "area base br col embed hr img input link meta param source track wbr".split()
    )
    _BLOCKS = frozenset({"br", "p", "div", "li", "h5"})

    def __init__(self, marketplace: str) -> None:
        super().__init__(convert_charrefs=True)
        self.marketplace = marketplace
        self.sections: list[SourceSection] = []
        self._stack: list[tuple[str, dict[str, str | None]]] = []
        self._active: tuple[int, str, list[str]] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if self._active is not None and tag in self._BLOCKS:
            self._active[2].append("\n")
        if tag in self._VOID:
            return
        self._stack.append((tag, values))
        if self._active is not None:
            return
        label = ""
        if self.marketplace == "ggsel":
            if tag == "h1":
                label = "title"
            elif values.get("data-testid") == "seo-text" and any(
                item.get("data-testid") == "product-info-section"
                for _, item in self._stack[:-1]
            ):
                label = "description"
        elif (
            tag == "div"
            and "param-item" in (values.get("class") or "").split()
            and any(
                "param-list" in (item.get("class") or "").split()
                for _, item in self._stack[:-1]
            )
        ):
            label = "parameter"
        if label:
            self._active = (len(self._stack), label, [])

    def handle_endtag(self, tag: str) -> None:
        position = next(
            (
                i
                for i in range(len(self._stack) - 1, -1, -1)
                if self._stack[i][0] == tag
            ),
            None,
        )
        if position is None:
            return
        if self._active is not None:
            depth, label, parts = self._active
            if position + 1 == depth:
                lines = [" ".join(line.split()) for line in "".join(parts).splitlines()]
                lines = [line for line in lines if line]
                if label == "parameter" and len(lines) >= 2:
                    label, lines = lines[0], lines[1:]
                self.sections.append(SourceSection(label, "\n".join(lines)))
                self._active = None
            elif tag in self._BLOCKS:
                parts.append("\n")
        del self._stack[position:]

    def handle_data(self, data: str) -> None:
        if self._active is not None and not any(
            tag in {"script", "style", "template"} for tag, _ in self._stack
        ):
            self._active[2].append(data)


def extract_sections(marketplace: str, html: str) -> tuple[SourceSection, ...]:
    """Fail closed on missing/duplicate detail sections; never infer conditions."""
    if marketplace not in {"ggsel", "funpay"}:
        raise EvidenceStructureError("Unsupported evidence marketplace.")
    parser = _Sections(marketplace)
    parser.feed(html)
    parser.close()
    required = (
        {"title", "description"}
        if marketplace == "ggsel"
        else {"Краткое описание", "Подробное описание"}
    )
    if parser._active is not None or any(
        len([item for item in parser.sections if item.label == label]) != 1
        or not any(item.label == label and item.text for item in parser.sections)
        for label in required
    ):
        raise EvidenceStructureError("Detail sections are missing or ambiguous.")
    return tuple(parser.sections)


async def collect(http: HttpClient) -> tuple[list[dict[str, object]], int]:
    """Read only the fixed nine known offers through the existing HTTP fetchers."""
    items: list[dict[str, object]] = []
    failures = 0
    for service, marketplace, identity, url in SOURCES:
        fetcher = GGSelFetcher(http) if marketplace == "ggsel" else FunPayFetcher(http)
        record: dict[str, object] = {
            "service": service,
            "marketplace": marketplace,
            "requested_offer_id": identity,
            "requested_url": url,
            "observed_at": datetime.now(UTC).isoformat(),
        }
        try:
            html = (
                await fetcher.fetch_html(url)
                if isinstance(fetcher, GGSelFetcher)
                else await fetcher.fetch(url)
            )
            record["response_sha256"] = sha256(html.encode("utf-8")).hexdigest()
            sections = extract_sections(marketplace, html)
            section_records = [asdict(section) for section in sections]
            record["sections"] = section_records
            record["sections_sha256"] = sha256(
                json.dumps(section_records, ensure_ascii=False, sort_keys=True).encode()
            ).hexdigest()
            record["status"] = "captured_not_approved"
        except (
            GGSelFetchError,
            FunPayFetchError,
            httpx.RequestError,
            EvidenceStructureError,
        ) as error:
            record["status"] = "capture_failed"
            record["error_type"] = type(error).__name__
            failures += 1
        record["http_status"] = fetcher.last_status_code
        if isinstance(fetcher, FunPayFetcher):
            record["observed_url"] = fetcher.last_url
        items.append(record)
        print(
            f"{record['status']}: {marketplace}/{identity}, "
            f"HTTP {fetcher.last_status_code}"
        )
        await asyncio.sleep(1)
    return items, failures


async def main() -> int:
    """Save a local temporary evidence artifact, never database or application data."""
    if os.getenv(LIVE_ENV) != LIVE_GUARD:
        print(f"NOT RUN: set {LIVE_ENV}={LIVE_GUARD} for read-only public requests.")
        return 2
    async with HttpClient(timeout=30, max_retries=1) as http:
        items, failures = await collect(http)
    output = Path(tempfile.mkdtemp(prefix="mediaengine-activation-evidence-"))
    artifact = output / "source-sections.json"
    artifact.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "scope": "source_text_only_not_approval",
                "items": items,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Evidence artifact: {artifact}")
    print(
        f"Captured {len(items) - failures}/{len(items)} known pages; "
        f"failures={failures}."
    )
    print("No parsed offers, conditions, decisions, prices or database writes created.")
    print(
        "Not a seller certification, availability proof or equivalent-price comparison."
    )
    return 1 if failures else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    raise SystemExit(asyncio.run(main()))
