
import asyncio
import logging
from datetime import date, datetime, timedelta

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.models import (
    Appointment,
    AppointmentHistory,
    AppointmentStatus,
    Doctor,
    DoctorLeave,
    DoctorSchedule,
    UserRole,
)
from app.schemas.leave import LeaveCreate, LeaveResponse
from app.routers.queue import broadcast_queue_update
from app.services.email_service import send_email

router = APIRouter(prefix="/leaves", tags=["Doctor Leaves"])

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = [
    AppointmentStatus.BOOKED,
    AppointmentStatus.CHECKED_IN,
    AppointmentStatus.IN_CONSULTATION,
]


def role_value(user):
    return user.role.value if hasattr(user.role, "value") else user.role


def verify_leave_permission(doctor_id: int, current_user):
    """Allow admins to manage any leave and doctors their own leaves."""
    role = role_value(current_user)

    if role == UserRole.ADMIN.value:
        return

    if role == UserRole.DOCTOR.value:
        doctor = current_user.doctor_profile

        if doctor is None or doctor.id != doctor_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can manage only your own leaves",
            )
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to manage doctor leaves",
    )


def get_active_doctor(db: Session, doctor_id: int):
    doctor = (
        db.query(Doctor)
        .filter(
            Doctor.id == doctor_id,
            Doctor.is_active.is_(True),
        )
        .first()
    )

    if doctor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active doctor not found",
        )

    return doctor


def send_leave_email_sync(email: str, subject: str, body: str):
    """Run the project's asynchronous email service as a background task."""
    try:
        asyncio.run(send_email(email, subject, body))
    except Exception:
        logger.exception("Failed to send leave notification to %s", email)


async def broadcast_leave_queue_updates(doctor_id: int, leave_date: date):
    """Broadcast queue updates using a separate database session."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        await broadcast_queue_update(db, doctor_id, leave_date)
    except Exception:
        logger.exception(
            "Failed to broadcast queue update for doctor %s",
            doctor_id,
        )
    finally:
        db.close()


def broadcast_leave_queue_sync(doctor_id: int, leave_date: date):
    try:
        asyncio.run(broadcast_leave_queue_updates(doctor_id, leave_date))
    except Exception:
        logger.exception("Failed to run leave queue update")


@router.get("/", response_model=list[LeaveResponse])
def list_leaves(
    doctor_id: int = Query(..., gt=0),
    db: Session = Depends(get_db),
):
    get_active_doctor(db, doctor_id)

    return (
        db.query(DoctorLeave)
        .filter(
            DoctorLeave.doctor_id == doctor_id,
            DoctorLeave.leave_date >= date.today(),
        )
        .order_by(DoctorLeave.leave_date)
        .all()
    )


@router.post(
    "/",
    response_model=LeaveResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_leave(
    data: LeaveCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    verify_leave_permission(data.doctor_id, current_user)

    doctor = get_active_doctor(db, data.doctor_id)

    if data.leave_date < date.today():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Leave date cannot be in the past",
        )

    existing = (
        db.query(DoctorLeave)
        .filter(
            DoctorLeave.doctor_id == data.doctor_id,
            DoctorLeave.leave_date == data.leave_date,
        )
        .first()
    )

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Leave already exists for this date",
        )

    leave = DoctorLeave(**data.model_dump())
    db.add(leave)

    cancelled_appointments = (
        db.query(Appointment)
        .filter(
            Appointment.doctor_id == data.doctor_id,
            Appointment.appointment_date == data.leave_date,
            Appointment.status.in_(ACTIVE_STATUSES),
        )
        .with_for_update()
        .all()
    )

    for appointment in cancelled_appointments:
        old_status = (
            appointment.status.value
            if hasattr(appointment.status, "value")
            else str(appointment.status)
        )

        appointment.status = AppointmentStatus.CANCELLED

        db.add(
            AppointmentHistory(
                appointment_id=appointment.id,
                old_status=old_status,
                new_status=AppointmentStatus.CANCELLED.value,
                changed_by=current_user.id,
            )
        )

    try:
        db.commit()
        db.refresh(leave)
    except Exception:
        db.rollback()
        raise

    # Notify affected patients after the database transaction succeeds.
    for appointment in cancelled_appointments:
        patient = appointment.patient

        if patient and patient.email:
            background_tasks.add_task(
                send_leave_email_sync,
                patient.email,
                "Appointment cancelled due to doctor leave",
                (
                    f"Hello {patient.full_name},\n\n"
                    f"Your appointment with Dr. {doctor.name} on "
                    f"{appointment.appointment_date} at "
                    f"{appointment.slot_time.strftime('%H:%M')} has been "
                    "cancelled because the doctor is on leave.\n\n"
                    "Please log in to the hospital appointment system "
                    "to book another appointment.\n\n"
                    "We apologise for the inconvenience."
                ),
            )

        background_tasks.add_task(
            broadcast_leave_queue_sync,
            appointment.doctor_id,
            appointment.appointment_date,
        )

    return leave


@router.delete(
    "/{leave_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_leave(
    leave_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    leave = (
        db.query(DoctorLeave)
        .filter(DoctorLeave.id == leave_id)
        .first()
    )

    if leave is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Leave not found",
        )

    verify_leave_permission(leave.doctor_id, current_user)

    db.delete(leave)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    return None


@router.get("/doctors/{doctor_id}/available-slots")
def get_available_slots(
    doctor_id: int,
    date: date = Query(..., description="Date in YYYY-MM-DD format"),
    db: Session = Depends(get_db),
):
    doctor = get_active_doctor(db, doctor_id)

    today = datetime.now().date()

    if date < today:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot check slots for a past date",
        )

    leave = (
        db.query(DoctorLeave)
        .filter(
            DoctorLeave.doctor_id == doctor_id,
            DoctorLeave.leave_date == date,
        )
        .first()
    )

    if leave:
        return {
            "doctor_id": doctor_id,
            "date": date.isoformat(),
            "slot_duration_minutes": doctor.slot_duration_minutes,
            "available_slots": [],
            "message": "Doctor is on leave",
        }

    schedules = (
        db.query(DoctorSchedule)
        .filter(
            DoctorSchedule.doctor_id == doctor_id,
            DoctorSchedule.day_of_week == date.weekday(),
        )
        .order_by(DoctorSchedule.start_time)
        .all()
    )

    if not schedules:
        return {
            "doctor_id": doctor_id,
            "date": date.isoformat(),
            "slot_duration_minutes": doctor.slot_duration_minutes,
            "available_slots": [],
            "message": "No schedule available for this date",
        }

    duration = doctor.slot_duration_minutes

    if not duration or duration <= 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Doctor slot duration is not configured",
        )

    appointments = (
        db.query(Appointment)
        .filter(
            Appointment.doctor_id == doctor_id,
            Appointment.appointment_date == date,
            Appointment.status.in_(ACTIVE_STATUSES),
        )
        .all()
    )

    booked_intervals = []

    for appointment in appointments:
        start = datetime.combine(date, appointment.slot_time)
        end = start + timedelta(minutes=duration)
        booked_intervals.append((start, end))

    now = datetime.now()
    available_slots = []

    for schedule in schedules:
        current = datetime.combine(date, schedule.start_time)
        end = datetime.combine(date, schedule.end_time)

        while current + timedelta(minutes=duration) <= end:
            slot_end = current + timedelta(minutes=duration)
            slot_start_time = current.time()
            slot_end_time = slot_end.time()

            overlaps_break = (
                schedule.break_start is not None
                and schedule.break_end is not None
                and slot_start_time < schedule.break_end
                and slot_end_time > schedule.break_start
            )

            is_past = date == today and current <= now

            overlaps_booking = any(
                current < booked_end and booked_start < slot_end
                for booked_start, booked_end in booked_intervals
            )

            if (
                not overlaps_break
                and not is_past
                and not overlaps_booking
            ):
                available_slots.append(slot_start_time.strftime("%H:%M"))

            current += timedelta(minutes=duration)

    return {
        "doctor_id": doctor_id,
        "date": date.isoformat(),
        "slot_duration_minutes": duration,
        "available_slots": sorted(set(available_slots)),
    }
