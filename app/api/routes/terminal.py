from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response

_TERMINAL_ROOT = Path(__file__).resolve().parents[2] / "web" / "market_terminal"
_DOCUMENT_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; base-uri 'none'; connect-src 'self'; "
        "font-src 'self'; form-action 'self'; frame-ancestors 'none'; "
        "img-src 'self' data:; object-src 'none'; script-src 'self'; "
        "style-src 'self'"
    ),
    "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Content-Type-Options": "nosniff",
}
_ASSET_HEADERS = {"X-Content-Type-Options": "nosniff"}

router = APIRouter(tags=["Market Terminal"])

_PREVIEW_ASSETS = {
    "preview.css": "text/css",
    "preview.js": "application/javascript",
    "world.svg": "image/svg+xml",
    "cube.svg": "image/svg+xml",
    "onest.ttf": "font/ttf",
    "funpay.ico": "image/vnd.microsoft.icon",
    "ggsel.ico": "image/vnd.microsoft.icon",
    "playerok.svg": "image/svg+xml",
    "minecraft-pc.jpg": "image/jpeg",
    "minecraft-ios.jpg": "image/jpeg",
    "product-placeholder.svg": "image/svg+xml",
}


@router.get("/terminal/preview", include_in_schema=False)
@router.get("/terminal/preview/", include_in_schema=False)
async def market_terminal_preview() -> HTMLResponse:
    """Serve the read-only interface prototype without replacing the live UI."""
    return HTMLResponse(_read_asset("preview/index.html"), headers=_DOCUMENT_HEADERS)


@router.get("/terminal/preview/not-found", include_in_schema=False)
async def market_terminal_preview_not_found() -> HTMLResponse:
    """Demonstrate an HTML missing-page state with an actual 404 status."""
    return HTMLResponse(
        _read_asset("preview/index.html"), status_code=404, headers=_DOCUMENT_HEADERS
    )


@router.get("/terminal/preview/{name}", include_in_schema=False)
async def market_terminal_preview_asset(name: str) -> FileResponse:
    """Expose only the explicit prototype assets, never arbitrary local files."""
    if name not in _PREVIEW_ASSETS:
        raise HTTPException(status_code=404)
    return FileResponse(
        _TERMINAL_ROOT / "preview" / name,
        media_type=_PREVIEW_ASSETS[name],
        headers=_ASSET_HEADERS,
    )


@router.get("/terminal", include_in_schema=False, response_class=HTMLResponse)
async def market_terminal() -> HTMLResponse:
    """Serve the embedded Market Terminal visual shell."""
    return HTMLResponse(_read_asset("index.html"), headers=_DOCUMENT_HEADERS)


@router.get("/terminal/", include_in_schema=False, response_class=HTMLResponse)
async def market_terminal_slash() -> HTMLResponse:
    """Serve the embedded Market Terminal visual shell with trailing slash."""
    return HTMLResponse(_read_asset("index.html"), headers=_DOCUMENT_HEADERS)


@router.get(
    "/terminal/review",
    include_in_schema=False,
    response_class=HTMLResponse,
)
async def market_terminal_review() -> HTMLResponse:
    """Serve the authenticated seller catalog-review workspace."""
    return HTMLResponse(_read_asset("review.html"), headers=_DOCUMENT_HEADERS)


@router.get(
    "/terminal/review/",
    include_in_schema=False,
    response_class=HTMLResponse,
)
async def market_terminal_review_slash() -> HTMLResponse:
    """Serve the catalog-review workspace with a trailing slash."""
    return HTMLResponse(_read_asset("review.html"), headers=_DOCUMENT_HEADERS)


@router.get("/terminal/styles.css", include_in_schema=False)
async def market_terminal_styles() -> Response:
    """Serve Market Terminal styles without introducing a frontend build step."""
    return Response(
        _read_asset("styles.css"),
        media_type="text/css",
        headers=_ASSET_HEADERS,
    )


@router.get("/terminal/app.js", include_in_schema=False)
async def market_terminal_script() -> Response:
    """Serve Market Terminal browser code without introducing bundling."""
    return Response(
        _read_asset("app.js"),
        media_type="application/javascript",
        headers=_ASSET_HEADERS,
    )


@router.get("/terminal/review.css", include_in_schema=False)
async def market_terminal_review_styles() -> Response:
    """Serve styles specific to the seller catalog-review workspace."""
    return Response(
        _read_asset("review.css"),
        media_type="text/css",
        headers=_ASSET_HEADERS,
    )


@router.get("/terminal/review.js", include_in_schema=False)
async def market_terminal_review_script() -> Response:
    """Serve the dependency-free catalog-review browser client."""
    return Response(
        _read_asset("review.js"),
        media_type="application/javascript",
        headers=_ASSET_HEADERS,
    )


def _read_asset(name: str) -> str:
    return (_TERMINAL_ROOT / name).read_text(encoding="utf-8")
