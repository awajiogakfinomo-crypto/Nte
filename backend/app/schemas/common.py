"""Common schemas and base classes."""
from datetime import datetime
from typing import Generic, TypeVar, Optional, List, Any
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


class BaseSchema(BaseModel):
    """Base schema with common configuration."""
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        use_enum_values=True,
        json_encoders={
            datetime: lambda v: v.isoformat() if v else None,
            UUID: lambda v: str(v) if v else None,
        },
    )


T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated response wrapper."""
    items: List[T]
    total: int
    page: int
    page_size: int
    total_pages: int

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages

    @property
    def has_prev(self) -> bool:
        return self.page > 1


class ErrorResponse(BaseModel):
    """Standard error response."""
    error: str
    message: str
    details: Optional[dict] = None
    request_id: Optional[str] = None


class SuccessResponse(BaseModel, Generic[T]):
    """Standard success response."""
    success: bool = True
    data: T
    message: Optional[str] = None


class HealthCheckResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    environment: str
    database: str
    redis: str
    postcode_api: str
    timestamp: datetime