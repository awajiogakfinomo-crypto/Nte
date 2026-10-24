"""Authentication schemas."""
from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from enum import Enum


class UserRole(str, Enum):
    SUPER_ADMIN = "super_admin"
    USER = "user"


class UserStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING_VERIFICATION = "pending_verification"
    SUSPENDED = "suspended"


class MemberRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    DEVELOPER = "developer"
    VIEWER = "viewer"


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenData(BaseModel):
    sub: str
    org_id: Optional[str] = None
    role: str = "viewer"
    token_type: str = "access"
    jti: str


class UserBase(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=255)
    phone: Optional[str] = Field(None, max_length=20)


class UserCreate(UserBase):
    password: str = Field(..., min_length=8, max_length=128)
    organization_name: Optional[str] = Field(None, min_length=1, max_length=255)
    organization_slug: Optional[str] = Field(None, min_length=1, max_length=100)


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(None, min_length=1, max_length=255)
    phone: Optional[str] = Field(None, max_length=20)
    avatar_url: Optional[str] = Field(None, max_length=500)


class UserResponse(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: UserRole
    status: UserStatus
    email_verified: bool
    is_active: bool
    last_login_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class UserWithOrg(UserResponse):
    organization_id: Optional[UUID] = None
    organization_name: Optional[str] = None
    organization_role: Optional[MemberRole] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    remember_me: bool = False


class RegisterRequest(UserCreate):
    pass


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=128)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8, max_length=128)


class EmailVerificationRequest(BaseModel):
    email: EmailStr


class EmailVerificationConfirm(BaseModel):
    token: str


class GoogleAuthRequest(BaseModel):
    id_token: str