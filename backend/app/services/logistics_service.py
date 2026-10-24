"""Logistics/Delivery service - business logic layer."""
from typing import List, Optional, Dict, Any
from uuid import UUID, uuid4
from datetime import datetime, UTC
from decimal import Decimal

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import structlog

from app.models.logistics import (
    DeliveryJob, DeliveryItem, FailedDelivery,
    JobStatus, ItemStatus, FailureReason
)
from app.models.organization import Organization
from app.schemas.logistics import (
    DeliveryJobCreate, DeliveryItemCreate,
    RouteOptimizationRequest, RouteOptimizationResponse,
)
from app.services.nipost_client import nipost_client
from app.services.rate_limit import check_organization_rate_limit
from app.tasks.logistics_tasks import optimize_delivery_route, notify_delivery_status

logger = structlog.get_logger()


class LogisticsService:
    """Service for logistics/delivery operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # -------------------------------------------------------------------------
    # Delivery Jobs
    # -------------------------------------------------------------------------

    async def create_job(
        self,
        request: DeliveryJobCreate,
        organization_id: UUID,
        api_key_id: Optional[UUID] = None,
        created_by_id: Optional[UUID] = None,
    ) -> DeliveryJob:
        """Create a new delivery job."""
        # Check rate limit
        allowed, retry_after = await check_organization_rate_limit(str(organization_id), limit_per_minute=30)
        if not allowed:
            from fastapi import HTTPException, status
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")

        # Generate reference number
        ref_number = f"DJ-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid4().hex[:8].upper()}"

        job = DeliveryJob(
            organization_id=organization_id,
            created_by_id=created_by_id,
            name=request.name,
            description=request.description,
            reference_number=ref_number,
            source_filename=request.source_filename,
            scheduled_for=request.scheduled_for,
        )
        self.db.add(job)
        await self.db.flush()

        # Add items if provided
        if request.items:
            items = []
            for i, item_data in enumerate(request.items):
                item = DeliveryItem(
                    job_id=job.id,
                    sequence_number=i + 1,
                    recipient_name=item_data.recipient_name,
                    recipient_phone=item_data.recipient_phone,
                    raw_address=item_data.raw_address,
                    landmarks=item_data.landmarks,
                    notes=item_data.notes,
                )
                items.append(item)
            self.db.add_all(items)
            job.total_items = len(items)

        await self.db.commit()
        await self.db.refresh(job)

        logger.info("delivery_job_created", job_id=str(job.id), org_id=str(organization_id), items=job.total_items)
        return job

    async def list_jobs(
        self,
        organization_id: UUID,
        page: int = 1,
        page_size: int = 20,
        status_filter: Optional[JobStatus] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """List delivery jobs with pagination."""
        query = select(DeliveryJob).where(DeliveryJob.organization_id == organization_id)

        if status_filter:
            query = query.where(DeliveryJob.status == status_filter)
        if date_from:
            query = query.where(DeliveryJob.created_at >= date_from)
        if date_to:
            query = query.where(DeliveryJob.created_at <= date_to)

        query = query.order_by(DeliveryJob.created_at.desc())

        # Count
        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.scalar(count_query)

        # Paginate
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        result = await self.db.execute(query)
        jobs = result.scalars().all()

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": jobs,
        }

    async def get_job(self, job_id: UUID, organization_id: UUID) -> Optional[DeliveryJob]:
        """Get delivery job with items."""
        result = await self.db.execute(
            select(DeliveryJob)
            .options(selectinload(DeliveryJob.items))
            .where(DeliveryJob.id == job_id, DeliveryJob.organization_id == organization_id)
        )
        return result.scalar_one_or_none()

    async def add_items(
        self,
        job_id: UUID,
        organization_id: UUID,
        items: List[DeliveryItemCreate],
    ) -> List[DeliveryItem]:
        """Add items to a delivery job."""
        job = await self.get_job(job_id, organization_id)
        if not job:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Job not found")

        if job.status != JobStatus.PENDING:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Can only add items to pending jobs")

        # Get next sequence number
        max_seq_result = await self.db.execute(
            select(func.max(DeliveryItem.sequence_number)).where(DeliveryItem.job_id == job_id)
        )
        next_seq = (max_seq_result.scalar() or 0) + 1

        new_items = []
        for i, item_data in enumerate(items):
            item = DeliveryItem(
                job_id=job_id,
                sequence_number=next_seq + i,
                recipient_name=item_data.recipient_name,
                recipient_phone=item_data.recipient_phone,
                raw_address=item_data.raw_address,
                landmarks=item_data.landmarks,
                notes=item_data.notes,
            )
            new_items.append(item)

        self.db.add_all(new_items)
        job.total_items += len(new_items)
        await self.db.commit()

        for item in new_items:
            await self.db.refresh(item)

        return new_items

    async def validate_job(self, job_id: UUID, organization_id: UUID) -> DeliveryJob:
        """Validate all addresses in a delivery job."""
        job = await self.get_job(job_id, organization_id)
        if not job:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Job not found")

        if not job.items:
            return job

        # Prepare addresses for validation
        addresses_data = []
        for item in job.items:
            if item.status == ItemStatus.PENDING:
                addresses_data.append({
                    "address": item.raw_address,
                    "landmarks": item.landmarks or "",
                })

        if addresses_data:
            # Bulk validate
            results = await nipost_client.bulk_validate(addresses_data)

            # Update items with results
            validated = 0
            failed = 0
            for item, result in zip(job.items, results):
                if result.status.value in ("valid", "partial"):
                    item.status = ItemStatus.VALIDATED
                    item.postcode = result.postcode
                    item.postcode_level = result.postcode_level
                    item.formatted_address = result.formatted_address
                    item.latitude = result.latitude
                    item.longitude = result.longitude
                    item.state = result.state
                    item.lga = result.lga
                    item.ward = result.ward
                    item.confidence_score = result.confidence_score
                    validated += 1
                else:
                    item.status = ItemStatus.INVALID
                    failed += 1

            job.validated_items = validated
            job.failed_items = failed
            job.status = JobStatus.READY_FOR_DISPATCH if validated > 0 else JobStatus.PENDING

            await self.db.commit()

        logger.info("job_validated", job_id=str(job_id), validated=validated, failed=failed)
        return job

    async def optimize_route(
        self,
        job_id: UUID,
        organization_id: UUID,
        request: RouteOptimizationRequest,
    ) -> RouteOptimizationResponse:
        """Optimize delivery route using OR-Tools."""
        job = await self.get_job(job_id, organization_id)
        if not job:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Job not found")

        # Queue async optimization task
        task = optimize_delivery_route.delay(str(job_id), str(organization_id), request.vehicle_capacity)

        # Return immediate response with task ID
        return RouteOptimizationResponse(
            job_id=job_id,
            task_id=task.id,
            status="queued",
            message="Route optimization queued. Check back for results.",
        )

    async def dispatch_job(self, job_id: UUID, organization_id: UUID) -> DeliveryJob:
        """Mark job as dispatched."""
        job = await self.get_job(job_id, organization_id)
        if not job:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Job not found")

        job.status = JobStatus.DISPATCHED
        job.dispatched_at = datetime.now(UTC)
        await self.db.commit()
        await self.db.refresh(job)

        logger.info("job_dispatched", job_id=str(job_id))
        return job

    async def complete_job(self, job_id: UUID, organization_id: UUID) -> DeliveryJob:
        """Mark job as completed."""
        job = await self.get_job(job_id, organization_id)
        if not job:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Job not found")

        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.now(UTC)
        await self.db.commit()
        await self.db.refresh(job)

        logger.info("job_completed", job_id=str(job_id))
        return job

    # -------------------------------------------------------------------------
    # Delivery Items
    # -------------------------------------------------------------------------

    async def mark_delivered(
        self,
        item_id: UUID,
        organization_id: UUID,
        latitude: float,
        longitude: float,
        notes: Optional[str] = None,
        proof_url: Optional[str] = None,
    ) -> DeliveryItem:
        """Mark item as delivered."""
        result = await self.db.execute(
            select(DeliveryItem)
            .join(DeliveryJob)
            .where(DeliveryItem.id == item_id, DeliveryJob.organization_id == organization_id)
        )
        item = result.scalar_one_or_none()

        if not item:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Item not found")

        item.status = ItemStatus.DELIVERED
        item.delivered_at = datetime.now(UTC)
        item.delivery_latitude = latitude
        item.delivery_longitude = longitude
        item.delivery_notes = notes
        item.proof_of_delivery_url = proof_url

        # Update job counters
        job = item.job
        delivered_count = sum(1 for i in job.items if i.status == ItemStatus.DELIVERED)
        if delivered_count == job.total_items:
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now(UTC)

        await self.db.commit()
        await self.db.refresh(item)

        # Queue notification
        notify_delivery_status.delay(str(item_id), "delivered", str(organization_id))

        logger.info("item_delivered", item_id=str(item_id))
        return item

    async def mark_failed(
        self,
        item_id: UUID,
        organization_id: UUID,
        reason: FailureReason,
        reason_details: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
    ) -> DeliveryItem:
        """Mark item as failed."""
        result = await self.db.execute(
            select(DeliveryItem)
            .join(DeliveryJob)
            .where(DeliveryItem.id == item_id, DeliveryJob.organization_id == organization_id)
        )
        item = result.scalar_one_or_none()

        if not item:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Item not found")

        item.status = ItemStatus.FAILED

        # Create failed delivery record
        failed = FailedDelivery(
            job_id=item.job_id,
            item_id=item.id,
            organization_id=organization_id,
            reason=reason,
            reason_details=reason_details,
            failure_latitude=latitude,
            failure_longitude=longitude,
            failure_postcode=item.postcode,
            next_retry_at=datetime.now(UTC),  # Immediate retry eligible
        )
        self.db.add(failed)

        job = item.job
        job.failed_items += 1

        await self.db.commit()
        await self.db.refresh(item)

        logger.info("item_failed", item_id=str(item_id), reason=reason.value)
        return item

    # -------------------------------------------------------------------------
    # Failed Deliveries
    # -------------------------------------------------------------------------

    async def list_failed(
        self,
        organization_id: UUID,
        page: int = 1,
        page_size: int = 20,
        resolved: Optional[bool] = None,
    ) -> List[FailedDelivery]:
        """List failed deliveries."""
        query = select(FailedDelivery).where(FailedDelivery.organization_id == organization_id)

        if resolved is not None:
            query = query.where(FailedDelivery.resolved == resolved)

        query = query.order_by(FailedDelivery.created_at.desc())
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        result = await self.db.execute(query)
        return result.scalars().all()

    async def retry_failed(self, failed_id: UUID, organization_id: UUID) -> FailedDelivery:
        """Retry a failed delivery."""
        result = await self.db.execute(
            select(FailedDelivery).where(
                FailedDelivery.id == failed_id,
                FailedDelivery.organization_id == organization_id
            )
        )
        failed = result.scalar_one_or_none()

        if not failed:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Failed delivery not found")

        if failed.resolved:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Already resolved")

        # Reset item status to pending for retry
        item_result = await self.db.execute(select(DeliveryItem).where(DeliveryItem.id == failed.item_id))
        item = item_result.scalar_one_or_none()
        if item:
            item.status = ItemStatus.PENDING

        failed.retry_count += 1
        failed.last_retry_at = datetime.now(UTC)
        failed.next_retry_at = datetime.now(UTC)  # Schedule immediate retry

        await self.db.commit()
        await self.db.refresh(failed)

        logger.info("failed_delivery_retried", failed_id=str(failed_id))
        return failed

    async def retry_due_deliveries(self) -> Dict[str, int]:
        """Retry all failed deliveries due for retry."""
        from sqlalchemy import and_
        result = await self.db.execute(
            select(FailedDelivery).where(
                and_(
                    FailedDelivery.resolved == False,
                    FailedDelivery.next_retry_at <= datetime.now(UTC),
                    FailedDelivery.retry_count < FailedDelivery.max_retries,
                )
            )
        )
        due = result.scalars().all()

        retried = 0
        for failed in due:
            try:
                await self.retry_failed(failed.id, failed.organization_id)
                retried += 1
            except Exception as e:
                logger.error("retry_failed", failed_id=str(failed.id), error=str(e))

        return {"retried": retried, "total_due": len(due)}