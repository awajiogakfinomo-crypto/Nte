"""API Key management routes."""
from typing import Optional, List
from uuid import UUID
from datetime import datetime, timedelta, UTC

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.api.deps import (
    get_api_key,
    get_current_user,
    get_db,
    get_organization_id,
    get_pagination,
)
from app.core.security import generate_api_key, hash_api_key
from app.models.api_key import ApiKey, ApiKeyStatus
from app.models.organization import OrganizationMember, MemberRole
from app.schemas.api_key import (
    ApiKeyCreate,
    ApiKeyResponse,
    ApiKeyDetail,
    ApiKeyListResponse,
    ApiKeyWithSecret,
)

router = APIRouter()
logger = structlog.get_logger()


@router.post("", response_model=ApiKeyWithSecret, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    request: ApiKeyCreate,
    current_user = Depends(get_current_user),
    organization_id: UUID = Depends(get_organization_id),
    db: AsyncSession = Depends(get_db),
):
    """Create a new API key for the organization."""
    # Verify user has permission (owner or admin)
    member_result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.role.in_([MemberRole.OWNER, MemberRole.ADMIN])
        )
    )
    if not member_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    # Generate key
    full_key, prefix, last4 = generate_api_key(is_live=request.is_live)
    key_hash = hash_api_key(full_key)

    # Calculate expiry
    expires_at = None
    if request.expires_in_days:
        expires_at = datetime.now(UTC) + timedelta(days=request.expires_in_days)

    api_key = ApiKey(
        organization_id=organization_id,
        created_by_id=current_user.id,
        name=request.name,
        description=request.description,
        key_prefix=prefix,
        key_hash=key_hash,
        key_last4=last4,
        rate_limit_per_minute=request.rate_limit_per_minute or 60,
        rate_limit_per_day=request.rate_limit_per_day or 10000,
        scopes=request.scopes or ["address:validate"],
        expires_at=expires_at,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    logger.info("api_key_created", key_id=str(api_key.id), org_id=str(organization_id))

    return ApiKeyWithSecret(
        id=api_key.id,
        name=api_key.name,
        description=api_key.description,
        key_prefix=api_key.key_prefix,
        key_last4=api_key.key_last4,
        status=api_key.status,
        rate_limit_per_minute=api_key.rate_limit_per_minute,
        rate_limit_per_day=api_key.rate_limit_per_day,
        scopes=api_key.scopes,
        expires_at=api_key.expires_at,
        created_at=api_key.created_at,
        full_key=full_key,  # Only returned once!
    )


@router.get("", response_model=ApiKeyListResponse)
async def list_api_keys(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: Optional[ApiKeyStatus] = Query(None),
    current_user = Depends(get_current_user),
    organization_id: UUID = Depends(get_organization_id),
    db: AsyncSession = Depends(get_db),
):
    """List API keys for the organization."""
    query = select(ApiKey).where(ApiKey.organization_id == organization_id)

    if status_filter:
        query = query.where(ApiKey.status == status_filter)

    query = query.order_by(ApiKey.created_at.desc())

    # Count
    from sqlalchemy import func
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)

    # Paginate
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    result = await db.execute(query)
    keys = result.scalars().all()

    return ApiKeyListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[
            ApiKeyResponse(
                id=k.id,
                name=k.name,
                description=k.description,
                key_prefix=k.key_prefix,
                key_last4=k.key_last4,
                status=k.status,
                rate_limit_per_minute=k.rate_limit_per_minute,
                rate_limit_per_day=k.rate_limit_per_day,
                scopes=k.scopes,
                total_requests=k.total_requests,
                last_used_at=k.last_used_at,
                expires_at=k.expires_at,
                created_at=k.created_at,
            )
            for k in keys
        ],
    )


@router.get("/{key_id}", response_model=ApiKeyDetail)
async def get_api_key(
    key_id: UUID,
    current_user = Depends(get_current_user),
    organization_id: UUID = Depends(get_organization_id),
    db: AsyncSession = Depends(get_db),
):
    """Get API key details (without secret)."""
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.id == key_id,
            ApiKey.organization_id == organization_id
        )
    )
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")

    return ApiKeyDetail(
        id=api_key.id,
        name=api_key.name,
        description=api_key.description,
        key_prefix=api_key.key_prefix,
        key_last4=api_key.key_last4,
        status=api_key.status,
        rate_limit_per_minute=api_key.rate_limit_per_minute,
        rate_limit_per_day=api_key.rate_limit_per_day,
        scopes=api_key.scopes,
        total_requests=api_key.total_requests,
        last_used_at=api_key.last_used_at,
        expires_at=api_key.expires_at,
        revoked_at=api_key.revoked_at,
        created_at=api_key.created_at,
        updated_at=api_key.updated_at,
    )


@router.patch("/{key_id}/revoke")
async def revoke_api_key(
    key_id: UUID,
    current_user = Depends(get_current_user),
    organization_id: UUID = Depends(get_organization_id),
    db: AsyncSession = Depends(get_db),
):
    """Revoke an API key."""
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.id == key_id,
            ApiKey.organization_id == organization_id
        )
    )
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")

    api_key.status = ApiKeyStatus.REVOKED
    api_key.revoked_at = datetime.now(UTC)
    await db.commit()

    logger.info("api_key_revoked", key_id=str(key_id), org_id=str(organization_id))

    return {"message": "API key revoked"}


@router.patch("/{key_id}/rotate")
async def rotate_api_key(
    key_id: UUID,
    current_user = Depends(get_current_user),
    organization_id: UUID = Depends(get_organization_id),
    db: AsyncSession = Depends(get_db),
):
    """Rotate an API key (generate new secret, keep same ID)."""
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.id == key_id,
            ApiKey.organization_id == organization_id
        )
    )
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")

    # Generate new key
    full_key, prefix, last4 = generate_api_key(is_live=api_key.key_prefix.startswith("usk_live"))
    api_key.key_prefix = prefix
    api_key.key_hash = hash_api_key(full_key)
    api_key.key_last4 = last4
    api_key.updated_at = datetime.now(UTC)
    await db.commit()

    logger.info("api_key_rotated", key_id=str(key_id), org_id=str(organization_id))

    return ApiKeyWithSecret(
        id=api_key.id,
        name=api_key.name,
        description=api_key.description,
        key_prefix=api_key.key_prefix,
        key_last4=api_key.key_last4,
        status=api_key.status,
        rate_limit_per_minute=api_key.rate_limit_per_minute,
        rate_limit_per_day=api_key.rate_limit_per_day,
        scopes=api_key.scopes,
        expires_at=api_key.expires_at,
        created_at=api_key.created_at,
        full_key=full_key,
    )