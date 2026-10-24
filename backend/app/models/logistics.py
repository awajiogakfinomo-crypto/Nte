"""Logistics and delivery models."""
import enum
from datetime import datetime, UTC
from uuid import uuid4
from sqlalchemy import String, DateTime, Enum, Boolean, Text, ForeignKey, Index, Integer, JSON, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class JobStatus(str, enum.Enum):
    """Delivery job status."""
    PENDING = "pending"
    PROCESSING = "processing"
    READY_FOR_DISPATCH = "ready_for_dispatch"
    DISPATCHED = "dispatched"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ItemStatus(str, enum.Enum):
    """Delivery item status."""
    PENDING = "pending"
    VALIDATED = "validated"
    INVALID = "invalid"
    ASSIGNED = "assigned"
    DELIVERED = "delivered"
    FAILED = "failed"


class FailureReason(str, enum.Enum):
    """Reasons for delivery failure."""
    ADDRESS_NOT_FOUND = "address_not_found"
    RECIPIENT_UNAVAILABLE = "recipient_unavailable"
    RECIPIENT_REFUSED = "recipient_refused"
    WRONG_ADDRESS = "wrong_address"
    ACCESS_DENIED = "access_denied"
    VEHICLE_ISSUE = "vehicle_issue"
    WEATHER = "weather"
    OTHER = "other"


class DeliveryJob(Base):
    """Delivery job/batch model."""
    __tablename__ = "delivery_jobs"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)

    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False),
        default=JobStatus.PENDING,
        nullable=False,
        index=True,
    )

    # Source file info
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    total_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    validated_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Routing optimization
    route_optimized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    optimization_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Timestamps
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="delivery_jobs", lazy="selectin"
    )
    items: Mapped[list["DeliveryItem"]] = relationship(
        "DeliveryItem", back_populates="job", lazy="selectin", cascade="all, delete-orphan"
    )
    failed_deliveries: Mapped[list["FailedDelivery"]] = relationship(
        "FailedDelivery", back_populates="job", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<DeliveryJob(id={self.id}, ref={self.reference_number}, status={self.status})>"


class DeliveryItem(Base):
    """Individual delivery item within a job."""
    __tablename__ = "delivery_items"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("delivery_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Original input
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    recipient_name: Mapped[str] = mapped_column(String(255), nullable=False)
    recipient_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    raw_address: Mapped[str] = mapped_column(Text, nullable=False)
    landmarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Validation result
    status: Mapped[ItemStatus] = mapped_column(
        Enum(ItemStatus, native_enum=False),
        default=ItemStatus.PENDING,
        nullable=False,
        index=True,
    )
    postcode: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    postcode_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    formatted_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[float | None] = mapped_column(nullable=True)
    longitude: Mapped[float | None] = mapped_column(nullable=True)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lga: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ward: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(nullable=True)

    # Assignment
    rider_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    rider_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Delivery tracking
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_latitude: Mapped[float | None] = mapped_column(nullable=True)
    delivery_longitude: Mapped[float | None] = mapped_column(nullable=True)
    delivery_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    proof_of_delivery_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

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
    job: Mapped["DeliveryJob"] = relationship("DeliveryJob", back_populates="items", lazy="selectin")

    __table_args__ = (
        Index("ix_delivery_item_job_seq", "job_id", "sequence_number"),
        Index("ix_delivery_item_postcode", "postcode"),
        Index("ix_delivery_item_rider", "rider_id"),
    )

    def __repr__(self) -> str:
        return f"<DeliveryItem(id={self.id}, job_id={self.job_id}, seq={self.sequence_number}, status={self.status})>"


class FailedDelivery(Base):
    """Failed delivery log for analysis and retry."""
    __tablename__ = "failed_deliveries"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("delivery_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("delivery_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Failure details
    reason: Mapped[FailureReason] = mapped_column(
        Enum(FailureReason, native_enum=False), nullable=False, index=True
    )
    reason_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    rider_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    rider_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Location at failure
    failure_latitude: Mapped[float | None] = mapped_column(nullable=True)
    failure_longitude: Mapped[float | None] = mapped_column(nullable=True)
    failure_postcode: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)

    # Retry tracking
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    last_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    job: Mapped["DeliveryJob"] = relationship("DeliveryJob", back_populates="failed_deliveries", lazy="selectin")

    __table_args__ = (
        Index("ix_failed_delivery_org_created", "organization_id", "created_at"),
        Index("ix_failed_delivery_retry", "next_retry_at", "resolved"),
    )

    def __repr__(self) -> str:
        return f"<FailedDelivery(id={self.id}, item_id={self.item_id}, reason={self.reason})>"