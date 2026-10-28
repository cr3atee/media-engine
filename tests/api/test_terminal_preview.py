"""Contract checks for the isolated, read-only interface prototype."""

from __future__ import annotations

import hashlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.terminal import router


@pytest.fixture
def client() -> TestClient:
    """Create a route-only client without any database or authentication setup."""
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.mark.parametrize("path", ["/terminal/preview", "/terminal/preview/"])
def test_preview_is_separate_from_existing_terminal(
    client: TestClient, path: str
) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert "Предпросмотр нового интерфейса" in response.text
    assert 'href="/terminal"' in response.text
    assert "/terminal/preview/preview.js" in response.text
    assert "'unsafe-inline'" not in response.headers["content-security-policy"]
    assert "connect-src 'self'" in response.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "Предпросмотр нового интерфейса" not in client.get("/terminal").text


@pytest.mark.parametrize(
    ("asset", "media_type"),
    [
        ("preview.css", "text/css"),
        ("preview.js", "application/javascript"),
        ("presentation.js", "application/javascript"),
        ("world.svg", "image/svg+xml"),
        ("cube.svg", "image/svg+xml"),
        ("onest.ttf", "font/ttf"),
        ("funpay.ico", "image/vnd.microsoft.icon"),
        ("ggsel.ico", "image/vnd.microsoft.icon"),
        ("playerok.svg", "image/svg+xml"),
        ("minecraft-pc.jpg", "image/jpeg"),
        ("minecraft-ios.jpg", "image/jpeg"),
        ("product-placeholder.svg", "image/svg+xml"),
    ],
)
def test_preview_assets_are_local_and_typed(
    client: TestClient, asset: str, media_type: str
) -> None:
    response = client.get(f"/terminal/preview/{asset}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(media_type)
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.content


def test_preview_not_found_has_real_html_404(client: TestClient) -> None:
    response = client.get("/terminal/preview/not-found")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "content-security-policy" in response.headers
    assert '<main id="main"' in response.text


@pytest.mark.parametrize("asset", ["minecraft-pc.jpg", "minecraft-ios.jpg"])
def test_product_artwork_is_a_bounded_local_jpeg(
    client: TestClient, asset: str
) -> None:
    """Reject HTML/error bodies and unexpectedly oversized product assets."""
    response = client.get(f"/terminal/preview/{asset}")

    assert response.status_code == 200
    assert response.content.startswith(b"\xff\xd8\xff")
    assert len(response.content) < 100_000


@pytest.mark.parametrize(
    ("asset", "sha256"),
    [
        (
            "funpay.ico",
            "4be0c08d3de3623101180a0fbd962b59b6e5bbcf33dbe08fec64589c6720b3ce",
        ),
        (
            "playerok.svg",
            "3de5c6bd5a90ee31e63e3be75ebb0b6f64d3484eb670f018317a14b6f22fedb5",
        ),
        (
            "ggsel.ico",
            "df3db4c0585d4c68313a9a735b68ef1125dbdca9f42cdb5ad658b6db96833cd3",
        ),
        (
            "minecraft-pc.jpg",
            "63ea1189c4e9990dac41db94147f225d6613ebb908e81fa80cab95b8742d4117",
        ),
        (
            "minecraft-ios.jpg",
            "3d51105eb4a01bafcaeaf9376400628bf7cd223af3e423b58b5bdbba1f1dcc81",
        ),
    ],
)
def test_branded_asset_matches_provenance_registry(
    client: TestClient, asset: str, sha256: str
) -> None:
    """Detect unreviewed replacement of a source-attributed visual asset."""
    response = client.get(f"/terminal/preview/{asset}")

    assert response.status_code == 200
    assert hashlib.sha256(response.content).hexdigest() == sha256


@pytest.mark.parametrize("name", ["index.html", "OFL.txt", "secrets.env", "../.env"])
def test_asset_allowlist_does_not_expose_other_files(
    client: TestClient, name: str
) -> None:
    assert client.get(f"/terminal/preview/{name}").status_code == 404


def test_preview_does_not_accept_mutations(client: TestClient) -> None:
    assert client.post("/terminal/preview", json={"role": "admin"}).status_code == 405


def test_motion_supports_reduced_motion(client: TestClient) -> None:
    stylesheet = client.get("/terminal/preview/preview.css").text

    assert "prefers-reduced-motion: reduce" in stylesheet
    assert "transition: all" not in stylesheet
