"""KYC/Address Verification API routes."""
from typing import Optional
from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
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
from app.models.kyc import VerificationRequest, VerificationResult, VerificationStatus, VerificationType
from app.schemas.kyc import (
    VerificationRequestCreate,
    VerificationRequestResponse,
    VerificationRequestDetail,
    VerificationRequestListResponse,
    VerificationResultResponse,
)
from app.services.kyc_service import KYCService

router = APIRouter()
logger = structlog.get_logger()


def get_kyc_service(db: AsyncSession = Depends(get_db)) -> KYCService:
    return KYCService(db)


@router.post("/verify", response_model=VerificationRequestResponse, status_code=status.HTTP_201_CREATED)
async def create_verification(
    request: VerificationRequestCreate,
    svc: KYCService = Depends(get_kyc_service),
    organization_id: UUID = Depends(get_organization_id),
    api_key = Depends(get_api_key_optional),
    current_user = Depends(get_current_user_optional),
):
    """Create a new address/identity verification request."""
    return await svc.create_verification(
        request=request,
        organization_id=organization_id,
        api_key_id=api_key.id if api_key else None,
        submitted_by_id=current_user.id if current_user else None,
    )


@router.get("/verify", response_model=VerificationRequestListResponse)
async def list_verifications(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: Optional[VerificationStatus] = Query(None),
    verification_type: Optional[VerificationType] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    svc: KYCService = Depends(get_kyc_service),
    organization_id: UUID = Depends(get_organization_id),
    api_key = Depends(get_api_key_optional),
    current_user = Depends(get_current_user_optional),
):
    """List verification requests with pagination and filters."""
    return await svc.list_verifications(
        organization_id=organization_id,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
        verification_type=verification_type,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/verify/{request_id}", response_model=VerificationRequestDetail)
async def get_verification(
    request_id: UUID,
    svc: KYCService = Depends(get_kyc_service),
    organization_id: UUID = Depends(get_organization_id),
    api_key = Depends(get_api_key_optional),
    current_user = Depends(get_current_user_optional),
):
    """Get verification request with result."""
    verification = await svc.get_verification(request_id, organization_id)
    if not verification:
        raise HTTPException(status_code=404, detail="Verification request not found")
    return verification


@router.get("/verify/{request_id}/result", response_model=VerificationResultResponse)
async def get_verification_result(
    request_id: UUID,
    svc: KYCService = Depends(get_kyc_service),
    organization_id: UUID = Depends(get_organization_id),
    api_key = Depends(get_api_key_optional),
    current_user = Depends(get_current_user_optional),
):
    """Get detailed verification result."""
    result = await svc.get_result(request_id, organization_id)
    if not result:
        raise HTTPException(status_code=404, detail="Verification result not found")
    return result


@router.post("/verify/{request_id}/review")
async def review_verification(
    request_id: UUID,
    approved: bool,
    notes: Optional[str] = None,
    svc: KYCService = Depends(get_kyc_service),
    organization_id: UUID = Depends(get_organization_id),
    current_user = Depends(get_current_user_optional),
):
    """Manual review of a verification request (admin only)."""
    if not current_user or current_user.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    return await svc.manual_review(
        request_id, organization_id, current_user.id, approved, notes
    )


@router.post("/verify/{request_id}/retry")
async def retry_verification(
    request_id: UUID,
    svc: KYCService = Depends(get_kyc_service),
    organization_id: UUID = Depends(get_organization_id),
    api_key = Depends(get_api_key_optional),
    current_user = Depends(get_current_user_optional),
):
    """Retry a failed verification."""
    return await svc.retry_verification(request_id, organization_id)