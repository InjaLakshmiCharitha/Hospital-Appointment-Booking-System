
from datetime import datetime, timedelta
import logging

from app.database import SessionLocal
from app.models.models import (
    Appointment,
    AppointmentHistory,
    AppointmentStatus,
)
from app.routers.queue import broadcast_queue_update

logger = logging.getLogger(__name__)


async def mark_no_show_appointments():
    db = SessionLocal()

    try:
        now = datetime.now()
        cutoff = now - timedelta(minutes=30)

        appointments = (
            db.query(Appointment)
            .filter(
                Appointment.status == AppointmentStatus.BOOKED,
                Appointment.appointment_date <= cutoff.date(),
            )
            .with_for_update()
            .all()
        )

        changed_queues = set()
        updated_count = 0

        for appointment in appointments:
            appointment_datetime = datetime.combine(
                appointment.appointment_date,
                appointment.slot_time,
            )

            # Mark no-show only after the slot has passed by 30 minutes.
            if appointment_datetime > cutoff:
                continue

            old_status = appointment.status.value

            appointment.status = AppointmentStatus.NO_SHOW

            db.add(
                AppointmentHistory(
                    appointment_id=appointment.id,
                    old_status=old_status,
                    new_status=AppointmentStatus.NO_SHOW.value,
                    changed_by=None,
                )
            )

            changed_queues.add(
                (appointment.doctor_id, appointment.appointment_date)
            )
            updated_count += 1

        db.commit()

        for doctor_id, appointment_date in changed_queues:
            try:
                await broadcast_queue_update(
                    db, doctor_id, appointment_date
                )
            except Exception:
                logger.exception(
                    "Queue update failed for doctor %s",
                    doctor_id,
                )

        logger.info(
            "No-show job finished: %s appointments updated",
            updated_count,
        )

    except Exception:
        db.rollback()
        logger.exception("No-show job failed")

    finally:
        db.close()

