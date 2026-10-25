"""Product role administration uses a user bearer token, not a workspace role."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query

from app.api.dependencies import get_product_role_service, require_seller_principal
from app.api.errors import ApiError
from app.api.schemas.product_roles import (
    ProductRoleActionResponse,
    ProductRoleRequest,
    ProductRoleResponse,
)
from app.domain.auth import AuthenticatedPrincipal
from app.services.product_roles import ProductRoleError, ProductRoleService

router = APIRouter(prefix="/api/v1/platform/users", tags=["product-access"])


def _error(error: ProductRoleError) -> ApiError:
    messages = {
        "product_admin_required": "Product administrator permission is required.",
        "role_target_unavailable": "Role target is unavailable.",
        "version_conflict": "User version has changed.",
        "idempotency_conflict": "Idempotency key is already bound to another command.",
        "last_product_admin": "The last active product admin cannot be removed.",
        "product_role_unchanged": "The requested role is already assigned.",
        "invalid_role_command": "Role command is invalid.",
    }
    return ApiError(
        error.status,
        error.code,
        messages.get(error.code, "Role command could not be completed."),
    )


@router.get("/{user_id}/role", response_model=ProductRoleResponse)
async def get_role(
    user_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_seller_principal)],
    service: Annotated[ProductRoleService, Depends(get_product_role_service)],
) -> ProductRoleResponse:
    """Read the target version without granting access to their workspaces."""
    try:
        user = await service.get_user(principal, user_id)
    except ProductRoleError as exc:
        raise _error(exc) from exc
    return ProductRoleResponse.model_validate(user, from_attributes=True)


@router.post("/{user_id}/role", response_model=ProductRoleActionResponse)
async def set_role(
    user_id: UUID,
    command: ProductRoleRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_seller_principal)],
    service: Annotated[ProductRoleService, Depends(get_product_role_service)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=1, max_length=128)
    ],
) -> ProductRoleActionResponse:
    """Atomically authorize, mutate and audit a guarded role assignment."""
    try:
        action = await service.assign(
            principal,
            user_id=user_id,
            role=command.role,
            expected_version=command.expected_version,
            reason=command.reason,
            idempotency_key=idempotency_key,
        )
    except ProductRoleError as exc:
        raise _error(exc) from exc
    return ProductRoleActionResponse.model_validate(action, from_attributes=True)


@router.get("/{user_id}/role-audit", response_model=list[ProductRoleActionResponse])
async def role_audit(
    user_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_seller_principal)],
    service: Annotated[ProductRoleService, Depends(get_product_role_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> list[ProductRoleActionResponse]:
    """Inspect bounded immutable role history with current product-admin access."""
    try:
        actions = await service.audit(principal, user_id, limit)
    except ProductRoleError as exc:
        raise _error(exc) from exc
    return [
        ProductRoleActionResponse.model_validate(action, from_attributes=True)
        for action in actions
    ]
