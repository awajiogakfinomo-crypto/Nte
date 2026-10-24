"""API Key schemas."""
from typing import Optional, List
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict
from enum import Enum


class ApiKeyStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


# -------------------------------------------------------------------------
# API Key Schemas
# -------------------------------------------------------------------------

class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    is_live: bool = True
    expires_in_days: Optional[int] = Field(None, ge=1, le=3650)
    rate_limit_per_minute: Optional[int] = Field(None, ge=1, le=10000)
    rate_limit_per_day: Optional[int] = Field(None, ge=1, le=1000000)
    scopes: Optional[List[str]] = Field(
        default=["address:validate"],
        description="Allowed scopes: address:validate, address:autocomplete, address:reverse, address:postcode, address:bulk, logistics:create, logistics:read, kyc:create, kyc:read"
    )


class ApiKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: Optional[str] = None
    key_prefix: str
    key_last4: str
    status: ApiKeyStatus
    rate_limit_per_minute: int
    rate_limit_per_day: int
    scopes: List[str]
    total_requests: int
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    created_at: datetime


class ApiKeyDetail(ApiKeyResponse):
    revoked_at: Optional[datetime] = None
    updated_at: datetime


class ApiKeyWithSecret(ApiKeyResponse):
    full_key: str


class ApiKeyListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[ApiKeyResponse]