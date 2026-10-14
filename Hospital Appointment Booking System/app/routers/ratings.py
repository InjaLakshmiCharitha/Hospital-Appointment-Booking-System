
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.models import (
    Appointment,
    AppointmentRating,
    AppointmentStatus,
    UserRole,
    Doctor
)
from app.schemas.rating import RatingCreate, RatingResponse

router = APIRouter(
    prefix="/appointments",
    tags=["Appointment Ratings & Feedback"],
)


def role_value(user):
    return user.role.value if hasattr(user.role, "value") else user.role


@router.post(
    "/{appointment_id}/rating",
    response_model=RatingResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_rating(
    appointment_id: int,
    data: RatingCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if role_value(current_user) != UserRole.PATIENT.value:
        raise HTTPException(
            status_code=403,
            detail="Only patients can submit ratings",
        )

    appointment = (
        db.query(Appointment)
        .filter(Appointment.id == appointment_id)
        .first()
    )

    if appointment is None:
        raise HTTPException(status_code=404, detail="Appointment not found")

    if appointment.patient_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You can rate only your own appointments",
        )

    if appointment.status != AppointmentStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail="Only completed appointments can be rated",
        )

    existing = (
        db.query(AppointmentRating)
        .filter(AppointmentRating.appointment_id == appointment_id)
        .first()
    )

    if existing:
        raise HTTPException(
            status_code=409,
            detail="This appointment has already been rated",
        )

    rating = AppointmentRating(
        appointment_id=appointment.id,
        patient_id=current_user.id,
        doctor_id=appointment.doctor_id,
        rating=data.rating,
        feedback=data.feedback,
    )

    db.add(rating)

    try:
        db.commit()
        db.refresh(rating)
    except Exception:
        db.rollback()
        raise

    return rating


@router.get(
    "/{appointment_id}/rating",
    response_model=RatingResponse,
)
def get_rating(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    appointment = (
        db.query(Appointment)
        .filter(Appointment.id == appointment_id)
        .first()
    )

    if appointment is None:
        raise HTTPException(status_code=404, detail="Appointment not found")

    role = role_value(current_user)

    if role == UserRole.PATIENT.value:
        if appointment.patient_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied")
    elif role != UserRole.ADMIN.value:
        doctor = (
            db.query(Doctor)
            .filter(Doctor.user_id == current_user.id)
            .first()
        )
        if not doctor or doctor.id != appointment.doctor_id:
            raise HTTPException(status_code=403, detail="Access denied")

    rating = (
        db.query(AppointmentRating)
        .filter(AppointmentRating.appointment_id == appointment_id)
        .first()
    )

    if rating is None:
        raise HTTPException(status_code=404, detail="Rating not found")

    return rating
