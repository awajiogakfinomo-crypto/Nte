"""Logistics/Delivery management API routes."""
from typing import Optional, List
from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import structlog

from app.api.deps import (
    get_api_key,
    get_api_key_optional,
    get_current_user_optional,
    get_db,
    get_organization_id,
    get_pagination,
)
from app.models.logistics import DeliveryJob, DeliveryItem, JobStatus, ItemStatus, FailedDelivery, FailureReason
from app.models.organization import Organization
from app.schemas.logistics import (
    DeliveryJobCreate,
    DeliveryJobResponse,
    DeliveryJobDetail,
    DeliveryItemCreate,
    DeliveryItemResponse,
    DeliveryJobListResponse,
    FailedDeliveryResponse,
    RouteOptimizationRequest,
    RouteOptimizationResponse,
)
from app.services.logistics_service import LogisticsService

router = APIRouter()
logger = structlog.get_logger()


def get_logistics_service(db: AsyncSession = Depends(get_db)) -> LogisticsService:
    return LogisticsService(db)


# -------------------------------------------------------------------------
# Delivery Jobs
# -------------------------------------------------------------------------

@router.post("/jobs", response_model=DeliveryJobResponse, status_code=status.HTTP_201_CREATED)
async def create_delivery_job(
    request: DeliveryJobCreate,
    svc: LogisticsService = Depends(get_logistics_service),
    organization_id: UUID = Depends(get_organization_id),
    api_key = Depends(get_api_key_optional),
    current_user = Depends(get_current_user_optional),
):
    """Create a new delivery job/batch."""
    return await svc.create_job(
        request=request,
        organization_id=organization_id,
        api_key_id=api_key.id if api_key else None,
        created_by_id=current_user.id if current_user else None,
    )


@router.get("/jobs", response_model=DeliveryJobListResponse)
async def list_delivery_jobs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: Optional[JobStatus] = Query(None, description="Filter by job status"),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    svc: LogisticsService = Depends(get_logistics_service),
    organization_id: UUID = Depends(get_organization_id),
    api_key = Depends(get_api_key_optional),
    current_user = Depends(get_current_user_optional),
):
    """List delivery jobs with pagination and filters."""
    return await svc.list_jobs(
        organization_id=organization_id,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/jobs/{job_id}", response_model=DeliveryJobDetail)
async def get_delivery_job(
    job_id: UUID,
    svc: LogisticsService = Depends(get_logistics_service),
    organization_id: UUID = Depends(get_organization_id),
    api_key = Depends(get_api_key_optional),
    current_user = Depends(get_current_user_optional),
):
    """Get delivery job with all items."""
    job = await svc.get_job(job_id, organization_id)
    if not job:
        raise HTTPException(status_code=404, detail="Delivery job not found")
    return job


@router.post("/jobs/{job_id}/items", response_model=List[DeliveryItemResponse])
async def add_delivery_items(
    job_id: UUID,
    items: List[DeliveryItemCreate],
    svc: LogisticsService = Depends(get_logistics_service),
    organization_id: UUID = Depends(get_organization_id),
    api_key = Depends(get_api_key_optional),
    current_user = Depends(get_current_user_optional),
):
    """Add items to a delivery job."""
    return await svc.add_items(job_id, organization_id, items)


@router.post("/jobs/{job_id}/validate", response_model=DeliveryJobResponse)
async def validate_delivery_job(
    job_id: UUID,
    svc: LogisticsService = Depends(get_logistics_service),
    organization_id: UUID = Depends(get_organization_id),
    api_key = Depends(get_api_key_optional),
    current_user = Depends(get_current_user_optional),
):
    """Validate all addresses in a delivery job using NIPOST API."""
    return await svc.validate_job(job_id, organization_id)


@router.post("/jobs/{job_id}/optimize", response_model=RouteOptimizationResponse)
async def optimize_route(
    job_id: UUID,
    request: RouteOptimizationRequest,
    svc: LogisticsService = Depends(get_logistics_service),
    organization_id: UUID = Depends(get_organization_id),
    api_key = Depends(get_api_key_optional),
    current_user = Depends(get_current_user_optional),
):
    """Optimize delivery route for a job using OR-Tools."""
    return await svc.optimize_route(job_id, organization_id, request)


@router.post("/jobs/{job_id}/dispatch", response_model=DeliveryJobResponse)
async def dispatch_job(
    job_id: UUID,
    svc: LogisticsService = Depends(get_logistics_service),
    organization_id: UUID = Depends(get_organization_id),
    api_key = Depends(get_api_key_optional),
    current_user = Depends(get_current_user_optional),
):
    """Mark job as dispatched to riders."""
    return await svc.dispatch_job(job_id, organization_id)


@router.post("/jobs/{job_id}/complete", response_model=DeliveryJobResponse)
async def complete_job(
    job_id: UUID,
    svc: LogisticsService = Depends(get_logistics_service),
    organization_id: UUID = Depends(get_organization_id),
    api_key = Depends(get_api_key_optional),
    current_user = Depends(get_current_user_optional),
):
    """Mark job as completed."""
    return await svc.complete_job(job_id, organization_id)


# -------------------------------------------------------------------------
# Delivery Items
# -------------------------------------------------------------------------

@router.patch("/items/{item_id}/deliver", response_model=DeliveryItemResponse)
async def mark_item_delivered(
    item_id: UUID,
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    notes: Optional[str] = None,
    proof_url: Optional[str] = None,
    svc: LogisticsService = Depends(get_logistics_service),
    organization_id: UUID = Depends(get_organization_id),
    api_key = Depends(get_api_key_optional),
    current_user = Depends(get_current_user_optional),
):
    """Mark a delivery item as delivered with proof."""
    return await svc.mark_delivered(
        item_id, organization_id, latitude, longitude, notes, proof_url
    )


@router.patch("/items/{item_id}/fail", response_model=DeliveryItemResponse)
async def mark_item_failed(
    item_id: UUID,
    reason: FailureReason,
    reason_details: Optional[str] = None,
    latitude: Optional[float] = Query(None, ge=-90, le=90),
    longitude: Optional[float] = Query(None, ge=-180, le=180),
    svc: LogisticsService = Depends(get_logistics_service),
    organization_id: UUID = Depends(get_organization_id),
    api_key = Depends(get_api_key_optional),
    current_user = Depends(get_current_user_optional),
):
    """Mark a delivery item as failed."""
    return await svc.mark_failed(
        item_id, organization_id, reason, reason_details, latitude, longitude
    )


# -------------------------------------------------------------------------
# Failed Deliveries
# -------------------------------------------------------------------------

@router.get("/failed", response_model=List[FailedDeliveryResponse])
async def list_failed_deliveries(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    resolved: Optional[bool] = Query(None),
    svc: LogisticsService = Depends(get_logistics_service),
    organization_id: UUID = Depends(get_organization_id),
    api_key = Depends(get_api_key_optional),
    current_user = Depends(get_current_user_optional),
):
    """List failed deliveries for retry/analysis."""
    return await svc.list_failed(
        organization_id=organization_id,
        page=page,
        page_size=page_size,
        resolved=resolved,
    )


@router.post("/failed/{failed_id}/retry", response_model=FailedDeliveryResponse)
async def retry_failed_delivery(
    failed_id: UUID,
    svc: LogisticsService = Depends(get_logistics_service),
    organization_id: UUID = Depends(get_organization_id),
    api_key = Depends(get_api_key_optional),
    current_user = Depends(get_current_user_optional),
):
    """Retry a failed delivery."""
    return await svc.retry_failed(failed_id, organization_id)