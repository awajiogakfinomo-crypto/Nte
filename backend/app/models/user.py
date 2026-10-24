"""User model."""
import enum
from datetime import datetime, UTC
from uuid import uuid4
from sqlalchemy import String, DateTime, Enum, Boolean, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class UserRole(str, enum.Enum):
    """Global user roles (not org-specific)."""
    SUPER_ADMIN = "super_admin"
    USER = "user"


class UserStatus(str, enum.Enum):
    """User account status."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING_VERIFICATION = "pending_verification"
    SUSPENDED = "suspended"


class User(Base):
    """User account model."""
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False),
        default=UserRole.USER,
        nullable=False,
    )
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, native_enum=False),
        default=UserStatus.PENDING_VERIFICATION,
        nullable=False,
    )

    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    organization_memberships: Mapped[list["OrganizationMember"]] = relationship(
        "OrganizationMember", back_populates="user", lazy="selectin"
    )
    api_keys: Mapped[list["ApiKey"]] = relationship(
        "ApiKey", back_populates="created_by_user", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email}, role={self.role})>"