from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response

_TERMINAL_ROOT = Path(__file__).resolve().parents[2] / "web" / "market_terminal"

router = APIRouter(tags=["Market Terminal"])


@router.get("/terminal", include_in_schema=False, response_class=HTMLResponse)
async def market_terminal() -> HTMLResponse:
    """Serve the embedded Market Terminal visual shell."""
    return HTMLResponse(_read_asset("index.html"))


@router.get("/terminal/", include_in_schema=False, response_class=HTMLResponse)
async def market_terminal_slash() -> HTMLResponse:
    """Serve the embedded Market Terminal visual shell with trailing slash."""
    return HTMLResponse(_read_asset("index.html"))


@router.get("/terminal/styles.css", include_in_schema=False)
async def market_terminal_styles() -> Response:
    """Serve Market Terminal styles without introducing a frontend build step."""
    return Response(_read_asset("styles.css"), media_type="text/css")


@router.get("/terminal/app.js", include_in_schema=False)
async def market_terminal_script() -> Response:
    """Serve Market Terminal browser code without introducing bundling."""
    return Response(_read_asset("app.js"), media_type="application/javascript")


def _read_asset(name: str) -> str:
    return (_TERMINAL_ROOT / name).read_text(encoding="utf-8")
