"""Logistics/Delivery schemas."""
from typing import Optional, List
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from enum import Enum

from app.schemas.address import AddressValidationResult


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY_FOR_DISPATCH = "ready_for_dispatch"
    DISPATCHED = "dispatched"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ItemStatus(str, Enum):
    PENDING = "pending"
    VALIDATED = "validated"
    INVALID = "invalid"
    ASSIGNED = "assigned"
    DELIVERED = "delivered"
    FAILED = "failed"


class FailureReason(str, Enum):
    ADDRESS_NOT_FOUND = "address_not_found"
    RECIPIENT_UNAVAILABLE = "recipient_unavailable"
    RECIPIENT_REFUSED = "recipient_refused"
    WRONG_ADDRESS = "wrong_address"
    ACCESS_DENIED = "access_denied"
    VEHICLE_ISSUE = "vehicle_issue"
    WEATHER = "weather"
    OTHER = "other"


# -------------------------------------------------------------------------
# Delivery Job Schemas
# -------------------------------------------------------------------------

class DeliveryJobCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    source_filename: Optional[str] = None
    scheduled_for: Optional[datetime] = None
    items: Optional[List["DeliveryItemCreate"]] = None


class DeliveryJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    created_by_id: Optional[UUID] = None
    name: str
    description: Optional[str] = None
    reference_number: str
    status: JobStatus
    source_filename: Optional[str] = None
    total_items: int
    validated_items: int
    failed_items: int
    route_optimized: bool
    scheduled_for: Optional[datetime] = None
    dispatched_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class DeliveryJobDetail(DeliveryJobResponse):
    items: List["DeliveryItemResponse"] = []


class DeliveryJobListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[DeliveryJobResponse]


# -------------------------------------------------------------------------
# Delivery Item Schemas
# -------------------------------------------------------------------------

class DeliveryItemCreate(BaseModel):
    recipient_name: str = Field(..., min_length=1, max_length=255)
    recipient_phone: str = Field(..., min_length=1, max_length=20)
    raw_address: str = Field(..., min_length=1, max_length=1000)
    landmarks: Optional[str] = None
    notes: Optional[str] = None


class DeliveryItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: UUID
    sequence_number: int
    recipient_name: str
    recipient_phone: str
    raw_address: str
    landmarks: Optional[str] = None
    notes: Optional[str] = None
    status: ItemStatus
    postcode: Optional[str] = None
    postcode_level: Optional[str] = None
    formatted_address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    state: Optional[str] = None
    lga: Optional[str] = None
    ward: Optional[str] = None
    confidence_score: Optional[float] = None
    rider_id: Optional[UUID] = None
    rider_name: Optional[str] = None
    assigned_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    delivery_latitude: Optional[float] = None
    delivery_longitude: Optional[float] = None
    delivery_notes: Optional[str] = None
    proof_of_delivery_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# -------------------------------------------------------------------------
# Failed Delivery Schemas
# -------------------------------------------------------------------------

class FailedDeliveryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: UUID
    item_id: UUID
    organization_id: UUID
    reason: FailureReason
    reason_details: Optional[str] = None
    rider_id: Optional[UUID] = None
    rider_notes: Optional[str] = None
    failure_latitude: Optional[float] = None
    failure_longitude: Optional[float] = None
    failure_postcode: Optional[str] = None
    retry_count: int
    max_retries: int
    last_retry_at: Optional[datetime] = None
    next_retry_at: Optional[datetime] = None
    resolved: bool
    resolved_at: Optional[datetime] = None
    resolution_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# -------------------------------------------------------------------------
# Route Optimization Schemas
# -------------------------------------------------------------------------

class RouteOptimizationRequest(BaseModel):
    vehicle_capacity: int = Field(default=50, ge=1, le=200)
    optimization_goal: str = Field(default="distance", pattern="^(distance|time|balanced)$")
    max_route_time_hours: Optional[float] = Field(None, ge=1, le=24)


class RouteOptimizationResponse(BaseModel):
    job_id: UUID
    task_id: str
    status: str
    message: str
    total_distance_km: Optional[float] = None
    total_time_minutes: Optional[float] = None
    routes: Optional[List[Dict]] = None


# Update forward references
DeliveryJobCreate.model_rebuild()
DeliveryJobDetail.model_rebuild()