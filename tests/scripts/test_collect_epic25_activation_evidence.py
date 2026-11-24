from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from app.parsers.funpay_fetcher import FunPayFetcher
from app.parsers.ggsel_fetcher import GGSelFetcher, GGSelFetchError
from scripts import collect_epic25_activation_evidence as collector
from scripts.collect_epic25_activation_evidence import (
    LIVE_ENV,
    LIVE_GUARD,
    EvidenceStructureError,
    SourceSection,
    extract_sections,
    main,
)


def test_ggsel_scopes_description_not_reviews_or_script_payloads() -> None:
    sections = extract_sections(
        "ggsel",
        """<html><h1>Fixture <span>subscription</span></h1>
        <div data-testid="seo-text">Unrelated page text</div>
        <div data-testid="product-info-section"><h2>About the product</h2>
        <div data-testid="seo-text"><p>Region: RU &amp; KZ</p>
        <p>Use <strong>within 1 hour</strong>.<br/>VPN required.</p>
        <script>do_not_retain_secret_or_script()</script></div></div>
        <section>Reviews: works everywhere!</section></html>""",
    )
    assert sections == (
        SourceSection("title", "Fixture subscription"),
        SourceSection(
            "description", "Region: RU & KZ\nUse within 1 hour.\nVPN required."
        ),
    )


def test_funpay_preserves_source_labels_and_contradictory_text() -> None:
    sections = extract_sections(
        "funpay",
        """<div class="param-list"><div class="row">
        <div class="param-item"><h5>Тип устройства</h5><div>PC</div></div></div>
        <div class="param-item"><h5>Краткое описание</h5><div>Fixture</div></div>
        <div class="param-item"><h5>Подробное описание</h5><div>New only.<br>
        Existing accounts supported.<script>not a fact</script></div></div></div>
        <div class="param-item"><h5>Review</h5><div>Ignored</div></div>""",
    )
    assert sections == (
        SourceSection("Тип устройства", "PC"),
        SourceSection("Краткое описание", "Fixture"),
        SourceSection("Подробное описание", "New only.\nExisting accounts supported."),
    )


@pytest.mark.parametrize(
    ("marketplace", "html"),
    [
        ("playerok", "<h1>Unsupported</h1>"),
        ("ggsel", "<html>Complete your security check</html>"),
        ("ggsel", '<h1>Fixture</h1><div data-testid="seo-text">Wrong scope</div>'),
        (
            "ggsel",
            '<h1>A</h1><h1>B</h1><div data-testid="product-info-section">'
            '<div data-testid="seo-text">Terms</div></div>',
        ),
        (
            "ggsel",
            '<h1>Fixture</h1><div data-testid="product-info-section">'
            '<div data-testid="seo-text">Unclosed',
        ),
        (
            "ggsel",
            '<h1>Fixture</h1><div data-testid="product-info-section">'
            '<div data-testid="seo-text"></div>'
            '<div data-testid="seo-text">Terms</div></div>',
        ),
        ("funpay", "<html>Sign in</html>"),
        (
            "funpay",
            '<div class="param-list"><div class="param-item">'
            "<h5>Краткое описание</h5><div>Title only</div></div></div>",
        ),
    ],
)
def test_missing_ambiguous_or_unrelated_pages_never_become_evidence(
    marketplace: str, html: str
) -> None:
    with pytest.raises(EvidenceStructureError):
        extract_sections(marketplace, html)


def test_live_guard_requires_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(LIVE_ENV, raising=False)
    assert asyncio.run(main()) == 2
    assert "NOT RUN" in capsys.readouterr().out


def test_partial_failure_is_not_success_and_artifact_contains_only_source_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def ggsel(self: GGSelFetcher, url: str) -> str:
        self.last_status_code = 503
        raise GGSelFetchError("Do not log an upstream secret or payload")

    async def funpay(self: FunPayFetcher, url: str) -> str:
        self.last_status_code = 200
        self.last_url = url
        return (
            '<div class="param-list"><div class="param-item">'
            "<h5>Краткое описание</h5><div>Fixture</div></div>"
            '<div class="param-item"><h5>Подробное описание</h5>'
            "<div>Explicit source facts only</div></div></div>"
        )

    async def no_delay(seconds: float) -> None:
        pass

    monkeypatch.setenv(LIVE_ENV, LIVE_GUARD)
    monkeypatch.setattr(
        collector, "SOURCES", (collector.SOURCES[0], collector.SOURCES[3])
    )
    monkeypatch.setattr(GGSelFetcher, "fetch_html", ggsel)
    monkeypatch.setattr(FunPayFetcher, "fetch", funpay)
    monkeypatch.setattr(asyncio, "sleep", no_delay)
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **kwargs: str(tmp_path))
    assert asyncio.run(main()) == 1
    artifact = json.loads((tmp_path / "source-sections.json").read_text("utf-8"))
    failed, captured = artifact["items"]
    assert failed["http_status"] == 503 and failed["status"] == "capture_failed"
    assert failed["error_type"] == "GGSelFetchError"
    assert "sections" not in failed and "response_sha256" not in failed
    assert captured["status"] == "captured_not_approved"
    assert captured["observed_url"] == collector.SOURCES[1][3]
    assert captured["sections"][1]["text"] == "Explicit source facts only"
    assert len(captured["sections_sha256"]) == 64
    assert len(captured["response_sha256"]) == 64
    assert "conditions" not in captured and "price" not in captured
    assert "upstream secret" not in json.dumps(artifact)
    assert "upstream secret" not in capsys.readouterr().out
