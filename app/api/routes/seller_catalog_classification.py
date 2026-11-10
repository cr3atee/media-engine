from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies import (
    get_catalog_classification_service,
    require_tenant_permission,
)
from app.api.errors import ApiError
from app.api.schemas.catalog_classification import (
    CatalogHubResponse,
    CatalogSectionResponse,
    CatalogSourceCategoryResponse,
    CatalogSourceRuleResponse,
    CatalogTaxonomyResponse,
    CreateCatalogSourceRuleRequest,
    UpdateCatalogSourceRuleRequest,
)
from app.catalog.hierarchy import CatalogSourceRule
from app.catalog.taxonomy import MVP_CATALOG_HUBS
from app.domain.auth import Permission, TenantContext
from app.services.catalog_classification import (
    CatalogClassificationService,
    CatalogClassificationServiceError,
    CatalogSourceCategoryEvidence,
    CreateCatalogSourceRuleCommand,
    UpdateCatalogSourceRuleCommand,
)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/catalog/classification",
    tags=["Seller catalog classification"],
)

CatalogReviewTenant = Annotated[
    TenantContext,
    Depends(require_tenant_permission(Permission.CATALOG_REVIEW)),
]


@router.get("/taxonomy", response_model=CatalogTaxonomyResponse)
async def get_catalog_classification_taxonomy(
    context: CatalogReviewTenant,
) -> CatalogTaxonomyResponse:
    """Return the verified targets available to this guarded seller workflow."""
    del context
    return CatalogTaxonomyResponse(
        hubs=tuple(
            CatalogHubResponse(
                code=hub.code,
                name=hub.name,
                sections=tuple(
                    CatalogSectionResponse(
                        code=section.code,
                        name=section.name,
                        offer_type=section.offer_type,
                    )
                    for section in hub.sections
                ),
            )
            for hub in MVP_CATALOG_HUBS
        )
    )


@router.get(
    "/integrations/{integration_id}/source-categories",
    response_model=list[CatalogSourceCategoryResponse],
)
async def list_catalog_source_categories(
    integration_id: UUID,
    context: CatalogReviewTenant,
    service: Annotated[
        CatalogClassificationService,
        Depends(get_catalog_classification_service),
    ],
) -> list[CatalogSourceCategoryResponse]:
    """List exact integration evidence without inferring from offer titles."""
    try:
        evidence = await service.list_source_categories(
            context.tenant.id,
            integration_id,
        )
    except CatalogClassificationServiceError as exc:
        raise _api_error(exc) from exc
    return [_source_category_response(item) for item in evidence]


@router.get(
    "/integrations/{integration_id}/rules",
    response_model=list[CatalogSourceRuleResponse],
)
async def list_catalog_source_rules(
    integration_id: UUID,
    context: CatalogReviewTenant,
    service: Annotated[
        CatalogClassificationService,
        Depends(get_catalog_classification_service),
    ],
) -> list[CatalogSourceRuleResponse]:
    """List exact mappings owned by one tenant marketplace integration."""
    try:
        rules = await service.list_rules(context.tenant.id, integration_id)
    except CatalogClassificationServiceError as exc:
        raise _api_error(exc) from exc
    return [_rule_response(rule) for rule in rules]


@router.post(
    "/integrations/{integration_id}/rules",
    response_model=CatalogSourceRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_catalog_source_rule(
    integration_id: UUID,
    payload: CreateCatalogSourceRuleRequest,
    context: CatalogReviewTenant,
    service: Annotated[
        CatalogClassificationService,
        Depends(get_catalog_classification_service),
    ],
) -> CatalogSourceRuleResponse:
    """Persist one human-verified source-category mapping."""
    try:
        rule = await service.create_rule(
            CreateCatalogSourceRuleCommand(
                tenant_id=context.tenant.id,
                integration_id=integration_id,
                marketplace=payload.marketplace,
                source_category_id=payload.source_category_id,
                source_category_name=payload.source_category_name,
                hub_code=payload.hub_code,
                section_code=payload.section_code,
            )
        )
    except CatalogClassificationServiceError as exc:
        raise _api_error(exc) from exc
    return _rule_response(rule)


@router.post(
    "/integrations/{integration_id}/rules/update",
    response_model=CatalogSourceRuleResponse,
)
async def update_catalog_source_rule(
    integration_id: UUID,
    payload: UpdateCatalogSourceRuleRequest,
    context: CatalogReviewTenant,
    service: Annotated[
        CatalogClassificationService,
        Depends(get_catalog_classification_service),
    ],
) -> CatalogSourceRuleResponse:
    """Correct one mapping with optimistic concurrency protection."""
    try:
        rule = await service.update_rule(
            UpdateCatalogSourceRuleCommand(
                tenant_id=context.tenant.id,
                integration_id=integration_id,
                marketplace=payload.marketplace,
                source_category_id=payload.source_category_id,
                source_category_name=payload.source_category_name,
                hub_code=payload.hub_code,
                section_code=payload.section_code,
                expected_version=payload.expected_version,
            )
        )
    except CatalogClassificationServiceError as exc:
        raise _api_error(exc) from exc
    return _rule_response(rule)


def _rule_response(rule: CatalogSourceRule) -> CatalogSourceRuleResponse:
    return CatalogSourceRuleResponse(
        id=rule.id,
        tenant_id=rule.tenant_id,
        integration_id=rule.integration_id,
        marketplace=rule.marketplace,
        source_category_id=rule.source_category_id,
        source_category_name=rule.source_category_name,
        hub_code=rule.hub_code,
        section_code=rule.section_code,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
        version=rule.version,
    )


def _source_category_response(
    evidence: CatalogSourceCategoryEvidence,
) -> CatalogSourceCategoryResponse:
    return CatalogSourceCategoryResponse(
        marketplace=evidence.marketplace,
        source_category_id=evidence.source_category_id,
        source_category_name=evidence.source_category_name,
        offer_count=evidence.offer_count,
    )


def _api_error(error: CatalogClassificationServiceError) -> ApiError:
    return ApiError(
        error.status_code,
        error.code,
        error.message,
        details=error.details,
    )
