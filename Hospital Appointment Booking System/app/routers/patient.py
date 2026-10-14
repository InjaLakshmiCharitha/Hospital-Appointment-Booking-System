
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.models import (
    Appointment,
    AppointmentStatus,
    Consultation,
    UploadedFile,
    UserRole,
)
from app.schemas.patient import PatientHistoryItem

router = APIRouter(tags=["Patient History"])


@router.get("/patients/me/history", response_model=list[PatientHistoryItem])
def get_patient_history(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    role = current_user.role.value

    if role != UserRole.PATIENT.value:
        raise HTTPException(
            status_code=403,
            detail="Only patients can view their appointment history",
        )

    appointments = (
        db.query(Appointment)
        .filter(
            Appointment.patient_id == current_user.id,
            or_(
                Appointment.appointment_date < date.today(),
                Appointment.status.in_(
                    [
                        AppointmentStatus.COMPLETED,
                        AppointmentStatus.CANCELLED,
                        AppointmentStatus.NO_SHOW,
                    ]
                ),
            ),
        )
        .order_by(
            Appointment.appointment_date.desc(),
            Appointment.slot_time.desc(),
        )
        .all()
    )

    history = []

    for appointment in appointments:
        consultation = (
            db.query(Consultation)
            .filter(Consultation.appointment_id == appointment.id)
            .first()
        )

        uploaded_files = (
            db.query(UploadedFile)
            .filter(UploadedFile.appointment_id == appointment.id)
            .all()
        )

        history.append(
            PatientHistoryItem(
                appointment_id=appointment.id,
                appointment_number=appointment.appointment_number,
                doctor_id=appointment.doctor_id,
                appointment_date=appointment.appointment_date,
                slot_time=appointment.slot_time,
                status=appointment.status.value,
                diagnosis=consultation.diagnosis if consultation else None,
                files=uploaded_files,
            )
        )

    return history
