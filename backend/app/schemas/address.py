"""Address validation schemas."""
from typing import Optional, List, Dict, Any
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from enum import Enum


class ValidationStatus(str, Enum):
    VALID = "valid"
    INVALID = "invalid"
    PARTIAL = "partial"
    ERROR = "error"


class ValidationSource(str, Enum):
    API = "api"
    BULK_UPLOAD = "bulk_upload"
    DASHBOARD = "dashboard"
    WIDGET = "widget"


class AddressValidationRequest(BaseModel):
    """Single address validation request."""
    address: str = Field(..., min_length=1, max_length=1000, description="Free-text address")
    landmarks: Optional[str] = Field(None, max_length=500, description="Nearby landmarks")
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    postcode_level: Optional[str] = Field(default="building", pattern=r"^(state|lga|ward|district|area|building)$")


class BulkAddressValidationRequest(BaseModel):
    """Bulk address validation request."""
    addresses: List[AddressValidationRequest] = Field(..., min_length=1, max_length=1000)
    callback_url: Optional[str] = None


class AddressValidationResult(BaseModel):
    """Single address validation result."""
    model_config = ConfigDict(from_attributes=True)

    # Input
    raw_address: str
    raw_landmarks: Optional[str] = None
    input_latitude: Optional[float] = None
    input_longitude: Optional[float] = None

    # Result
    status: ValidationStatus
    postcode: Optional[str] = None
    postcode_level: Optional[str] = None
    formatted_address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    state: Optional[str] = None
    lga: Optional[str] = None
    ward: Optional[str] = None
    district: Optional[str] = None
    area: Optional[str] = None

    # Confidence
    confidence_score: Optional[float] = Field(None, ge=0, le=1)
    match_type: Optional[str] = None
    suggestions: Optional[List[Dict[str, Any]]] = None

    # Metadata
    processing_time_ms: int = 0


class AddressValidationResponse(BaseModel):
    """Response for single address validation."""
    request_id: UUID
    result: AddressValidationResult


class BulkValidationResponse(BaseModel):
    """Response for bulk validation."""
    batch_id: UUID
    total: int
    processed: int
    valid: int
    invalid: int
    partial: int
    errors: int
    results: List[AddressValidationResult]


class AddressAutocompleteRequest(BaseModel):
    """Address autocomplete request."""
    query: str = Field(..., min_length=1, max_length=200)
    limit: int = Field(default=10, ge=1, le=50)
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    radius_km: Optional[float] = Field(None, ge=0, le=100)


class AutocompleteSuggestion(BaseModel):
    """Autocomplete suggestion."""
    address: str
    postcode: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    state: Optional[str] = None
    lga: Optional[str] = None
    confidence: float = Field(ge=0, le=1)


class AddressAutocompleteResponse(BaseModel):
    """Address autocomplete response."""
    suggestions: List[AutocompleteSuggestion]


class ReverseGeocodeRequest(BaseModel):
    """Reverse geocode request."""
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    radius_meters: int = Field(default=100, ge=1, le=5000)


class PostcodeLookupRequest(BaseModel):
    """Postcode lookup request."""
    postcode: str = Field(..., min_length=1, max_length=20)


class PostcodeInfo(BaseModel):
    """Postcode information."""
    postcode: str
    state: str
    lga: str
    ward: Optional[str] = None
    district: Optional[str] = None
    area: Optional[str] = None
    latitude: float
    longitude: float


class ValidationLogEntry(BaseModel):
    """Validation log entry for history."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    raw_address: str
    status: ValidationStatus
    postcode: Optional[str] = None
    formatted_address: Optional[str] = None
    confidence_score: Optional[float] = None
    source: ValidationSource
    processing_time_ms: int
    created_at: Any  # datetime


class ValidationStats(BaseModel):
    """Validation statistics."""
    total_validations: int
    valid_count: int
    invalid_count: int
    partial_count: int
    error_count: int
    success_rate: float
    avg_processing_time_ms: float
    top_postcodes: List[Dict[str, Any]]
    top_states: List[Dict[str, Any]]