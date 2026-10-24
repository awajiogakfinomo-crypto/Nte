"""KYC/Address Verification models."""
import enum
from datetime import datetime, UTC
from uuid import uuid4
from sqlalchemy import String, DateTime, Enum, Boolean, Text, ForeignKey, Index, Integer, JSON, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class VerificationStatus(str, enum.Enum):
    """Verification request status."""
    PENDING = "pending"
    PROCESSING = "processing"
    VERIFIED = "verified"
    FAILED = "failed"
    MANUAL_REVIEW = "manual_review"
    EXPIRED = "expired"


class VerificationType(str, enum.Enum):
    """Type of verification."""
    ADDRESS_ONLY = "address_only"
    ADDRESS_AND_IDENTITY = "address_and_identity"
    BUSINESS_ADDRESS = "business_address"


class VerificationResult(Base):
    """Detailed verification result."""
    __tablename__ = "verification_results"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    request_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("verification_requests.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )

    # Address verification details
    address_match: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    address_confidence: Mapped[float] = mapped_column(Numeric(3, 2), default=0.0, nullable=False)
    postcode_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    coordinates_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # NIPOST API response
    nipost_postcode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    nipost_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    nipost_latitude: Mapped[float | None] = mapped_column(nullable=True)
    nipost_longitude: Mapped[float | None] = mapped_column(nullable=True)
    nipost_state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    nipost_lga: Mapped[str | None] = mapped_column(String(100), nullable=True)
    nipost_ward: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Discrepancies found
    discrepancies: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)

    # Risk signals
    risk_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 0-100
    risk_factors: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # Supporting documents (if identity verification)
    documents_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    document_details: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)

    # Manual review
    reviewed_by_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class VerificationRequest(Base):
    """KYC/Address verification request."""
    __tablename__ = "verification_requests"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    api_key_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True, index=True
    )
    submitted_by_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # External reference (from client system)
    external_reference: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    # Verification details
    verification_type: Mapped[VerificationType] = mapped_column(
        Enum(VerificationType, native_enum=False),
        default=VerificationType.ADDRESS_ONLY,
        nullable=False,
    )
    status: Mapped[VerificationStatus] = mapped_column(
        Enum(VerificationStatus, native_enum=False),
        default=VerificationStatus.PENDING,
        nullable=False,
        index=True,
    )

    # Subject information
    subject_name: Mapped[str] = mapped_column(String(255), nullable=False)
    subject_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    subject_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject_id_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # NIN, BVN, Drivers License, etc.
    subject_id_number: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Address to verify
    raw_address: Mapped[str] = mapped_column(Text, nullable=False)
    landmarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_latitude: Mapped[float | None] = mapped_column(nullable=True)
    input_longitude: Mapped[float | None] = mapped_column(nullable=True)

    # Callback/webhook
    callback_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    callback_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Result reference
    result: Mapped["VerificationResult | None"] = relationship(
        "VerificationResult", back_populates="request", lazy="selectin", cascade="all, delete-orphan"
    )

    # Timestamps
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

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
        "Organization", back_populates="verification_requests", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_verification_org_created", "organization_id", "created_at"),
        Index("ix_verification_external_ref", "external_reference"),
        Index("ix_verification_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<VerificationRequest(id={self.id}, subject={self.subject_name}, status={self.status})>"