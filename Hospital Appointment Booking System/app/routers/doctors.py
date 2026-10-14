from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.models.models import (
    Appointment,
    AppointmentStatus,
    Department,
    Doctor,
    User,
    UserRole,
)
from app.schemas.doctor import DoctorCreate, DoctorUpdate, DoctorResponse
from app.auth.dependencies import require_roles

router = APIRouter(prefix="/doctors", tags=["Doctors"])

ALLOWED_SLOT_DURATIONS = {10, 15, 20, 30}

UPCOMING_STATUSES = [
    AppointmentStatus.BOOKED,
    AppointmentStatus.CHECKED_IN,
    AppointmentStatus.IN_CONSULTATION,
]


def get_doctor_or_404(db: Session, doctor_id: int) -> Doctor:
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()

    if doctor is None:
        raise HTTPException(status_code=404, detail="Doctor not found")

    return doctor


def ensure_no_upcoming_appointments(db: Session, doctor_id: int) -> None:
    upcoming = db.query(Appointment).filter(
        Appointment.doctor_id == doctor_id,
        Appointment.appointment_date >= date.today(),
        Appointment.status.in_(UPCOMING_STATUSES),
    ).first()

    if upcoming:
        raise HTTPException(
            status_code=409,
            detail="Cannot deactivate a doctor who has upcoming appointments",
        )


@router.get("")
def list_doctors(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    department_id: Optional[int] = Query(None, ge=1),
    specialization: Optional[str] = Query(None, min_length=1, max_length=100),
    search: Optional[str] = Query(None, min_length=1, max_length=100),
    db: Session = Depends(get_db),
):
    query = db.query(Doctor).filter(Doctor.is_active.is_(True))

    if department_id is not None:
        query = query.filter(Doctor.department_id == department_id)

    if specialization is not None:
        query = query.filter(
            Doctor.specialization.ilike(
                f"%{specialization.strip()}%"
            )
        )

    if search is not None:
        search_term = search.strip()

        if not search_term:
            raise HTTPException(
                status_code=422,
                detail="Search text cannot be empty",
            )

        query = query.filter(
            Doctor.name.ilike(f"%{search_term}%")
        )

    query = query.order_by(Doctor.name, Doctor.id)

    offset = (page - 1) * page_size

    return query.offset(offset).limit(page_size).all()


@router.get("/{doctor_id}", response_model=DoctorResponse)
def get_doctor(doctor_id: int, db: Session = Depends(get_db)):
    doctor = (
        db.query(Doctor)
        .join(Department, Doctor.department_id == Department.id)
        .filter(
            Doctor.id == doctor_id,
            Doctor.is_active.is_(True),
            Department.is_active.is_(True),
        )
        .first()
    )

    if doctor is None:
        raise HTTPException(status_code=404, detail="Active doctor not found")

    return doctor


@router.post(
    "/",
    response_model=DoctorResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_doctor(
    data: DoctorCreate,
    db: Session = Depends(get_db),
    admin=Depends(require_roles("admin")),
):
    doctor_user = db.query(User).filter(User.id == data.user_id).first()

    if doctor_user is None:
        raise HTTPException(status_code=404, detail="Doctor user account not found")

    if doctor_user.role != UserRole.DOCTOR:
        raise HTTPException(
            status_code=422,
            detail="user_id must belong to a user with the doctor role",
        )

    if not doctor_user.is_active:
        raise HTTPException(
            status_code=409,
            detail="Cannot create a profile for an inactive user",
        )

    existing_profile = db.query(Doctor).filter(
        Doctor.user_id == data.user_id
    ).first()

    if existing_profile:
        raise HTTPException(
            status_code=409,
            detail="This user already has a doctor profile",
        )

    department = db.query(Department).filter(
        Department.id == data.department_id,
        Department.is_active.is_(True),
    ).first()

    if department is None:
        raise HTTPException(
            status_code=404,
            detail="Active department not found",
        )

    if data.slot_duration_minutes not in ALLOWED_SLOT_DURATIONS:
        raise HTTPException(
            status_code=422,
            detail="slot_duration_minutes must be 10, 15, 20, or 30",
        )

    doctor = Doctor(
        user_id=data.user_id,
        name=data.name.strip(),
        department_id=data.department_id,
        specialization=data.specialization.strip(),
        qualification=data.qualification.strip(),
        experience_years=data.experience_years,
        consultation_fee=data.consultation_fee,
        slot_duration_minutes=data.slot_duration_minutes,
        is_active=True,
    )

    db.add(doctor)

    try:
        db.commit()
        db.refresh(doctor)
    except Exception:
        db.rollback()
        raise

    return doctor


@router.put("/{doctor_id}", response_model=DoctorResponse)
def update_doctor(
    doctor_id: int,
    data: DoctorUpdate,
    db: Session = Depends(get_db),
    admin=Depends(require_roles("admin")),
):
    doctor = get_doctor_or_404(db, doctor_id)
    changes = data.model_dump(exclude_unset=True)

    if "department_id" in changes and changes["department_id"] is not None:
        department = db.query(Department).filter(
            Department.id == changes["department_id"],
            Department.is_active.is_(True),
        ).first()

        if department is None:
            raise HTTPException(
                status_code=404,
                detail="Active department not found",
            )

    if (
        "slot_duration_minutes" in changes
        and changes["slot_duration_minutes"] is not None
        and changes["slot_duration_minutes"] not in ALLOWED_SLOT_DURATIONS
    ):
        raise HTTPException(
            status_code=422,
            detail="slot_duration_minutes must be 10, 15, 20, or 30",
        )

    if changes.get("is_active") is False and doctor.is_active:
        ensure_no_upcoming_appointments(db, doctor_id)

    for field in ("name", "specialization", "qualification"):
        if field in changes and changes[field] is not None:
            changes[field] = changes[field].strip()
            if not changes[field]:
                raise HTTPException(
                    status_code=422,
                    detail=f"{field} cannot be empty",
                )

    for field, value in changes.items():
        setattr(doctor, field, value)

    try:
        db.commit()
        db.refresh(doctor)
    except Exception:
        db.rollback()
        raise

    return doctor


@router.delete("/{doctor_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_doctor(
    doctor_id: int,
    db: Session = Depends(get_db),
    admin=Depends(require_roles("admin")),
):
    doctor = get_doctor_or_404(db, doctor_id)

    if doctor.is_active:
        ensure_no_upcoming_appointments(db, doctor_id)
        doctor.is_active = False

        try:
            db.commit()
        except Exception:
            db.rollback()
            raise

    # Soft deletion: the database record remains for appointment history.
    return None