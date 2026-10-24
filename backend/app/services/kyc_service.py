"""KYC/Address Verification service - business logic layer."""
from typing import Optional, List, Dict, Any
from uuid import UUID, uuid4
from datetime import datetime, UTC

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import structlog

from app.models.kyc import VerificationRequest, VerificationResult, VerificationStatus, VerificationType
from app.models.organization import Organization
from app.schemas.kyc import VerificationRequestCreate
from app.services.nipost_client import nipost_client
from app.services.rate_limit import check_organization_rate_limit
from app.tasks.notification_tasks import send_verification_webhook

logger = structlog.get_logger()


class KYCService:
    """Service for KYC/Address verification operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_verification(
        self,
        request: VerificationRequestCreate,
        organization_id: UUID,
        api_key_id: Optional[UUID] = None,
        submitted_by_id: Optional[UUID] = None,
    ) -> VerificationRequest:
        """Create a new verification request."""
        # Check rate limit
        allowed, retry_after = await check_organization_rate_limit(str(organization_id), limit_per_minute=30)
        if not allowed:
            from fastapi import HTTPException, status
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")

        # Create verification request
        vr = VerificationRequest(
            organization_id=organization_id,
            api_key_id=api_key_id,
            submitted_by_id=submitted_by_id,
            external_reference=request.external_reference,
            verification_type=request.verification_type,
            subject_name=request.subject_name,
            subject_phone=request.subject_phone,
            subject_email=request.subject_email,
            subject_id_type=request.subject_id_type,
            subject_id_number=request.subject_id_number,
            raw_address=request.raw_address,
            landmarks=request.landmarks,
            input_latitude=request.input_latitude,
            input_longitude=request.input_longitude,
            callback_url=request.callback_url,
            callback_secret=request.callback_secret,
            expires_at=request.expires_at or datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0),
        )
        self.db.add(vr)
        await self.db.flush()

        # Start async verification
        await self._process_verification(vr)

        await self.db.commit()
        await self.db.refresh(vr)

        logger.info("verification_created", request_id=str(vr.id), org_id=str(organization_id))
        return vr

    async def _process_verification(self, vr: VerificationRequest) -> None:
        """Process verification asynchronously (called after commit)."""
        # Update status to processing
        vr.status = VerificationStatus.PROCESSING
        await self.db.commit()

        try:
            # Validate address with NIPOST
            validation = await nipost_client.validate_address(
                address=vr.raw_address,
                landmarks=vr.landmarks or "",
                latitude=vr.input_latitude,
                longitude=vr.input_longitude,
            )

            # Create result
            result = VerificationResult(
                request_id=vr.id,
                address_match=validation.status.value == "valid",
                address_confidence=validation.confidence_score or 0.0,
                postcode_verified=validation.postcode is not None,
                coordinates_verified=validation.latitude is not None and validation.longitude is not None,
                nipost_postcode=validation.postcode,
                nipost_address=validation.formatted_address,
                nipost_latitude=validation.latitude,
                nipost_longitude=validation.longitude,
                nipost_state=validation.state,
                nipost_lga=validation.lga,
                nipost_ward=validation.ward,
            )

            # Calculate risk score
            risk_score = 0
            risk_factors = []

            if validation.status.value != "valid":
                risk_score += 30
                risk_factors.append("address_invalid")

            if validation.confidence_score and validation.confidence_score < 0.7:
                risk_score += 20
                risk_factors.append("low_confidence")

            if vr.verification_type in [VerificationType.ADDRESS_AND_IDENTITY, VerificationType.BUSINESS_ADDRESS]:
                # Additional identity checks would go here
                if not vr.subject_id_number:
                    risk_score += 25
                    risk_factors.append("missing_id_number")

            result.risk_score = min(risk_score, 100)
            result.risk_factors = risk_factors if risk_factors else None

            # Determine final status
            if risk_score >= 70:
                vr.status = VerificationStatus.MANUAL_REVIEW
            elif risk_score >= 40:
                vr.status = VerificationStatus.FAILED
            else:
                vr.status = VerificationStatus.VERIFIED

            vr.completed_at = datetime.now(UTC)
            self.db.add(result)
            await self.db.commit()

            # Send webhook if configured
            if vr.callback_url:
                send_verification_webhook.delay(
                    str(vr.id), str(vr.organization_id), vr.callback_url, vr.callback_secret or ""
                )

            logger.info("verification_completed", request_id=str(vr.id), status=vr.status.value, risk_score=risk_score)

        except Exception as e:
            vr.status = VerificationStatus.FAILED
            vr.completed_at = datetime.now(UTC)
            await self.db.commit()
            logger.error("verification_failed", request_id=str(vr.id), error=str(e))

    async def list_verifications(
        self,
        organization_id: UUID,
        page: int = 1,
        page_size: int = 20,
        status_filter: Optional[VerificationStatus] = None,
        verification_type: Optional[VerificationType] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """List verification requests."""
        query = select(VerificationRequest).where(VerificationRequest.organization_id == organization_id)

        if status_filter:
            query = query.where(VerificationRequest.status == status_filter)
        if verification_type:
            query = query.where(VerificationRequest.verification_type == verification_type)
        if date_from:
            query = query.where(VerificationRequest.created_at >= date_from)
        if date_to:
            query = query.where(VerificationRequest.created_at <= date_to)

        query = query.order_by(VerificationRequest.created_at.desc())

        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.scalar(count_query)

        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        result = await self.db.execute(query)
        items = result.scalars().all()

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": items,
        }

    async def get_verification(self, request_id: UUID, organization_id: UUID) -> Optional[VerificationRequest]:
        """Get verification request with result."""
        result = await self.db.execute(
            select(VerificationRequest)
            .options(selectinload(VerificationRequest.result))
            .where(VerificationRequest.id == request_id, VerificationRequest.organization_id == organization_id)
        )
        return result.scalar_one_or_none()

    async def get_result(self, request_id: UUID, organization_id: UUID) -> Optional[VerificationResult]:
        """Get verification result."""
        result = await self.db.execute(
            select(VerificationResult)
            .join(VerificationRequest)
            .where(VerificationResult.request_id == request_id, VerificationRequest.organization_id == organization_id)
        )
        return result.scalar_one_or_none()

    async def manual_review(
        self,
        request_id: UUID,
        organization_id: UUID,
        reviewer_id: UUID,
        approved: bool,
        notes: Optional[str] = None,
    ) -> VerificationRequest:
        """Manual review of verification."""
        vr = await self.get_verification(request_id, organization_id)
        if not vr:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Verification not found")

        if vr.status != VerificationStatus.MANUAL_REVIEW:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Not pending manual review")

        vr.status = VerificationStatus.VERIFIED if approved else VerificationStatus.FAILED
        vr.completed_at = datetime.now(UTC)

        if vr.result:
            vr.result.reviewed_by_id = reviewer_id
            vr.result.reviewed_at = datetime.now(UTC)
            vr.result.review_notes = notes

        await self.db.commit()
        await self.db.refresh(vr)

        logger.info("verification_reviewed", request_id=str(request_id), approved=approved)
        return vr

    async def retry_verification(self, request_id: UUID, organization_id: UUID) -> VerificationRequest:
        """Retry a failed verification."""
        vr = await self.get_verification(request_id, organization_id)
        if not vr:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Verification not found")

        vr.status = VerificationStatus.PENDING
        vr.completed_at = None
        await self.db.commit()

        # Re-process
        await self._process_verification(vr)

        return vr