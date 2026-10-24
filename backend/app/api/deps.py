"""FastAPI dependencies for database, cache, authentication, and authorization."""
from typing import AsyncGenerator, Optional
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.cache import cache_manager
from app.core.config import settings
from app.core.database import async_session_maker
from app.core.security import decode_token, verify_api_key
from app.models.api_key import ApiKey
from app.models.user import User

logger = structlog.get_logger()

# Security schemes
bearer_scheme = HTTPBearer(auto_error=False)
api_key_scheme = HTTPBearer(auto_error=False)


# =============================================================================
# Database
# =============================================================================

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session."""
    async with async_session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# =============================================================================
# Cache
# =============================================================================

async def get_cache() -> "CacheManager":
    """Get cache manager instance."""
    return cache_manager


# =============================================================================
# Authentication - JWT Token
# =============================================================================

async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Get current authenticated user from JWT token."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    payload = decode_token(token)

    if not payload or payload.get("token_type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check token blocklist in Redis
    jti = payload.get("jti")
    if jti and await cache_manager.is_token_revoked(jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    from sqlalchemy import select
    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if not user.is_active or user.status.value != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive or suspended",
        )

    # Attach user to request state for logging/metrics
    request.state.user_id = str(user.id)
    request.state.user_email = user.email

    return user


async def get_current_user_optional(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Get current user if authenticated, otherwise None."""
    try:
        return await get_current_user(request, credentials, db)
    except HTTPException:
        return None


# =============================================================================
# Authentication - API Key
# =============================================================================

async def get_api_key(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(api_key_scheme),
    db: AsyncSession = Depends(get_db),
) -> ApiKey:
    """Validate API key from Authorization header."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    api_key_str = credentials.credentials
    api_key = await verify_api_key(db, api_key_str)

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check rate limits
    from app.services.rate_limit import check_rate_limit
    allowed, retry_after = await check_rate_limit(api_key)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )

    # Attach to request state
    request.state.api_key_id = str(api_key.id)
    request.state.organization_id = str(api_key.organization_id)

    return api_key


async def get_api_key_optional(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(api_key_scheme),
    db: AsyncSession = Depends(get_db),
) -> Optional[ApiKey]:
    """Get API key if provided, otherwise None."""
    try:
        return await get_api_key(request, credentials, db)
    except HTTPException:
        return None


# =============================================================================
# Organization Context
# =============================================================================

async def get_organization_id(
    request: Request,
    api_key: Optional[ApiKey] = Depends(get_api_key_optional),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> UUID:
    """Get organization ID from API key or user's default org."""
    if api_key:
        return api_key.organization_id

    if current_user:
        # Get user's first active organization membership
        from app.models.organization import OrganizationMember, OrganizationStatus
        from sqlalchemy import select
        result = await db.execute(
            select(OrganizationMember.organization_id)
            .join(OrganizationMember.organization)
            .where(
                OrganizationMember.user_id == current_user.id,
                OrganizationMember.organization.has(Organization.status == OrganizationStatus.ACTIVE)
            )
            .limit(1)
        )
        org_id = result.scalar_one_or_none()
        if org_id:
            return org_id

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="No organization context. Provide API key or authenticate as organization member.",
    )


# =============================================================================
# Request Context
# =============================================================================

def get_request_id(request: Request) -> str:
    """Get or generate request ID for tracing."""
    request_id = request.headers.get("X-Request-ID")
    if not request_id:
        import uuid
        request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    return request_id


def get_client_ip(request: Request) -> str:
    """Get client IP address."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# =============================================================================
# Pagination
# =============================================================================

from pydantic import BaseModel, Field

class PaginationParams(BaseModel):
    """Pagination parameters."""
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


def get_pagination(
    page: int = 1,
    page_size: int = 20,
) -> PaginationParams:
    """Get pagination parameters."""
    return PaginationParams(page=page, page_size=page_size)