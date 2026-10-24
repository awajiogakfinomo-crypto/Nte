"""API Key model."""
import enum
import secrets
from datetime import datetime, UTC
from uuid import uuid4
from sqlalchemy import String, DateTime, Enum, Boolean, Text, ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class ApiKeyStatus(str, enum.Enum):
    """API Key status."""
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


class ApiKey(Base):
    """API Key for programmatic access."""
    __tablename__ = "api_keys"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # The actual key (prefix + random part)
    # Stored as: usk_live_xxxxx or usk_test_xxxxx
    key_prefix: Mapped[str] = mapped_column(String(20), nullable=False)  # e.g., "usk_live_"
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False, index=True)  # bcrypt hash
    key_last4: Mapped[str] = mapped_column(String(4), nullable=False)  # Last 4 chars for identification

    status: Mapped[ApiKeyStatus] = mapped_column(
        Enum(ApiKeyStatus, native_enum=False),
        default=ApiKeyStatus.ACTIVE,
        nullable=False,
    )

    # Rate limiting per key
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    rate_limit_per_day: Mapped[int] = mapped_column(Integer, default=10000, nullable=False)

    # Permissions/scopes
    scopes: Mapped[list[str]] = mapped_column(
        # JSON array of scopes: ["address:validate", "logistics:create", "kyc:verify"]
        default=list,
        nullable=False,
    )

    # Usage tracking
    total_requests: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="api_keys", lazy="selectin"
    )
    created_by_user: Mapped["User | None"] = relationship(
        "User", back_populates="api_keys", lazy="selectin"
    )

    @classmethod
    def generate_key(cls, is_live: bool = True) -> tuple[str, str, str]:
        """Generate a new API key.

        Returns:
            tuple: (full_key, key_prefix, key_last4)
        """
        prefix = "usk_live_" if is_live else "usk_test_"
        random_part = secrets.token_urlsafe(32)
        full_key = f"{prefix}{random_part}"
        key_hash = full_key  # Will be hashed before storage
        key_last4 = random_part[-4:]
        return full_key, prefix, key_last4

    def __repr__(self) -> str:
        return f"<ApiKey(id={self.id}, name={self.name}, prefix={self.key_prefix}***{self.key_last4})>"