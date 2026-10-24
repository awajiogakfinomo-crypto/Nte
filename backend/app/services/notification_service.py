"""Notification service for webhooks, emails, and reports."""
from typing import List, Dict, Any, Optional
from uuid import UUID
from datetime import datetime, UTC, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.models.organization import Organization, OrganizationMember
from app.models.usage import UsageRecord, UsageType
from app.models.kyc import VerificationRequest
from app.core.cache import cache_manager
from app.tasks.notification_tasks import send_webhook, send_email

logger = structlog.get_logger()


class NotificationService:
    """Service for sending notifications and generating reports."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def send_delivery_notification(
        self,
        item_id: UUID,
        status: str,
        organization_id: UUID,
    ) -> None:
        """Send delivery status notification via webhook."""
        # Get organization webhook config
        org_result = await self.db.execute(
            select(Organization).where(Organization.id == organization_id)
        )
        org = org_result.scalar_one_or_none()

        if not org or not org.webhook_url:
            return

        # Get item details
        from app.models.logistics import DeliveryItem, DeliveryJob
        item_result = await self.db.execute(
            select(DeliveryItem)
            .join(DeliveryJob)
            .where(DeliveryItem.id == item_id)
        )
        item = item_result.scalar_one_or_none()

        if not item:
            return

        payload = {
            "event": f"delivery.{status}",
            "timestamp": datetime.now(UTC).isoformat(),
            "delivery": {
                "item_id": str(item.id),
                "job_id": str(item.job_id),
                "reference_number": item.job.reference_number,
                "recipient_name": item.recipient_name,
                "recipient_phone": item.recipient_phone,
                "address": item.formatted_address or item.raw_address,
                "postcode": item.postcode,
                "status": status,
                "delivered_at": item.delivered_at.isoformat() if item.delivered_at else None,
                "coordinates": {
                    "latitude": item.delivery_latitude,
                    "longitude": item.delivery_longitude,
                } if item.delivery_latitude and item.delivery_longitude else None,
            }
        }

        send_webhook.delay(org.webhook_url, payload, org.webhook_secret, str(organization_id))

    async def generate_daily_reports(self) -> Dict[str, Any]:
        """Generate daily usage reports for all active organizations."""
        from app.models.organization import OrganizationStatus

        orgs_result = await self.db.execute(
            select(Organization).where(Organization.status == OrganizationStatus.ACTIVE)
        )
        organizations = orgs_result.scalars().all()

        generated = 0
        for org in organizations:
            try:
                await self._generate_org_report(org)
                generated += 1
            except Exception as e:
                logger.error("org_report_failed", org_id=str(org.id), error=str(e))

        return {"count": generated, "total_orgs": len(organizations)}

    async def _generate_org_report(self, org: Organization) -> None:
        """Generate report for a single organization."""
        # Yesterday's date
        yesterday = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        today = yesterday + timedelta(days=1)

        # Aggregate usage
        usage_result = await self.db.execute(
            select(
                UsageRecord.usage_type,
                func.sum(UsageRecord.request_count).label("requests"),
                func.sum(UsageRecord.cost_kobo).label("cost"),
            )
            .where(
                UsageRecord.organization_id == org.id,
                UsageRecord.created_at >= yesterday,
                UsageRecord.created_at < today,
            )
            .group_by(UsageRecord.usage_type)
        )

        usage_by_type = {}
        total_requests = 0
        total_cost = 0

        for row in usage_result:
            usage_by_type[row.usage_type.value] = {
                "requests": row.requests or 0,
                "cost_kobo": row.cost or 0,
            }
            total_requests += row.requests or 0
            total_cost += row.cost or 0

        # Verification stats
        vr_result = await self.db.execute(
            select(
                func.count(VerificationRequest.id).label("total"),
                func.sum(func.case((VerificationRequest.status == "verified", 1), else_=0)).label("verified"),
            )
            .where(
                VerificationRequest.organization_id == org.id,
                VerificationRequest.created_at >= yesterday,
                VerificationRequest.created_at < today,
            )
        )
        vr_row = vr_result.one()

        report = {
            "organization": {"id": str(org.id), "name": org.name},
            "date": yesterday.date().isoformat(),
            "usage": {
                "total_requests": total_requests,
                "total_cost_kobo": total_cost,
                "by_type": usage_by_type,
            },
            "verifications": {
                "total": vr_row.total or 0,
                "verified": vr_row.verified or 0,
            },
        }

        # Cache report for dashboard
        await cache_manager.set(f"daily_report:{org.id}:{yesterday.date()}", report, ttl=86400 * 7)

        # Email to org admins (if configured)
        # admins = await self._get_org_admins(org.id)
        # for admin in admins:
        #     send_email.delay(admin.email, f"Daily Report - {org.name}", self._format_report_email(report))

        logger.info("org_report_generated", org_id=str(org.id), date=yesterday.date().isoformat())

    async def get_daily_report(self, organization_id: UUID, date: datetime) -> Optional[Dict[str, Any]]:
        """Get cached daily report."""
        return await cache_manager.get(f"daily_report:{organization_id}:{date.date()}")