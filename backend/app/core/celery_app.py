"""Celery configuration for background tasks."""
from celery import Celery
from celery.schedules import crontab
from kombu import Queue

from app.core.config import settings

# Create Celery app
celery_app = Celery(
    "nte",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.tasks.validation_tasks",
        "app.tasks.logistics_tasks",
        "app.tasks.notification_tasks",
    ],
)

# Configuration
celery_app.conf.update(
    # Serialization
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Timezone
    timezone="UTC",
    enable_utc=True,

    # Task routing
    task_routes={
        "app.tasks.validation_tasks.*": {"queue": "validation"},
        "app.tasks.logistics_tasks.*": {"queue": "logistics"},
        "app.tasks.notification_tasks.*": {"queue": "notifications"},
    },

    # Queue configuration
    task_create_missing_queues=True,
    task_queues=(
        Queue("default", routing_key="default"),
        Queue("validation", routing_key="validation"),
        Queue("logistics", routing_key="logistics"),
        Queue("notifications", routing_key="notifications"),
    ),

    # Worker configuration
    worker_prefetch_multiplier=4,
    worker_max_tasks_per_child=1000,
    worker_disable_rate_limits=False,

    # Task execution
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,

    # Result backend
    result_expires=3600,
    result_compression="gzip",

    # Monitoring
    worker_send_task_events=True,
    task_send_sent_event=True,

    # Beat schedule (periodic tasks)
    beat_schedule={
        "reset-monthly-usage": {
            "task": "app.tasks.maintenance_tasks.reset_monthly_usage",
            "schedule": crontab(day_of_month=1, hour=0, minute=0),
        },
        "cleanup-expired-tokens": {
            "task": "app.tasks.maintenance_tasks.cleanup_expired_tokens",
            "schedule": crontab(hour=3, minute=0),
        },
        "retry-failed-deliveries": {
            "task": "app.tasks.logistics_tasks.retry_failed_deliveries",
            "schedule": crontab(minute="*/15"),
        },
        "generate-usage-reports": {
            "task": "app.tasks.notification_tasks.generate_daily_usage_reports",
            "schedule": crontab(hour=1, minute=0),
        },
    },

    # Task retry policy
    task_autoretry_for=(Exception,),
    task_retry_backoff=True,
    task_retry_backoff_max=600,
    task_retry_jitter=True,
)

# Auto-discover tasks
celery_app.autodiscover_tasks(["app.tasks"])


@celery_app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Debug task."""
    print(f"Request: {self.request!r}")