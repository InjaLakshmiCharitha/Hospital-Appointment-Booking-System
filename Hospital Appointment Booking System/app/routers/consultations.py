
from datetime import date
from io import BytesIO
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from fastapi.responses import StreamingResponse
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.models import (
    Appointment,
    AppointmentHistory,
    AppointmentStatus,
    Consultation,
    Doctor,
    UserRole,
)
from app.schemas.consultation import (
    ConsultationCreate,
    ConsultationResponse,
)


router = APIRouter(
    prefix="/appointments",
    tags=["Consultations & Prescriptions"],
)


def role_value(user):
    return user.role.value if hasattr(user.role, "value") else user.role


async def broadcast_queue_update(
    db: Session,
    doctor_id: int,
    queue_date: date,
):
    from app.routers.queue import (
        queue_data,
    )
    from app.websockets.manager import manager

    queue = queue_data(db, doctor_id, queue_date)

    await manager.broadcast(
        f"queue:{doctor_id}",
        {
            "type": "queue_update",
            "doctor_id": doctor_id,
            "queue": queue,
        },
    )


@router.post(
    "/{appointment_id}/consultation",
    response_model=ConsultationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_consultation(
    appointment_id: int,
    data: ConsultationCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if role_value(current_user) != UserRole.DOCTOR.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only doctors can create consultations",
        )

    doctor = (
        db.query(Doctor)
        .filter(Doctor.user_id == current_user.id)
        .first()
    )

    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor profile not found",
        )

    appointment = (
        db.query(Appointment)
        .filter(Appointment.id == appointment_id)
        .with_for_update()
        .first()
    )

    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found",
        )

    if appointment.doctor_id != doctor.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only consult your own patients",
        )

    if appointment.status != AppointmentStatus.IN_CONSULTATION:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Appointment must be In Consultation",
        )

    existing = (
        db.query(Consultation)
        .filter(Consultation.appointment_id == appointment_id)
        .first()
    )

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Consultation already exists",
        )

    try:
        consultation = Consultation(
            appointment_id=appointment_id,
            symptoms=data.symptoms,
            diagnosis=data.diagnosis,
            prescription=data.prescription,
            advice=data.advice,
            follow_up_date=data.follow_up_date,
        )

        old_status = appointment.status
        appointment.status = AppointmentStatus.COMPLETED

        db.add(consultation)
        db.add(
            AppointmentHistory(
                appointment_id=appointment.id,
                old_status=old_status.value,
                new_status=AppointmentStatus.COMPLETED.value,
                changed_by=current_user.id,
            )
        )

        db.commit()
        db.refresh(consultation)

    except Exception:
        db.rollback()
        raise

    # Broadcast only after the consultation and appointment status
    # have been successfully committed.
    await broadcast_queue_update(
        db,
        appointment.doctor_id,
        appointment.appointment_date,
    )

    return consultation



@router.get(
    "/{appointment_id}/consultation",
    response_model=ConsultationResponse,
)
def get_consultation(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    appointment = (
        db.query(Appointment)
        .filter(Appointment.id == appointment_id)
        .first()
    )

    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found",
        )

    role = role_value(current_user)

    if role == UserRole.PATIENT.value:
        if appointment.patient_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only view your own consultation",
            )

    elif role == UserRole.DOCTOR.value:
        doctor = (
            db.query(Doctor)
            .filter(Doctor.user_id == current_user.id)
            .first()
        )

        if not doctor or appointment.doctor_id != doctor.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only view your own patients' consultations",
            )

    elif role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    consultation = (
        db.query(Consultation)
        .filter(Consultation.appointment_id == appointment_id)
        .first()
    )

    if not consultation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Consultation not found",
        )

    return consultation


@router.get("/history")
def consultation_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    patient_id: Optional[int] = Query(None, ge=1),
    doctor_id: Optional[int] = Query(None, ge=1),
    follow_up_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    role = role_value(current_user)

    query = (
        db.query(Consultation)
        .join(
            Appointment,
            Consultation.appointment_id == Appointment.id,
        )
    )

    if role == UserRole.PATIENT.value:
        query = query.filter(
            Appointment.patient_id == current_user.id
        )

    elif role == UserRole.DOCTOR.value:
        doctor = (
            db.query(Doctor)
            .filter(Doctor.user_id == current_user.id)
            .first()
        )

        if doctor is None:
            return []

        query = query.filter(
            Appointment.doctor_id == doctor.id
        )

    elif role == UserRole.ADMIN.value:
        if patient_id is not None:
            query = query.filter(
                Appointment.patient_id == patient_id
            )

        if doctor_id is not None:
            query = query.filter(
                Appointment.doctor_id == doctor_id
            )

    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    if follow_up_date is not None:
        query = query.filter(
            Consultation.follow_up_date == follow_up_date
        )

    query = query.order_by(
        Appointment.appointment_date.desc(),
        Appointment.id.desc(),
    )

    offset = (page - 1) * page_size

    return query.offset(offset).limit(page_size).all()



@router.get(
    "/{appointment_id}/prescription-pdf",
    tags=["Consultations & Prescriptions"],
)
def download_prescription_pdf(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    appointment = (
        db.query(Appointment)
        .filter(Appointment.id == appointment_id)
        .first()
    )

    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found",
        )

    role = role_value(current_user)

    if role == UserRole.PATIENT.value:
        if appointment.patient_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

    elif role == UserRole.DOCTOR.value:
        doctor = (
            db.query(Doctor)
            .filter(Doctor.user_id == current_user.id)
            .first()
        )

        if not doctor or appointment.doctor_id != doctor.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

    elif role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    consultation = (
        db.query(Consultation)
        .filter(Consultation.appointment_id == appointment_id)
        .first()
    )

    if not consultation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Consultation or prescription not found",
        )

    pdf_buffer = BytesIO()
    pdf = canvas.Canvas(pdf_buffer, pagesize=A4)
    _, height = A4

    y = height - 60

    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(50, y, "Hospital Prescription")
    y -= 40

    pdf.setFont("Helvetica", 11)

    details = [
        f"Appointment ID: {appointment.id}",
        f"Appointment Number: {appointment.appointment_number}",
        f"Patient ID: {appointment.patient_id}",
        f"Doctor ID: {appointment.doctor_id}",
        f"Date: {appointment.appointment_date}",
        "",
        f"Symptoms: {consultation.symptoms}",
        f"Diagnosis: {consultation.diagnosis}",
        f"Prescription: {consultation.prescription}",
        f"Advice: {consultation.advice or 'N/A'}",
        f"Follow-up Date: {consultation.follow_up_date or 'N/A'}",
    ]

    for detail in details:
        if y < 60:
            pdf.showPage()
            pdf.setFont("Helvetica", 11)
            y = height - 60

        # Limit line length to avoid drawing beyond the page.
        pdf.drawString(50, y, detail[:110])
        y -= 22

    pdf.save()
    pdf_buffer.seek(0)

    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="prescription_{appointment_id}.pdf"'
            )
        },
    )
