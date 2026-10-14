import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.jobs.appointment_reminders import send_appointment_reminders
from app.jobs.no_show_job import mark_no_show_appointments
from app.jobs.follow_up_emails import send_follow_up_emails

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def start_scheduler():
    if scheduler.running:
        return

    scheduler.add_job(
        send_appointment_reminders,
        trigger="interval",
        hours=1,
        id="appointment_reminders",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.add_job(
        mark_no_show_appointments,
        trigger="interval",
        minutes=15,
        id="no_show_job",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.add_job(
        send_follow_up_emails,
        trigger="cron",
        hour=9,
        minute=0,
        id="follow_up_emails",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.start()
    logger.info("Background job scheduler started")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Background job scheduler stopped")

