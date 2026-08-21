from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import SecretStr

from app.config.settings import AuthSettings
from app.domain.auth import PasswordCredential, Permission
from app.domain.tenancy import Membership, Tenant, TenantRole, User
from app.services.auth_tokens import SignedAccessTokenService
from app.services.authentication import AuthenticationError, AuthenticationService
from app.services.authorization import AuthorizationError, AuthorizationService
from app.services.passwords import PasswordHasher
from app.services.repository_scope import (
    RepositoryScopeFactory,
    create_memory_repository_scope,
)
from tests.repositories.contracts.factories import run_async

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
USER_ID = UUID("10000000-0000-4000-8000-000000000001")
TENANT_ID = UUID("20000000-0000-4000-8000-000000000001")
MEMBERSHIP_ID = UUID("30000000-0000-4000-8000-000000000001")
PASSWORD = "correct horse battery staple"


def test_login_refresh_logout_and_access_revocation() -> None:
    service, authorization, _ = run_async(_seeded_services(role=TenantRole.VIEWER))

    tokens = run_async(service.login(email="SELLER@example.com", password=PASSWORD))
    principal = run_async(service.authenticate_access_token(tokens.access_token))
    profile = run_async(authorization.get_profile(principal))
    refreshed = run_async(service.refresh(refresh_token=tokens.refresh_token))

    assert tokens.token_type == "bearer"
    assert principal.user_id == USER_ID
    assert profile.user.email == "seller@example.com"
    assert len(profile.memberships) == 1
    assert refreshed.refresh_token != tokens.refresh_token

    with pytest.raises(AuthenticationError) as old_refresh:
        run_async(service.refresh(refresh_token=tokens.refresh_token))
    assert old_refresh.value.code == "token_revoked"

    run_async(service.logout(refresh_token=refreshed.refresh_token))
    with pytest.raises(AuthenticationError) as revoked_access:
        run_async(service.authenticate_access_token(refreshed.access_token))
    assert revoked_access.value.code == "token_revoked"


def test_password_reset_rotates_credentials_and_revokes_sessions() -> None:
    service, _, _ = run_async(_seeded_services(role=TenantRole.VIEWER))
    tokens = run_async(service.login(email="seller@example.com", password=PASSWORD))
    reset = run_async(service.request_password_reset(email="seller@example.com"))

    assert reset.accepted is True
    assert reset.reset_token is not None
    run_async(
        service.complete_password_reset(
            reset_token=reset.reset_token,
            new_password="new correct horse battery staple",
        )
    )

    with pytest.raises(AuthenticationError):
        run_async(service.authenticate_access_token(tokens.access_token))
    with pytest.raises(AuthenticationError):
        run_async(service.login(email="seller@example.com", password=PASSWORD))

    new_tokens = run_async(
        service.login(
            email="seller@example.com",
            password="new correct horse battery staple",
        )
    )
    assert new_tokens.access_token


def test_authorization_reflects_role_and_membership_changes() -> None:
    service, authorization, scope_factory = run_async(
        _seeded_services(role=TenantRole.VIEWER)
    )
    tokens = run_async(service.login(email="seller@example.com", password=PASSWORD))
    principal = run_async(service.authenticate_access_token(tokens.access_token))

    with pytest.raises(AuthorizationError) as denied:
        run_async(
            authorization.require_tenant_context(
                principal,
                TENANT_ID,
                Permission.CONTENT_REVIEW,
            )
        )
    assert denied.value.code == "permission_denied"

    async def promote() -> None:
        async with scope_factory() as repositories:
            membership = await repositories.memberships.get_by_user_and_tenant(
                USER_ID,
                TENANT_ID,
            )
            assert membership is not None
            await repositories.memberships.update_role(
                USER_ID,
                TENANT_ID,
                TenantRole.REVIEWER,
                membership.version,
            )

    run_async(promote())
    context = run_async(
        authorization.require_tenant_context(
            principal,
            TENANT_ID,
            Permission.CONTENT_REVIEW,
        )
    )
    assert context.membership.role is TenantRole.REVIEWER

    async def deactivate() -> None:
        async with scope_factory() as repositories:
            membership = await repositories.memberships.get_by_user_and_tenant(
                USER_ID,
                TENANT_ID,
            )
            assert membership is not None
            await repositories.memberships.set_active(
                USER_ID,
                TENANT_ID,
                False,
                membership.version,
            )

    run_async(deactivate())
    with pytest.raises(AuthorizationError) as hidden:
        run_async(
            authorization.require_tenant_context(
                principal,
                TENANT_ID,
                Permission.DASHBOARD_READ,
            )
        )
    assert hidden.value.code == "tenant_not_found"


async def _seeded_services(
    *,
    role: TenantRole,
) -> tuple[AuthenticationService, AuthorizationService, RepositoryScopeFactory]:
    from app.repositories.provider import create_memory_provider

    provider = create_memory_provider()
    scope_factory = create_memory_repository_scope(provider)
    hasher = PasswordHasher(iterations=100_000)
    async with scope_factory() as repositories:
        await repositories.users.create(
            User(
                id=USER_ID,
                email="seller@example.com",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await repositories.tenants.create(
            Tenant(
                id=TENANT_ID,
                name="Seller Workspace",
                slug="seller-workspace",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await repositories.memberships.create(
            Membership(
                id=MEMBERSHIP_ID,
                user_id=USER_ID,
                tenant_id=TENANT_ID,
                role=role,
                joined_at=NOW,
                updated_at=NOW,
            )
        )
        await repositories.password_credentials.set_for_user(
            PasswordCredential(
                user_id=USER_ID,
                password_hash=hasher.hash_password(PASSWORD),
                created_at=NOW,
                updated_at=NOW,
            )
        )

    auth_settings = AuthSettings(access_token_secret=SecretStr("test-secret"))
    token_service = SignedAccessTokenService(
        secret=auth_settings.access_token_secret.get_secret_value(),
        ttl_seconds=auth_settings.access_token_ttl_seconds,
        issuer=auth_settings.token_issuer,
        audience=auth_settings.token_audience,
    )
    authentication = AuthenticationService(
        scope_factory,
        token_service,
        hasher,
        access_token_ttl_seconds=auth_settings.access_token_ttl_seconds,
        refresh_token_ttl_seconds=auth_settings.refresh_token_ttl_seconds,
        password_reset_token_ttl_seconds=(
            auth_settings.password_reset_token_ttl_seconds
        ),
        clock=lambda: NOW,
    )
    return authentication, AuthorizationService(scope_factory), scope_factory
