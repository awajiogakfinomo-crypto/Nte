"""Organization and membership models."""
import enum
from datetime import datetime, UTC
from uuid import uuid4
from sqlalchemy import String, DateTime, Enum, Boolean, Text, ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class OrganizationStatus(str, enum.Enum):
    """Organization account status."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    TRIAL = "trial"


class OrganizationPlan(str, enum.Enum):
    """Organization subscription plan."""
    FREE = "free"
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


class MemberRole(str, enum.Enum):
    """Organization member roles."""
    OWNER = "owner"
    ADMIN = "admin"
    DEVELOPER = "developer"
    VIEWER = "viewer"


class Organization(Base):
    """Organization/Company model."""
    __tablename__ = "organizations"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)

    status: Mapped[OrganizationStatus] = mapped_column(
        Enum(OrganizationStatus, native_enum=False),
        default=OrganizationStatus.TRIAL,
        nullable=False,
    )
    plan: Mapped[OrganizationPlan] = mapped_column(
        Enum(OrganizationPlan, native_enum=False),
        default=OrganizationPlan.FREE,
        nullable=False,
    )

    # Billing/usage limits
    monthly_api_limit: Mapped[int] = mapped_column(Integer, default=10000, nullable=False)
    monthly_validations_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    api_limit_reset_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    # Settings
    default_postcode_level: Mapped[str] = mapped_column(String(20), default="building", nullable=False)
    webhook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    webhook_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)

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
    members: Mapped[list["OrganizationMember"]] = relationship(
        "OrganizationMember", back_populates="organization", lazy="selectin"
    )
    api_keys: Mapped[list["ApiKey"]] = relationship(
        "ApiKey", back_populates="organization", lazy="selectin"
    )
    address_validations: Mapped[list["AddressValidationLog"]] = relationship(
        "AddressValidationLog", back_populates="organization", lazy="selectin"
    )
    delivery_jobs: Mapped[list["DeliveryJob"]] = relationship(
        "DeliveryJob", back_populates="organization", lazy="selectin"
    )
    verification_requests: Mapped[list["VerificationRequest"]] = relationship(
        "VerificationRequest", back_populates="organization", lazy="selectin"
    )
    usage_records: Mapped[list["UsageRecord"]] = relationship(
        "UsageRecord", back_populates="organization", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Organization(id={self.id}, name={self.name}, slug={self.slug})>"


class OrganizationMember(Base):
    """Organization membership model."""
    __tablename__ = "organization_members"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[MemberRole] = mapped_column(
        Enum(MemberRole, native_enum=False),
        default=MemberRole.VIEWER,
        nullable=False,
    )
    invited_by_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="members", lazy="selectin"
    )
    user: Mapped["User"] = relationship(
        "User", back_populates="organization_memberships", lazy="selectin"
    )
    invited_by: Mapped["User | None"] = relationship(
        "User", foreign_keys=[invited_by_id], lazy="selectin"
    )

    # Unique constraint: one membership per user per organization
    __table_args__ = (
        Index("ix_org_member_org_user", "organization_id", "user_id", unique=True),
    )

    def __repr__(self) -> str:
        return f"<OrganizationMember(org_id={self.organization_id}, user_id={self.user_id}, role={self.role})>"