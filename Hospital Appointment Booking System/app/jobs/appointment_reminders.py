
from datetime import datetime, timedelta
import logging

from app.database import SessionLocal
from app.models.models import Appointment, AppointmentStatus, User
from app.services.email_service import send_email
from app.services.notification_service import send_user_notification

logger = logging.getLogger(__name__)


async def send_appointment_reminders():
    db = SessionLocal()

    try:
        now = datetime.now()

        # The scheduler runs hourly, so check the next one-hour window
        # around the 24-hour reminder point.
        reminder_start = now + timedelta(hours=23)
        reminder_end = now + timedelta(hours=24)

        appointments = (
            db.query(Appointment)
            .filter(
                Appointment.appointment_date >= reminder_start.date(),
                Appointment.appointment_date <= reminder_end.date(),
                Appointment.status == AppointmentStatus.BOOKED,
                Appointment.reminder_sent.is_(False),
            )
            .all()
        )

        sent_count = 0

        for appointment in appointments:
            appointment_datetime = datetime.combine(
                appointment.appointment_date,
                appointment.slot_time,
            )

            if not reminder_start <= appointment_datetime < reminder_end:
                continue

            patient = (
                db.query(User)
                .filter(User.id == appointment.patient_id)
                .first()
            )

            if not patient or not patient.email:
                continue

            try:
                await send_email(
                    to_email=patient.email,
                    subject="Hospital Appointment Reminder",
                    body=(
                        f"Hello {patient.full_name},\n\n"
                        "This is a reminder for your upcoming "
                        "hospital appointment.\n\n"
                        f"Appointment Number: {appointment.appointment_number}\n"
                        f"Appointment Date: {appointment.appointment_date}\n"
                        f"Appointment Time: {appointment.slot_time}\n\n"
                        "Please arrive on time.\n\nThank you."
                    ),
                )

                await send_user_notification(
                    patient.id,
                    {
                        "type": "appointment_reminder",
                        "appointment_id": appointment.id,
                        "appointment_number": appointment.appointment_number,
                        "message": (
                            "Your appointment is approximately "
                            "24 hours away."
                        ),
                    },
                )

                appointment.reminder_sent = True
                db.commit()
                sent_count += 1

            except Exception:
                db.rollback()
                logger.exception(
                    "Failed to send reminder for appointment %s",
                    appointment.id,
                )

        logger.info("Appointment reminder job finished: %s emails sent", sent_count)

    except Exception:
        db.rollback()
        logger.exception("Appointment reminder job failed")

    finally:
        db.close()


