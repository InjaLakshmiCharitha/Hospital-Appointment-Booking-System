
from datetime import date
import logging

from app.database import SessionLocal
from app.models.models import (
    Appointment,
    AppointmentStatus,
    Consultation,
    User,
)
from app.services.email_service import send_email

logger = logging.getLogger(__name__)


async def send_follow_up_emails():
    db = SessionLocal()

    try:
        consultations = (
            db.query(Consultation)
            .join(
                Appointment,
                Consultation.appointment_id == Appointment.id,
            )
            .filter(
                Appointment.status == AppointmentStatus.COMPLETED,
                Consultation.follow_up_date == date.today(),
                Consultation.follow_up_email_sent.is_(False),
            )
            .all()
        )

        sent_count = 0

        for consultation in consultations:
            appointment = (
                db.query(Appointment)
                .filter(
                    Appointment.id == consultation.appointment_id
                )
                .first()
            )

            if appointment is None:
                continue

            patient = (
                db.query(User)
                .filter(User.id == appointment.patient_id)
                .first()
            )

            if patient is None or not patient.email:
                continue

            try:
                await send_email(
                    to_email=patient.email,
                    subject="Hospital Consultation Follow-up",
                    body=(
                        f"Hello {patient.full_name},\n\n"
                        "This is a reminder about your consultation "
                        "follow-up.\n\n"
                        f"Appointment Number: {appointment.appointment_number}\n"
                        f"Follow-up Date: {consultation.follow_up_date}\n\n"
                        "Please contact the hospital to arrange your "
                        "follow-up appointment if needed.\n\nThank you."
                    ),
                )

                consultation.follow_up_email_sent = True
                db.commit()
                sent_count += 1

            except Exception:
                db.rollback()
                logger.exception(
                    "Follow-up email failed for consultation %s",
                    consultation.id,
                )

        logger.info("Follow-up job finished: %s emails sent", sent_count)

    except Exception:
        db.rollback()
        logger.exception("Follow-up email job failed")

    finally:
        db.close()
