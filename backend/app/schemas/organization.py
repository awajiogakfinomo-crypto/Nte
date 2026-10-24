"""Organization schemas."""
from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict, HttpUrl
from enum import Enum


class OrganizationStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    TRIAL = "trial"


class OrganizationPlan(str, Enum):
    FREE = "free"
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


class MemberRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    DEVELOPER = "developer"
    VIEWER = "viewer"


class OrganizationBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    description: Optional[str] = None
    website: Optional[HttpUrl] = None


class OrganizationCreate(OrganizationBase):
    pass


class OrganizationUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    website: Optional[HttpUrl] = None
    logo_url: Optional[HttpUrl] = None
    default_postcode_level: Optional[str] = Field(None, max_length=20)
    webhook_url: Optional[HttpUrl] = None


class OrganizationResponse(OrganizationBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: OrganizationStatus
    plan: OrganizationPlan
    monthly_api_limit: int
    monthly_validations_used: int
    api_limit_reset_at: datetime
    logo_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class OrganizationWithStats(OrganizationResponse):
    member_count: int = 0
    api_key_count: int = 0
    validations_this_month: int = 0


class OrganizationMemberBase(BaseModel):
    user_id: UUID
    role: MemberRole = MemberRole.VIEWER


class OrganizationMemberCreate(OrganizationMemberBase):
    pass


class OrganizationMemberUpdate(BaseModel):
    role: MemberRole


class OrganizationMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    user_id: UUID
    role: MemberRole
    joined_at: datetime
    user_email: Optional[str] = None
    user_full_name: Optional[str] = None
    user_avatar_url: Optional[str] = None


class InviteMemberRequest(BaseModel):
    email: str = Field(..., pattern=r"^[^@]+@[^@]+\.[^@]+$")
    role: MemberRole = MemberRole.VIEWER


class AcceptInviteRequest(BaseModel):
    token: str