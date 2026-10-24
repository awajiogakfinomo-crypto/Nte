"""Authentication routes: login, register, token refresh, password reset."""
from datetime import timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    revoke_token,
    verify_password,
)
from app.api.deps import get_current_user, get_current_user_optional
from app.models.user import User, UserRole, UserStatus
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    RefreshTokenRequest,
    Token,
    TokenData,
    UserResponse,
    UserWithOrg,
    PasswordChangeRequest,
    PasswordResetRequest,
    PasswordResetConfirm,
    EmailVerificationRequest,
    EmailVerificationConfirm,
    GoogleAuthRequest,
)

router = APIRouter()
logger = structlog.get_logger()
bearer_scheme = HTTPBearer(auto_error=False)


@router.post("/register", response_model=UserWithOrg, status_code=status.HTTP_201_CREATED)
async def register(
    request: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> UserWithOrg:
    """Register a new user and optionally create an organization."""
    # Check if email exists
    result = await db.execute(select(User).where(User.email == request.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Create user
    user = User(
        email=request.email,
        hashed_password=hash_password(request.password),
        full_name=request.full_name,
        phone=request.phone,
        status=UserStatus.PENDING_VERIFICATION,
    )
    db.add(user)
    await db.flush()

    # Create organization if provided
    org_id = None
    org_name = None
    if request.organization_name:
        from app.models.organization import Organization, OrganizationMember, MemberRole, OrganizationStatus, OrganizationPlan
        org = Organization(
            name=request.organization_name,
            slug=request.organization_slug or request.organization_name.lower().replace(" ", "-"),
            status=OrganizationStatus.TRIAL,
            plan=OrganizationPlan.FREE,
        )
        db.add(org)
        await db.flush()

        # Add user as owner
        member = OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role=MemberRole.OWNER,
        )
        db.add(member)
        org_id = org.id
        org_name = org.name

    await db.commit()
    await db.refresh(user)

    logger.info("user_registered", user_id=str(user.id), email=user.email)

    return UserWithOrg(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        phone=user.phone,
        role=user.role,
        status=user.status,
        email_verified=user.email_verified,
        is_active=user.is_active,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        updated_at=user.updated_at,
        organization_id=org_id,
        organization_name=org_name,
        organization_role="owner" if org_id else None,
    )


@router.post("/login", response_model=Token)
async def login(
    request: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> Token:
    """Login with email and password."""
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if not user.is_active or user.status != UserStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive or pending verification",
        )

    # Get user's default organization
    from app.models.organization import OrganizationMember, OrganizationStatus
    org_result = await db.execute(
        select(OrganizationMember.organization_id)
        .join(OrganizationMember.organization)
        .where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.organization.has(Organization.status == OrganizationStatus.ACTIVE)
        )
        .limit(1)
    )
    org_id = org_result.scalar_one_or_none()

    # Create tokens
    access_token, access_jti = create_access_token(
        subject=str(user.id),
        organization_id=str(org_id) if org_id else None,
        role=user.role.value,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES * (30 if request.remember_me else 1)),
    )
    refresh_token, refresh_jti = create_refresh_token(subject=str(user.id))

    # Store refresh token JTI in user record (or separate table)
    # For now, we'll use a simple approach

    # Update last login
    from datetime import datetime, UTC
    user.last_login_at = datetime.now(UTC)
    await db.commit()

    # Set secure cookies for refresh token
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    )

    logger.info("user_logged_in", user_id=str(user.id), email=user.email)

    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60 * (30 if request.remember_me else 1),
    )


@router.post("/refresh", response_model=Token)
async def refresh_token(
    request: RefreshTokenRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> Token:
    """Refresh access token using refresh token."""
    payload = decode_token(request.refresh_token)

    if not payload or payload.get("token_type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    # Check if refresh token is revoked
    jti = payload.get("jti")
    if jti:
        from app.core.cache import cache_manager
        if await cache_manager.is_token_revoked(jti):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
            )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    # Verify user exists and is active
    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()

    if not user or not user.is_active or user.status != UserStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    # Get organization
    from app.models.organization import OrganizationMember, OrganizationStatus
    org_result = await db.execute(
        select(OrganizationMember.organization_id)
        .join(OrganizationMember.organization)
        .where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.organization.has(Organization.status == OrganizationStatus.ACTIVE)
        )
        .limit(1)
    )
    org_id = org_result.scalar_one_or_none()

    # Revoke old refresh token
    if jti:
        await revoke_token(jti)

    # Create new tokens
    access_token, _ = create_access_token(
        subject=str(user.id),
        organization_id=str(org_id) if org_id else None,
        role=user.role.value,
    )
    new_refresh_token, _ = create_refresh_token(subject=str(user.id))

    # Set new refresh token cookie
    response.set_cookie(
        key="refresh_token",
        value=new_refresh_token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    )

    return Token(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Logout - revoke tokens and clear cookies."""
    # Revoke current access token
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
        payload = decode_token(token)
        if payload and payload.get("jti"):
            await revoke_token(payload["jti"])

    # Clear refresh token cookie
    response.delete_cookie(key="refresh_token")

    logger.info("user_logged_out", user_id=str(current_user.id))

    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserWithOrg)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserWithOrg:
    """Get current user info with organization context."""
    # Get organization
    from app.models.organization import OrganizationMember, MemberRole, OrganizationStatus
    org_result = await db.execute(
        select(OrganizationMember.organization_id, OrganizationMember.role, OrganizationMember.organization.has(Organization.name))
        .join(OrganizationMember.organization)
        .where(
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.organization.has(Organization.status == OrganizationStatus.ACTIVE)
        )
        .limit(1)
    )
    org_row = org_result.first()

    org_id = None
    org_name = None
    org_role = None
    if org_row:
        org_id = org_row[0]
        org_role = org_row[1].value if org_row[1] else None
        # Need to fetch org name separately
        from app.models.organization import Organization
        org_result2 = await db.execute(select(Organization.name).where(Organization.id == org_id))
        org_name = org_result2.scalar_one_or_none()

    return UserWithOrg(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        phone=current_user.phone,
        role=current_user.role,
        status=current_user.status,
        email_verified=current_user.email_verified,
        is_active=current_user.is_active,
        last_login_at=current_user.last_login_at,
        created_at=current_user.created_at,
        updated_at=current_user.updated_at,
        organization_id=org_id,
        organization_name=org_name,
        organization_role=org_role,
    )


@router.post("/change-password")
async def change_password(
    request: PasswordChangeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Change password for authenticated user."""
    if not verify_password(request.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    current_user.hashed_password = hash_password(request.new_password)
    await db.commit()

    logger.info("password_changed", user_id=str(current_user.id))

    return {"message": "Password changed successfully"}


@router.post("/forgot-password")
async def forgot_password(
    request: PasswordResetRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Request password reset email."""
    # Always return success to prevent email enumeration
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()

    if user:
        # Generate reset token (in production, send email)
        from app.core.security import generate_verification_token
        reset_token = generate_verification_token()
        # Store token in Redis with expiry
        from app.core.cache import cache_manager
        await cache_manager.set(f"password_reset:{request.email}", reset_token, ttl=3600)

        logger.info("password_reset_requested", user_id=str(user.id), email=user.email)
        # TODO: Send email with reset token

    return {"message": "If the email exists, a password reset link has been sent"}


@router.post("/reset-password")
async def reset_password(
    request: PasswordResetConfirm,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Confirm password reset with token."""
    from app.core.cache import cache_manager

    # Verify token
    stored_token = await cache_manager.get(f"password_reset:{request.token}")
    # In production, token would be in the email link, not the request body
    # This is simplified - token should be in URL, email in body

    # For now, just verify token exists
    if not stored_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    # Find user by email (would come from token in production)
    # Simplified for demo
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Password reset flow needs email integration",
    )


@router.post("/verify-email")
async def verify_email(
    request: EmailVerificationRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Request email verification."""
    # Always return success
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()

    if user and not user.email_verified:
        from app.core.security import generate_verification_token
        verify_token = generate_verification_token()
        from app.core.cache import cache_manager
        await cache_manager.set(f"email_verify:{request.email}", verify_token, ttl=86400)

        logger.info("email_verification_requested", user_id=str(user.id), email=user.email)
        # TODO: Send verification email

    return {"message": "If the email exists, a verification link has been sent"}


@router.post("/verify-email/confirm")
async def verify_email_confirm(
    request: EmailVerificationConfirm,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Confirm email verification."""
    from app.core.cache import cache_manager

    # In production, token would be in URL, email in query param
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Email verification flow needs email integration",
    )


@router.post("/google")
async def google_auth(
    request: GoogleAuthRequest,
    db: AsyncSession = Depends(get_db),
) -> Token:
    """Authenticate with Google OAuth."""
    # TODO: Verify Google ID token, create/get user, return tokens
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Google OAuth not yet implemented",
    )