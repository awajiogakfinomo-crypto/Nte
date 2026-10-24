"""Celery tasks for notifications and reports."""
from celery import shared_task
from uuid import UUID
import structlog

logger = structlog.get_logger()


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_webhook(self, url: str, payload: dict, secret: str = None, organization_id: str = None):
    """Send webhook notification with retry."""
    import httpx
    import hmac
    import hashlib
    import json

    try:
        headers = {"Content-Type": "application/json"}
        if secret:
            signature = hmac.new(secret.encode(), json.dumps(payload).encode(), hashlib.sha256).hexdigest()
            headers["X-Nte-Signature"] = signature

        response = httpx.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()

        logger.info("webhook_sent", url=url, status=response.status_code)
        return {"sent": True, "status": response.status_code}

    except Exception as exc:
        logger.warning("webhook_failed", url=url, error=str(exc))
        raise self.retry(exc=exc)


@shared_task(bind=True)
def send_email(self, to: str, subject: str, body: str, organization_id: str = None):
    """Send email notification."""
    # TODO: Integrate with email provider (SendGrid, AWS SES, etc.)
    logger.info("email_sent", to=to, subject=subject)
    return {"sent": True}


@shared_task(bind=True)
def generate_daily_usage_reports(self):
    """Generate daily usage reports for all organizations."""
    from app.core.database import get_db_context
    from app.services.notification_service import NotificationService

    try:
        import asyncio

        async def _generate():
            async with get_db_context() as db:
                svc = NotificationService(db)
                return await svc.generate_daily_reports()

        result = asyncio.run(_generate())

        logger.info("daily_reports_generated", count=result.get("count", 0))
        return result

    except Exception as exc:
        logger.error("daily_reports_failed", error=str(exc))
        raise self.retry(exc=exc)


@shared_task(bind=True)
def send_verification_webhook(self, request_id: str, organization_id: str, callback_url: str, callback_secret: str):
    """Send verification result to callback URL."""
    from app.core.database import get_db_context
    from app.models.kyc import VerificationRequest, VerificationResult

    try:
        import asyncio

        async def _send():
            async with get_db_context() as db:
                from sqlalchemy import select
                result = await db.execute(
                    select(VerificationRequest)
                    .options(selectinload(VerificationRequest.result))
                    .where(VerificationRequest.id == UUID(request_id))
                )
                vr = result.scalar_one_or_none()

                if vr and vr.result:
                    payload = {
                        "external_reference": vr.external_reference,
                        "status": vr.status.value,
                        "verification_type": vr.verification_type.value,
                        "result": {
                            "address_match": vr.result.address_match,
                            "address_confidence": float(vr.result.address_confidence),
                            "postcode_verified": vr.result.postcode_verified,
                            "risk_score": vr.result.risk_score,
                        } if vr.result else None,
                    }
                    return await send_webhook.delay(callback_url, payload, callback_secret, organization_id)

        asyncio.run(_send())
        return {"webhook_queued": True}

    except Exception as exc:
        logger.error("verification_webhook_failed", request_id=request_id, error=str(exc))
        return {"webhook_queued": False, "error": str(exc)}