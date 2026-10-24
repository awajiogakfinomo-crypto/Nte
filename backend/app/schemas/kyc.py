"""KYC/Address Verification schemas."""
from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from enum import Enum


class VerificationStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    VERIFIED = "verified"
    FAILED = "failed"
    MANUAL_REVIEW = "manual_review"
    EXPIRED = "expired"


class VerificationType(str, Enum):
    ADDRESS_ONLY = "address_only"
    ADDRESS_AND_IDENTITY = "address_and_identity"
    BUSINESS_ADDRESS = "business_address"


# -------------------------------------------------------------------------
# Verification Request Schemas
# -------------------------------------------------------------------------

class VerificationRequestCreate(BaseModel):
    external_reference: Optional[str] = Field(None, max_length=100)
    verification_type: VerificationType = VerificationType.ADDRESS_ONLY
    subject_name: str = Field(..., min_length=1, max_length=255)
    subject_phone: str = Field(..., min_length=1, max_length=20)
    subject_email: Optional[EmailStr] = None
    subject_id_type: Optional[str] = Field(None, max_length=50)
    subject_id_number: Optional[str] = Field(None, max_length=50)
    raw_address: str = Field(..., min_length=1, max_length=1000)
    landmarks: Optional[str] = None
    input_latitude: Optional[float] = Field(None, ge=-90, le=90)
    input_longitude: Optional[float] = Field(None, ge=-180, le=180)
    callback_url: Optional[str] = Field(None, max_length=500)
    callback_secret: Optional[str] = Field(None, max_length=255)
    expires_at: Optional[datetime] = None


class VerificationRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    api_key_id: Optional[UUID] = None
    submitted_by_id: Optional[UUID] = None
    external_reference: Optional[str] = None
    verification_type: VerificationType
    status: VerificationStatus
    subject_name: str
    subject_phone: str
    subject_email: Optional[str] = None
    subject_id_type: Optional[str] = None
    subject_id_number: Optional[str] = None
    raw_address: str
    landmarks: Optional[str] = None
    input_latitude: Optional[float] = None
    input_longitude: Optional[float] = None
    callback_url: Optional[str] = None
    completed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class VerificationRequestDetail(VerificationRequestResponse):
    result: Optional["VerificationResultResponse"] = None


class VerificationRequestListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[VerificationRequestResponse]


# -------------------------------------------------------------------------
# Verification Result Schemas
# -------------------------------------------------------------------------

class VerificationResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    request_id: UUID
    address_match: bool
    address_confidence: float
    postcode_verified: bool
    coordinates_verified: bool
    nipost_postcode: Optional[str] = None
    nipost_address: Optional[str] = None
    nipost_latitude: Optional[float] = None
    nipost_longitude: Optional[float] = None
    nipost_state: Optional[str] = None
    nipost_lga: Optional[str] = None
    nipost_ward: Optional[str] = None
    discrepancies: Optional[List[Dict[str, Any]]] = None
    risk_score: int
    risk_factors: Optional[List[str]] = None
    documents_verified: bool
    document_details: Optional[List[Dict[str, Any]]] = None
    reviewed_by_id: Optional[UUID] = None
    reviewed_at: Optional[datetime] = None
    review_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# Update forward references
VerificationRequestDetail.model_rebuild()