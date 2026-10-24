"""Usage analytics and billing API routes."""
from typing import Optional
from uuid import UUID
from datetime import datetime, timedelta, UTC

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.api.deps import (
    get_current_user,
    get_db,
    get_organization_id,
    get_pagination,
)
from app.models.usage import UsageRecord, UsageType
from app.models.organization import Organization, OrganizationPlan
from app.schemas.usage import (
    UsageSummary,
    UsageRecordResponse,
    UsageListResponse,
    BillingSummary,
    PlanLimits,
)

router = APIRouter()
logger = structlog.get_logger()


# Plan limits configuration
PLAN_LIMITS = {
    OrganizationPlan.FREE: {"monthly_api_calls": 10000, "rate_limit_per_minute": 30, "rate_limit_per_day": 1000},
    OrganizationPlan.STARTER: {"monthly_api_calls": 100000, "rate_limit_per_minute": 60, "rate_limit_per_day": 10000},
    OrganizationPlan.PROFESSIONAL: {"monthly_api_calls": 1000000, "rate_limit_per_minute": 300, "rate_limit_per_day": 100000},
    OrganizationPlan.ENTERPRISE: {"monthly_api_calls": -1, "rate_limit_per_minute": 1000, "rate_limit_per_day": 1000000},
}


@router.get("/summary", response_model=UsageSummary)
async def get_usage_summary(
    days: int = Query(default=30, ge=1, le=365),
    current_user = Depends(get_current_user),
    organization_id: UUID = Depends(get_organization_id),
    db: AsyncSession = Depends(get_db),
):
    """Get usage summary for the organization."""
    date_from = datetime.now(UTC) - timedelta(days=days)
    date_to = datetime.now(UTC)

    # Aggregate by usage type
    query = select(
        UsageRecord.usage_type,
        func.sum(UsageRecord.request_count).label("total_requests"),
        func.sum(UsageRecord.items_processed).label("total_items"),
        func.sum(UsageRecord.cost_kobo).label("total_cost_kobo"),
        func.avg(UsageRecord.response_time_ms).label("avg_response_time"),
    ).where(
        UsageRecord.organization_id == organization_id,
        UsageRecord.created_at >= date_from,
        UsageRecord.created_at <= date_to,
    ).group_by(UsageRecord.usage_type)

    result = await db.execute(query)
    by_type = {}
    total_requests = 0
    total_cost_kobo = 0

    for row in result:
        by_type[row.usage_type.value] = {
            "requests": row.total_requests or 0,
            "items": row.total_items or 0,
            "cost_kobo": row.total_cost_kobo or 0,
            "avg_response_time_ms": float(row.avg_response_time) if row.avg_response_time else 0,
        }
        total_requests += row.total_requests or 0
        total_cost_kobo += row.total_cost_kobo or 0

    # Get organization for plan info
    org_result = await db.execute(select(Organization).where(Organization.id == organization_id))
    org = org_result.scalar_one_or_none()

    limits = PLAN_LIMITS.get(org.plan if org else OrganizationPlan.FREE, PLAN_LIMITS[OrganizationPlan.FREE])
    monthly_used = org.monthly_validations_used if org else 0
    monthly_limit = limits["monthly_api_calls"]

    return UsageSummary(
        period_days=days,
        total_requests=total_requests,
        total_cost_kobo=total_cost_kobo,
        total_cost_ngn=total_cost_kobo / 100,
        by_type=by_type,
        monthly_limit=monthly_limit,
        monthly_used=monthly_used,
        monthly_remaining=max(0, monthly_limit - monthly_used) if monthly_limit > 0 else -1,
        plan=org.plan.value if org else OrganizationPlan.FREE.value,
    )


@router.get("/records", response_model=UsageListResponse)
async def list_usage_records(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    usage_type: Optional[UsageType] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    api_key_id: Optional[UUID] = Query(None),
    current_user = Depends(get_current_user),
    organization_id: UUID = Depends(get_organization_id),
    db: AsyncSession = Depends(get_db),
):
    """List usage records with pagination and filters."""
    query = select(UsageRecord).where(UsageRecord.organization_id == organization_id)

    if usage_type:
        query = query.where(UsageRecord.usage_type == usage_type)
    if date_from:
        query = query.where(UsageRecord.created_at >= date_from)
    if date_to:
        query = query.where(UsageRecord.created_at <= date_to)
    if api_key_id:
        query = query.where(UsageRecord.api_key_id == api_key_id)

    query = query.order_by(UsageRecord.created_at.desc())

    # Count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)

    # Paginate
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    result = await db.execute(query)
    records = result.scalars().all()

    return UsageListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[
            UsageRecordResponse(
                id=r.id,
                usage_type=r.usage_type,
                endpoint=r.endpoint,
                method=r.method,
                status_code=r.status_code,
                request_count=r.request_count,
                items_processed=r.items_processed,
                response_time_ms=r.response_time_ms,
                cost_kobo=r.cost_kobo,
                created_at=r.created_at,
            )
            for r in records
        ],
    )


@router.get("/billing", response_model=BillingSummary)
async def get_billing_summary(
    current_user = Depends(get_current_user),
    organization_id: UUID = Depends(get_organization_id),
    db: AsyncSession = Depends(get_db),
):
    """Get billing summary for current period."""
    # Current month
    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month = (month_start + timedelta(days=32)).replace(day=1)

    query = select(
        func.sum(UsageRecord.cost_kobo).label("total_cost"),
        func.sum(UsageRecord.request_count).label("total_requests"),
    ).where(
        UsageRecord.organization_id == organization_id,
        UsageRecord.created_at >= month_start,
        UsageRecord.created_at < next_month,
    )
    result = await db.execute(query)
    row = result.one()

    total_cost_kobo = row.total_cost or 0
    total_requests = row.total_requests or 0

    # Get org and plan
    org_result = await db.execute(select(Organization).where(Organization.id == organization_id))
    org = org_result.scalar_one_or_none()

    limits = PLAN_LIMITS.get(org.plan if org else OrganizationPlan.FREE, PLAN_LIMITS[OrganizationPlan.FREE])

    return BillingSummary(
        period_start=month_start,
        period_end=next_month - timedelta(seconds=1),
        plan=org.plan.value if org else OrganizationPlan.FREE.value,
        monthly_limit=limits["monthly_api_calls"],
        requests_this_month=total_requests,
        cost_this_month_kobo=total_cost_kobo,
        cost_this_month_ngn=total_cost_kobo / 100,
        overage_requests=max(0, total_requests - limits["monthly_api_calls"]) if limits["monthly_api_calls"] > 0 else 0,
        overage_cost_kobo=0,  # Would calculate based on overage pricing
    )


@router.get("/limits", response_model=PlanLimits)
async def get_plan_limits(
    current_user = Depends(get_current_user),
    organization_id: UUID = Depends(get_organization_id),
    db: AsyncSession = Depends(get_db),
):
    """Get current plan limits and usage."""
    org_result = await db.execute(select(Organization).where(Organization.id == organization_id))
    org = org_result.scalar_one_or_none()

    plan = org.plan if org else OrganizationPlan.FREE
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS[OrganizationPlan.FREE])

    return PlanLimits(
        plan=plan.value,
        monthly_api_calls=limits["monthly_api_calls"],
        rate_limit_per_minute=limits["rate_limit_per_minute"],
        rate_limit_per_day=limits["rate_limit_per_day"],
        current_usage=org.monthly_validations_used if org else 0,
        features={
            "bulk_validation": plan in [OrganizationPlan.PROFESSIONAL, OrganizationPlan.ENTERPRISE],
            "logistics": plan in [OrganizationPlan.STARTER, OrganizationPlan.PROFESSIONAL, OrganizationPlan.ENTERPRISE],
            "kyc_verification": plan in [OrganizationPlan.PROFESSIONAL, OrganizationPlan.ENTERPRISE],
            "webhooks": plan in [OrganizationPlan.PROFESSIONAL, OrganizationPlan.ENTERPRISE],
            "dedicated_support": plan == OrganizationPlan.ENTERPRISE,
            "sla": plan == OrganizationPlan.ENTERPRISE,
        },
    )