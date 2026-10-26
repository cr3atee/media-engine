"""Browser refresh-cookie transport over the existing authentication service."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.dependencies import get_authentication_service, map_authentication_error
from app.api.errors import ApiError, api_error_handler
from app.api.schemas.auth import LoginRequest
from app.services.authentication import (
    AuthenticationError,
    AuthenticationService,
    TokenPair,
)

COOKIE_PATH = "/api/v1/auth/browser"
router = APIRouter(prefix=COOKIE_PATH, tags=["browser-auth"])


def require_browser_origin(request: Request) -> None:
    """Cookie mutations require an exact origin and a non-simple request header."""
    origin = str(request.base_url).rstrip("/")
    if (
        request.headers.get("origin") != origin
        or request.headers.get("x-terminal-request") != "1"
        or request.headers.get("sec-fetch-site") not in {None, "same-origin"}
    ):
        raise ApiError(403, "browser_origin_required", "Same-origin request required.")
    if request.url.scheme != "https" and not (
        request.url.hostname in {"localhost", "127.0.0.1", "::1"}
        and request.client is not None
        and request.client.host in {"localhost", "127.0.0.1", "::1"}
    ):
        raise ApiError(503, "browser_https_required", "HTTPS is required.")


def _cookie_name(request: Request) -> str:
    return (
        "__Secure-mt_refresh" if request.url.scheme == "https" else "mt_refresh_local"
    )


def _tokens(request: Request, result: TokenPair) -> JSONResponse:
    response = JSONResponse(
        {
            "access_token": result.access_token,
            "token_type": result.token_type,
            "expires_in": result.expires_in,
        },
        headers={"Cache-Control": "no-store"},
    )
    # A session cookie survives page navigation, but is not a remember-me promise.
    response.set_cookie(
        _cookie_name(request),
        result.refresh_token,
        path=COOKIE_PATH,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
    )
    return response


def _clear_cookie(request: Request, response: JSONResponse) -> JSONResponse:
    response.delete_cookie(
        _cookie_name(request),
        path=COOKIE_PATH,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/login", dependencies=[Depends(require_browser_origin)])
async def browser_login(
    request: Request,
    command: LoginRequest,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> JSONResponse:
    """Return only a short-lived access token to JavaScript."""
    try:
        result = await service.login(email=command.email, password=command.password)
    except AuthenticationError as exc:
        raise map_authentication_error(exc) from exc
    return _tokens(request, result)


@router.post("/refresh", dependencies=[Depends(require_browser_origin)])
async def browser_refresh(
    request: Request,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> JSONResponse:
    """Rotate the HttpOnly token and restore a page's in-memory access token."""
    token = request.cookies.get(_cookie_name(request), "")
    if not token:
        return _clear_cookie(
            request,
            await api_error_handler(
                request, ApiError(401, "browser_session_missing", "Sign in required.")
            ),
        )
    try:
        result = await service.refresh(refresh_token=token)
    except AuthenticationError as exc:
        response = await api_error_handler(request, map_authentication_error(exc))
        return _clear_cookie(request, response)
    return _tokens(request, result)


@router.post("/logout", dependencies=[Depends(require_browser_origin)])
async def browser_logout(
    request: Request,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> JSONResponse:
    """Revoke the existing server session before clearing its browser cookie."""
    token = request.cookies.get(_cookie_name(request))
    if token:
        await service.logout(refresh_token=token)
    return _clear_cookie(request, JSONResponse({"status": "ok"}))
