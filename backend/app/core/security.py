"""Security utilities: JWT tokens, API keys, password hashing."""
from datetime import datetime, timedelta, UTC
from typing import Optional, Dict, Any
from uuid import uuid4
import secrets

from jose import jwt, JWTError
from passlib.context import CryptContext
import structlog

from app.core.config import settings
from app.core.cache import cache_manager
from app.core.database import get_db_context
from app.models.api_key import ApiKey, ApiKeyStatus
from sqlalchemy import select

logger = structlog.get_logger()

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# =============================================================================
# Password Hashing
# =============================================================================

def hash_password(password: str) -> str:
    """Hash a password."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


# =============================================================================
# JWT Tokens
# =============================================================================

def create_access_token(
    subject: str,
    organization_id: Optional[str] = None,
    role: str = "viewer",
    expires_delta: Optional[timedelta] = None,
) -> tuple[str, str]:
    """Create JWT access token. Returns (token, jti)."""
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    jti = str(uuid4())
    to_encode = {
        "sub": subject,
        "org_id": organization_id,
        "role": role,
        "token_type": "access",
        "jti": jti,
        "exp": expire,
        "iat": datetime.now(UTC),
    }
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt, jti


def create_refresh_token(
    subject: str,
    expires_delta: Optional[timedelta] = None,
) -> tuple[str, str]:
    """Create JWT refresh token. Returns (token, jti)."""
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    jti = str(uuid4())
    to_encode = {
        "sub": subject,
        "token_type": "refresh",
        "jti": jti,
        "exp": expire,
        "iat": datetime.now(UTC),
    }
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt, jti


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and validate JWT token."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError as e:
        logger.debug("jwt_decode_failed", error=str(e))
        return None


async def revoke_token(jti: str, ttl: int = 604800) -> bool:
    """Revoke a token by adding its JTI to the blocklist."""
    return await cache_manager.revoke_token(jti, ttl)


# =============================================================================
# API Key Management
# =============================================================================

def hash_api_key(api_key: str) -> str:
    """Hash an API key for storage."""
    return pwd_context.hash(api_key)


def verify_api_key_hash(api_key: str, key_hash: str) -> bool:
    """Verify an API key against its hash."""
    return pwd_context.verify(api_key, key_hash)


async def verify_api_key(db_session, api_key_str: str) -> Optional[ApiKey]:
    """Verify API key and return ApiKey object if valid."""
    # Extract prefix to find candidate keys
    if not api_key_str.startswith(("usk_live_", "usk_test_")):
        return None

    prefix_end = api_key_str.find("_", 4) + 1  # After "usk_live_" or "usk_test_"
    prefix = api_key_str[:prefix_end]

    # Find keys with matching prefix
    result = await db_session.execute(
        select(ApiKey).where(
            ApiKey.key_prefix == prefix,
            ApiKey.status == ApiKeyStatus.ACTIVE,
        )
    )
    candidates = result.scalars().all()

    for candidate in candidates:
        if verify_api_key_hash(api_key_str, candidate.key_hash):
            # Check expiry
            if candidate.expires_at and candidate.expires_at < datetime.now(UTC):
                return None
            return candidate

    return None


async def record_api_key_usage(db_session, api_key: ApiKey) -> None:
    """Record API key usage (increment counter, update last_used_at)."""
    api_key.total_requests += 1
    api_key.last_used_at = datetime.now(UTC)
    await db_session.commit()


# =============================================================================
# Token Generation Utilities
# =============================================================================

def generate_verification_token() -> str:
    """Generate a secure token for email verification, password reset, etc."""
    return secrets.token_urlsafe(32)


def generate_api_key(is_live: bool = True) -> tuple[str, str, str]:
    """Generate a new API key.

    Returns:
        tuple: (full_key, key_prefix, key_last4)
    """
    prefix = "usk_live_" if is_live else "usk_test_"
    random_part = secrets.token_urlsafe(32)
    full_key = f"{prefix}{random_part}"
    key_last4 = random_part[-4:]
    return full_key, prefix, key_last4