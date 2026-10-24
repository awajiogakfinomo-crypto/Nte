"""Usage tracking and analytics models."""
import enum
from datetime import datetime, UTC
from uuid import uuid4
from sqlalchemy import String, DateTime, Enum, ForeignKey, Index, Integer, BigInteger, JSON, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class UsageType(str, enum.Enum):
    """Type of usage event."""
    ADDRESS_VALIDATE = "address_validate"
    ADDRESS_AUTOCOMPLETE = "address_autocomplete"
    REVERSE_GEOCODE = "reverse_geocode"
    POSTCODE_LOOKUP = "postcode_lookup"
    BULK_VALIDATE = "bulk_validate"
    DELIVERY_CREATE = "delivery_create"
    DELIVERY_VALIDATE = "delivery_validate"
    VERIFICATION_REQUEST = "verification_request"
    VERIFICATION_CHECK = "verification_check"
    API_KEY_CREATE = "api_key_create"


class UsageRecord(Base):
    """Usage record for billing and analytics."""
    __tablename__ = "usage_records"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    api_key_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)

    usage_type: Mapped[UsageType] = mapped_column(
        Enum(UsageType, native_enum=False), nullable=False, index=True
    )

    # Request details
    endpoint: Mapped[str] = mapped_column(String(200), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)

    # Count and volume
    request_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    items_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # For bulk operations

    # Performance
    response_time_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Cost tracking (in kobo for NGN precision)
    cost_kobo: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # Metadata
    metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Time bucketing for aggregation
    date_bucket: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    hour_bucket: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-23

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="usage_records", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_usage_org_date", "organization_id", "date_bucket"),
        Index("ix_usage_org_type_date", "organization_id", "usage_type", "date_bucket"),
        Index("ix_usage_api_key_date", "api_key_id", "date_bucket"),
    )

    def __repr__(self) -> str:
        return f"<UsageRecord(org_id={self.organization_id}, type={self.usage_type}, count={self.request_count})>"