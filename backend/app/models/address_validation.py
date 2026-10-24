"""Address validation log model."""
import enum
from datetime import datetime, UTC
from uuid import uuid4
from sqlalchemy import String, DateTime, Enum, Boolean, Text, ForeignKey, Index, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class ValidationStatus(str, enum.Enum):
    """Address validation status."""
    VALID = "valid"
    INVALID = "invalid"
    PARTIAL = "partial"
    ERROR = "error"


class ValidationSource(str, enum.Enum):
    """Source of validation request."""
    API = "api"
    BULK_UPLOAD = "bulk_upload"
    DASHBOARD = "dashboard"
    WIDGET = "widget"


class AddressValidationLog(Base):
    """Log of address validation requests for analytics and debugging."""
    __tablename__ = "address_validation_logs"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    api_key_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Input
    raw_address: Mapped[str] = mapped_column(Text, nullable=False)
    raw_landmarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_latitude: Mapped[float | None] = mapped_column(nullable=True)
    input_longitude: Mapped[float | None] = mapped_column(nullable=True)

    # Result
    status: Mapped[ValidationStatus] = mapped_column(
        Enum(ValidationStatus, native_enum=False), nullable=False, index=True
    )
    postcode: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    postcode_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    formatted_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[float | None] = mapped_column(nullable=True)
    longitude: Mapped[float | None] = mapped_column(nullable=True)

    # NIPOST API response details
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lga: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ward: Mapped[str | None] = mapped_column(String(100), nullable=True)
    district: Mapped[str | None] = mapped_column(String(100), nullable=True)
    area: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Confidence and metadata
    confidence_score: Mapped[float | None] = mapped_column(nullable=True)
    match_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # exact, fuzzy, landmark
    suggestions: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)

    # Request metadata
    source: Mapped[ValidationSource] = mapped_column(
        Enum(ValidationSource, native_enum=False),
        default=ValidationSource.API,
        nullable=False,
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_time_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Error details (if any)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="address_validations", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_addr_val_org_created", "organization_id", "created_at"),
        Index("ix_addr_val_postcode", "postcode"),
        Index("ix_addr_val_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<AddressValidationLog(id={self.id}, postcode={self.postcode}, status={self.status})>"