"""Usage analytics and billing schemas."""
from typing import Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict
from enum import Enum

from app.models.organization import OrganizationPlan


class UsageType(str, Enum):
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


class UsageRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    api_key_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    usage_type: UsageType
    endpoint: str
    method: str
    status_code: int
    request_count: int
    items_processed: int
    response_time_ms: int
    cost_kobo: int
    created_at: datetime


class UsageListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[UsageRecordResponse]


class UsageSummary(BaseModel):
    period_days: int
    total_requests: int
    total_cost_kobo: int
    total_cost_ngn: float
    by_type: Dict[str, Dict[str, Any]]
    monthly_limit: int
    monthly_used: int
    monthly_remaining: int
    plan: str


class BillingSummary(BaseModel):
    period_start: datetime
    period_end: datetime
    plan: str
    monthly_limit: int
    requests_this_month: int
    cost_this_month_kobo: int
    cost_this_month_ngn: float
    overage_requests: int
    overage_cost_kobo: int


class PlanLimits(BaseModel):
    plan: str
    monthly_api_calls: int
    rate_limit_per_minute: int
    rate_limit_per_day: int
    current_usage: int
    features: Dict[str, bool]