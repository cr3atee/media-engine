"""Sanitized diagnostic recording and product-admin query boundary."""

from __future__ import annotations

import asyncio
import json
import re
import traceback
from collections import defaultdict, deque
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from time import monotonic
from uuid import UUID, uuid4

import structlog

from app.config.settings import DiagnosticSettings
from app.domain.auth import ActorType, AuthenticatedPrincipal
from app.domain.diagnostics import (
    DiagnosticIncident,
    DiagnosticSeverity,
    DiagnosticSource,
)
from app.domain.product_access import ProductRole
from app.domain.tenancy import utc_now
from app.repositories.provider import RepositoryProvider
from app.services.repository_scope import RepositoryScopeFactory

logger = structlog.get_logger(__name__)

_SAFE_TOKEN = re.compile(r"[^a-zA-Z0-9_.:-]+")
_FRONTEND_ROUTES = {
    "catalog": "/terminal",
    "review": "/terminal/review",
    "not_found": "/terminal/{path:path}",
}


class DiagnosticAccessError(Exception):
    """Stable authorization or rate-limit failure for the diagnostics API."""

    def __init__(self, code: str, status_code: int) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(code)


class DiagnosticService:
    """Persist diagnostics outside failed work and expose sanitized admin reads."""

    def __init__(
        self,
        scope_factory: RepositoryScopeFactory,
        configuration: DiagnosticSettings,
    ) -> None:
        self._scope_factory = scope_factory
        self._configuration = configuration
        self._fallback_lock = asyncio.Lock()
        self._rate_lock = asyncio.Lock()
        self._frontend_reports: dict[UUID, deque[float]] = defaultdict(deque)

    async def record_backend(
        self,
        *,
        request_id: str,
        route: str,
        method: str,
        error: Exception,
        status_code: int = 500,
    ) -> DiagnosticIncident:
        """Record safe exception metadata through an independent repository scope."""
        error_type = _safe_token(type(error).__name__, fallback="Exception")
        return await self._persist(
            self._build(
                source=DiagnosticSource.BACKEND,
                severity=DiagnosticSeverity.ERROR,
                code="internal_error",
                component="api",
                action="request",
                route=_safe_route(route),
                method=method,
                status_code=status_code,
                request_id=request_id,
                error_type=error_type,
                stack_frames=_safe_stack_frames(error),
            )
        )

    async def record_frontend(
        self,
        principal: AuthenticatedPrincipal,
        *,
        kind: str,
        page: str,
        component: str,
        action: str,
        request_id: str,
    ) -> DiagnosticIncident:
        """Record one allowlisted browser signal without accepting raw error text."""
        if not await self._allow_frontend_report(principal.user_id):
            raise DiagnosticAccessError("diagnostic_rate_limited", 429)
        return await self._persist(
            self._build(
                source=DiagnosticSource.FRONTEND,
                severity=DiagnosticSeverity.ERROR,
                code=_safe_token(kind, fallback="frontend_error"),
                component=_safe_token(component, fallback="shell"),
                action=_safe_token(action, fallback="render"),
                route=_FRONTEND_ROUTES.get(page, "/terminal"),
                method="CLIENT",
                status_code=None,
                request_id=request_id,
                error_type=None,
                stack_frames=(),
                user_id=principal.user_id,
            )
        )

    async def list_for_admin(
        self,
        principal: AuthenticatedPrincipal,
        *,
        source: DiagnosticSource | None,
        severity: DiagnosticSeverity | None,
        component: str | None,
        environment: str | None,
        limit: int,
        offset: int,
    ) -> tuple[tuple[DiagnosticIncident, ...], int]:
        """Read a bounded page after checking the current product role in storage."""
        async with self._scope_factory() as repositories:
            await _require_product_admin(repositories, principal)
            return await repositories.diagnostic_incidents.list_recent(
                source=source,
                severity=severity,
                component=component,
                environment=environment,
                limit=limit,
                offset=offset,
            )

    async def get_for_admin(
        self,
        principal: AuthenticatedPrincipal,
        incident_id: UUID,
    ) -> DiagnosticIncident:
        """Return one incident without exposing it to non-product administrators."""
        async with self._scope_factory() as repositories:
            await _require_product_admin(repositories, principal)
            incident = await repositories.diagnostic_incidents.get_by_id(incident_id)
            if incident is None:
                raise DiagnosticAccessError("diagnostic_not_found", 404)
            return incident

    def _build(
        self,
        *,
        source: DiagnosticSource,
        severity: DiagnosticSeverity,
        code: str,
        component: str,
        action: str,
        route: str,
        method: str,
        status_code: int | None,
        request_id: str,
        error_type: str | None,
        stack_frames: tuple[str, ...],
        user_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> DiagnosticIncident:
        now = utc_now()
        safe_request_id = _bounded(request_id, fallback="unavailable", maximum=128)
        fingerprint = _fingerprint(
            source.value,
            severity.value,
            code,
            component,
            action,
            route,
            method.upper(),
            error_type or "",
            self._configuration.environment,
            self._configuration.release,
            str(tenant_id or ""),
        )
        return DiagnosticIncident(
            id=uuid4(),
            fingerprint=fingerprint,
            source=source,
            severity=severity,
            code=code,
            component=component,
            action=action,
            route=route,
            method=method,
            status_code=status_code,
            tenant_id=tenant_id,
            user_id=user_id,
            error_type=error_type,
            environment=self._configuration.environment,
            release=self._configuration.release,
            first_request_id=safe_request_id,
            last_request_id=safe_request_id,
            stack_frames=stack_frames,
            first_seen_at=now,
            last_seen_at=now,
        )

    async def _persist(self, incident: DiagnosticIncident) -> DiagnosticIncident:
        try:
            async with asyncio.timeout(self._configuration.persistence_timeout_seconds):
                async with self._scope_factory() as repositories:
                    cutoff = utc_now() - timedelta(
                        days=self._configuration.retention_days
                    )
                    await repositories.diagnostic_incidents.delete_last_seen_before(
                        cutoff
                    )
                    return await repositories.diagnostic_incidents.record(incident)
        except Exception:
            try:
                async with asyncio.timeout(
                    self._configuration.fallback_timeout_seconds
                ):
                    await self._write_fallback(incident)
            except Exception:
                logger.error(
                    "diagnostic_fallback_unavailable",
                    incident_id=str(incident.id),
                )
            logger.error(
                "diagnostic_database_unavailable",
                incident_id=str(incident.id),
                source=incident.source.value,
            )
            return incident

    async def _allow_frontend_report(self, user_id: UUID) -> bool:
        now = monotonic()
        async with self._rate_lock:
            reports = self._frontend_reports[user_id]
            while reports and reports[0] <= now - 60:
                reports.popleft()
            if len(reports) >= self._configuration.frontend_reports_per_minute:
                return False
            reports.append(now)
            return True

    async def _write_fallback(self, incident: DiagnosticIncident) -> None:
        async with self._fallback_lock:
            await asyncio.to_thread(
                _append_fallback,
                self._configuration.fallback_path,
                self._configuration.fallback_max_bytes,
                self._configuration.fallback_backups,
                incident,
            )


async def _require_product_admin(
    repositories: RepositoryProvider,
    principal: AuthenticatedPrincipal,
) -> None:
    user = await repositories.users.get_by_id(principal.user_id)
    if (
        principal.actor_type is not ActorType.USER
        or user is None
        or not user.enabled
        or user.product_role is not ProductRole.ADMIN
    ):
        raise DiagnosticAccessError("product_admin_required", 403)


def _safe_stack_frames(error: Exception) -> tuple[str, ...]:
    frames = traceback.extract_tb(error.__traceback__)[-20:]
    return tuple(
        f"{_safe_token(Path(frame.filename).name, fallback='module')}:{frame.lineno}:"
        f"{_safe_token(frame.name, fallback='call')}"
        for frame in frames
    )


def _safe_route(route: str) -> str:
    if not route or "?" in route or len(route) > 255:
        return "__unmatched__"
    return route


def _safe_token(value: str, *, fallback: str) -> str:
    normalized = _SAFE_TOKEN.sub("_", value.strip())[:64].strip("_")
    return normalized or fallback


def _bounded(value: str, *, fallback: str, maximum: int) -> str:
    normalized = value.strip()[:maximum]
    return normalized or fallback


def _fingerprint(*parts: str) -> str:
    return sha256("\x1f".join(parts).encode()).hexdigest()


def _append_fallback(
    path: Path,
    maximum_bytes: int,
    backups: int,
    incident: DiagnosticIncident,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (
        json.dumps(
            {
                "incident_id": str(incident.id),
                "fingerprint": incident.fingerprint,
                "source": incident.source.value,
                "severity": incident.severity.value,
                "code": incident.code,
                "component": incident.component,
                "action": incident.action,
                "route": incident.route,
                "method": incident.method,
                "status_code": incident.status_code,
                "tenant_id": str(incident.tenant_id) if incident.tenant_id else None,
                "user_id": str(incident.user_id) if incident.user_id else None,
                "error_type": incident.error_type,
                "environment": incident.environment,
                "release": incident.release,
                "request_id": incident.last_request_id,
                "stack_frames": incident.stack_frames,
                "occurred_at": incident.last_seen_at.isoformat(),
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    encoded_size = len(line.encode("utf-8"))
    if path.exists() and path.stat().st_size + encoded_size > maximum_bytes:
        for index in range(backups, 1, -1):
            older = path.with_suffix(f"{path.suffix}.{index - 1}")
            newer = path.with_suffix(f"{path.suffix}.{index}")
            if older.exists():
                older.replace(newer)
        path.replace(path.with_suffix(f"{path.suffix}.1"))
    with path.open("a", encoding="utf-8", newline="\n") as fallback:
        fallback.write(line)
