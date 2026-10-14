
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from typing import Optional

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
from app.schemas.appointment import (
    AppointmentCreate,
    AppointmentResponse,
    AppointmentReschedule,
)
from app.services.notification_service import (
    send_appointment_notification,
)
from app.websockets.manager import manager


router = APIRouter(prefix="/appointments", tags=["Appointments"])


ACTIVE_STATUSES = [
    AppointmentStatus.BOOKED,
    AppointmentStatus.CHECKED_IN,
    AppointmentStatus.IN_CONSULTATION,
]


def role_value(user):
    return user.role.value if hasattr(user.role, "value") else user.role


async def broadcast_queue_update(db, doctor_id: int, queue_date=None):
    from app.routers.queue import (
        broadcast_queue_update as send_queue_update,
    )

    await send_queue_update(
        db,
        doctor_id,
        queue_date or date.today(),
    )


def can_view_appointment(user, appointment):
    role = role_value(user)

    if role == UserRole.ADMIN.value:
        return True

    if role == UserRole.PATIENT.value:
        return appointment.patient_id == user.id

    if role == UserRole.DOCTOR.value:
        return (
            appointment.doctor is not None
            and appointment.doctor.user_id == user.id
        )

    return False


def recalculate_daily_tokens(db, doctor_id: int, appointment_date: date):
    """Reassign tokens by appointment time for active appointments."""
    appointments = (
        db.query(Appointment)
        .filter(
            Appointment.doctor_id == doctor_id,
            Appointment.appointment_date == appointment_date,
            Appointment.status.in_(ACTIVE_STATUSES),
        )
        .order_by(Appointment.slot_time, Appointment.id)
        .with_for_update()
        .all()
    )

    for token, appointment in enumerate(appointments, start=1):
        appointment.token_number = token


@router.post(
    "",
    response_model=AppointmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_appointment(
    data: AppointmentCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if role_value(current_user) != UserRole.PATIENT.value:
        raise HTTPException(
            status_code=403,
            detail="Only patients can book appointments",
        )

    today = date.today()

    if data.appointment_date <= today:
        raise HTTPException(
            status_code=422,
            detail="Appointments must be booked for a future date",
        )

    if data.appointment_date > today + timedelta(days=30):
        raise HTTPException(
            status_code=422,
            detail="Appointments can be booked at most 30 days in advance",
        )

    requested_datetime = datetime.combine(
        data.appointment_date,
        data.slot_time,
    )

    if requested_datetime <= datetime.now():
        raise HTTPException(
            status_code=422,
            detail="Appointment slot must be in the future",
        )

    try:
        doctor = (
            db.query(Doctor)
            .filter(
                Doctor.id == data.doctor_id,
                Doctor.is_active.is_(True),
            )
            .with_for_update()
            .first()
        )

        if doctor is None:
            raise HTTPException(
                status_code=404,
                detail="Active doctor not found",
            )

        if not doctor.user.is_active:
            raise HTTPException(
                status_code=409,
                detail="Doctor's user account is inactive",
            )

        leave = (
            db.query(DoctorLeave)
            .filter(
                DoctorLeave.doctor_id == doctor.id,
                DoctorLeave.leave_date == data.appointment_date,
            )
            .first()
        )

        if leave:
            raise HTTPException(
                status_code=409,
                detail="Doctor is on leave on this date",
            )

        schedules = (
            db.query(DoctorSchedule)
            .filter(
                DoctorSchedule.doctor_id == doctor.id,
                DoctorSchedule.day_of_week
                == data.appointment_date.weekday(),
            )
            .all()
        )

        duration = doctor.slot_duration_minutes
        slot_start = data.slot_time
        slot_end = (
            datetime.combine(data.appointment_date, slot_start)
            + timedelta(minutes=duration)
        ).time()

        valid_schedule = None

        for schedule in schedules:
            if not (
                schedule.start_time <= slot_start
                and slot_end <= schedule.end_time
            ):
                continue

            overlaps_break = (
                schedule.break_start is not None
                and schedule.break_end is not None
                and slot_start < schedule.break_end
                and slot_end > schedule.break_start
            )

            if not overlaps_break:
                valid_schedule = schedule
                break

        if valid_schedule is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Requested slot is outside working hours "
                    "or overlaps a break"
                ),
            )

        same_doctor_day = (
            db.query(Appointment)
            .filter(
                Appointment.patient_id == current_user.id,
                Appointment.doctor_id == doctor.id,
                Appointment.appointment_date == data.appointment_date,
                Appointment.status.in_(ACTIVE_STATUSES),
            )
            .first()
        )

        if same_doctor_day:
            raise HTTPException(
                status_code=409,
                detail=(
                    "You already have an appointment with this "
                    "doctor on that date"
                ),
            )

        same_patient_time = (
            db.query(Appointment)
            .filter(
                Appointment.patient_id == current_user.id,
                Appointment.appointment_date == data.appointment_date,
                Appointment.slot_time == data.slot_time,
                Appointment.status.in_(ACTIVE_STATUSES),
            )
            .first()
        )

        if same_patient_time:
            raise HTTPException(
                status_code=409,
                detail="You already have an appointment at this date and time",
            )

        occupied = (
            db.query(Appointment)
            .filter(
                Appointment.doctor_id == doctor.id,
                Appointment.appointment_date == data.appointment_date,
                Appointment.slot_time == data.slot_time,
                Appointment.status.in_(ACTIVE_STATUSES),
            )
            .first()
        )

        if occupied:
            raise HTTPException(
                status_code=409,
                detail="This appointment slot is already booked",
            )

        day_prefix = f"APT-{data.appointment_date:%Y%m%d}-"

        existing_numbers = (
            db.query(Appointment.appointment_number)
            .filter(
                Appointment.appointment_number.like(f"{day_prefix}%")
            )
            .with_for_update()
            .all()
        )

        sequence = len(existing_numbers) + 1
        appointment_number = f"{day_prefix}{sequence:04d}"

        appointment = Appointment(
            appointment_number=appointment_number,
            patient_id=current_user.id,
            doctor_id=doctor.id,
            appointment_date=data.appointment_date,
            slot_time=data.slot_time,
            token_number=1,
            reason=data.reason,
            status=AppointmentStatus.BOOKED,
            consultation_fee=doctor.consultation_fee,
        )

        db.add(appointment)
        db.flush()

        recalculate_daily_tokens(
            db,
            doctor.id,
            data.appointment_date,
        )

        db.add(
            AppointmentHistory(
                appointment_id=appointment.id,
                old_status=None,
                new_status=AppointmentStatus.BOOKED.value,
                changed_by=current_user.id,
            )
        )

        db.commit()
        db.refresh(appointment)

        doctor_user_id = doctor.user_id
        appointment_id = appointment.id
        appointment_number = appointment.appointment_number
        appointment_date = appointment.appointment_date
        slot_time = appointment.slot_time

        await broadcast_queue_update(
            db,
            doctor.id,
            appointment_date,
        )

        await send_appointment_notification(
            patient_id=current_user.id,
            doctor_user_id=doctor_user_id,
            message={
                "event": "appointment_booked",
                "appointment_id": appointment_id,
                "appointment_number": appointment_number,
                "doctor_id": doctor.id,
                "appointment_date": str(appointment_date),
                "slot_time": str(slot_time),
                "message": "Your appointment has been booked successfully.",
            },
        )

        return appointment

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                "A conflicting appointment or appointment number already "
                "exists. Please refresh the available slots and try again."
            ),
        )
    except Exception:
        db.rollback()
        raise


@router.get("", response_model=list[AppointmentResponse])
def list_appointments(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    appointment_date: Optional[date] = None,
    appointment_status: Optional[str] = None,
    doctor_id: Optional[int] = Query(None, ge=1),
    search: Optional[str] = Query(None, min_length=1, max_length=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    role = role_value(current_user)

    query = db.query(Appointment)
    doctor = None

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

    elif role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=403,
            detail="You are not allowed to view appointments",
        )

    if appointment_date is not None:
        query = query.filter(
            Appointment.appointment_date == appointment_date
        )

    if appointment_status is not None:
        valid_statuses = {
            item.value for item in AppointmentStatus
        }

        if appointment_status not in valid_statuses:
            raise HTTPException(
                status_code=422,
                detail="Invalid appointment status",
            )

        query = query.filter(
            Appointment.status == AppointmentStatus(appointment_status)
        )

    if doctor_id is not None:
        if role == UserRole.PATIENT.value:
            raise HTTPException(
                status_code=403,
                detail="Patients cannot filter by doctor ID",
            )

        if (
            role == UserRole.DOCTOR.value
            and doctor_id != doctor.id
        ):
            raise HTTPException(
                status_code=403,
                detail="You cannot view another doctor's appointments",
            )

        query = query.filter(
            Appointment.doctor_id == doctor_id
        )

    if search is not None:
        search_term = search.strip()

        if not search_term:
            raise HTTPException(
                status_code=422,
                detail="Search text cannot be empty",
            )

        query = query.filter(
            Appointment.appointment_number.ilike(
                f"%{search_term}%"
            )
        )

    query = query.order_by(
        Appointment.appointment_date,
        Appointment.slot_time,
        Appointment.id,
    )

    offset = (page - 1) * page_size

    return query.offset(offset).limit(page_size).all()


@router.get(
    "/{appointment_id}",
    response_model=AppointmentResponse,
)
def get_appointment(
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
        raise HTTPException(
            status_code=404,
            detail="Appointment not found",
        )

    if not can_view_appointment(current_user, appointment):
        raise HTTPException(
            status_code=403,
            detail="You are not allowed to view this appointment",
        )

    return appointment


def get_booked_appointment(appointment_id, current_user, db):
    appointment = (
        db.query(Appointment)
        .filter(Appointment.id == appointment_id)
        .with_for_update()
        .first()
    )

    if appointment is None:
        raise HTTPException(
            status_code=404,
            detail="Appointment not found",
        )

    if role_value(current_user) != UserRole.PATIENT.value:
        raise HTTPException(
            status_code=403,
            detail="Only the patient who owns the appointment can do this",
        )

    if appointment.patient_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You cannot modify another patient's appointment",
        )

    if appointment.status != AppointmentStatus.BOOKED:
        raise HTTPException(
            status_code=409,
            detail="Only Booked appointments can be modified",
        )

    return appointment


def check_two_hour_cutoff(appointment):
    appointment_datetime = datetime.combine(
        appointment.appointment_date,
        appointment.slot_time,
    )

    if datetime.now() > appointment_datetime - timedelta(hours=2):
        raise HTTPException(
            status_code=422,
            detail=(
                "Cancellation or rescheduling is allowed only "
                "up to 2 hours before the slot"
            ),
        )


def validate_reschedule_slot(
    appointment,
    new_date,
    new_time,
    db,
):
    today = date.today()

    if new_date <= today:
        raise HTTPException(
            status_code=422,
            detail="Rescheduled appointments must be on a future date",
        )

    if new_date > today + timedelta(days=30):
        raise HTTPException(
            status_code=422,
            detail="Appointments can be booked at most 30 days in advance",
        )

    doctor = (
        db.query(Doctor)
        .filter(
            Doctor.id == appointment.doctor_id,
            Doctor.is_active.is_(True),
        )
        .with_for_update()
        .first()
    )

    if doctor is None:
        raise HTTPException(
            status_code=404,
            detail="Active doctor not found",
        )

    if not doctor.user.is_active:
        raise HTTPException(
            status_code=409,
            detail="Doctor's user account is inactive",
        )

    leave = (
        db.query(DoctorLeave)
        .filter(
            DoctorLeave.doctor_id == doctor.id,
            DoctorLeave.leave_date == new_date,
        )
        .first()
    )

    if leave:
        raise HTTPException(
            status_code=409,
            detail="Doctor is on leave on the selected date",
        )

    duration = doctor.slot_duration_minutes
    requested_start = datetime.combine(new_date, new_time)
    requested_end = requested_start + timedelta(minutes=duration)

    if requested_start <= datetime.now():
        raise HTTPException(
            status_code=422,
            detail="The selected slot must be in the future",
        )

    schedules = (
        db.query(DoctorSchedule)
        .filter(
            DoctorSchedule.doctor_id == doctor.id,
            DoctorSchedule.day_of_week == new_date.weekday(),
        )
        .all()
    )

    valid_slot = False

    for schedule in schedules:
        if not (
            schedule.start_time <= new_time
            and requested_end.time() <= schedule.end_time
            and requested_end.date() == new_date
        ):
            continue

        schedule_start = datetime.combine(
            new_date,
            schedule.start_time,
        )

        minutes_from_start = int(
            (requested_start - schedule_start).total_seconds() // 60
        )

        if minutes_from_start < 0 or minutes_from_start % duration != 0:
            continue

        overlaps_break = (
            schedule.break_start is not None
            and schedule.break_end is not None
            and new_time < schedule.break_end
            and requested_end.time() > schedule.break_start
        )

        if not overlaps_break:
            valid_slot = True
            break

    if not valid_slot:
        raise HTTPException(
            status_code=422,
            detail=(
                "Selected time is outside working hours, overlaps a break, "
                "or is not a valid slot"
            ),
        )

    same_doctor_day = (
        db.query(Appointment)
        .filter(
            Appointment.id != appointment.id,
            Appointment.patient_id == appointment.patient_id,
            Appointment.doctor_id == doctor.id,
            Appointment.appointment_date == new_date,
            Appointment.status.in_(ACTIVE_STATUSES),
        )
        .first()
    )

    if same_doctor_day:
        raise HTTPException(
            status_code=409,
            detail="You already have an appointment with this doctor on that date",
        )

    same_patient_time = (
        db.query(Appointment)
        .filter(
            Appointment.id != appointment.id,
            Appointment.patient_id == appointment.patient_id,
            Appointment.appointment_date == new_date,
            Appointment.slot_time == new_time,
            Appointment.status.in_(ACTIVE_STATUSES),
        )
        .first()
    )

    if same_patient_time:
        raise HTTPException(
            status_code=409,
            detail="You already have an appointment at this date and time",
        )

    occupied = (
        db.query(Appointment)
        .filter(
            Appointment.id != appointment.id,
            Appointment.doctor_id == doctor.id,
            Appointment.appointment_date == new_date,
            Appointment.slot_time == new_time,
            Appointment.status.in_(ACTIVE_STATUSES),
        )
        .first()
    )

    if occupied:
        raise HTTPException(
            status_code=409,
            detail="The selected slot is already booked",
        )

    return doctor


@router.put(
    "/{appointment_id}/reschedule",
    response_model=AppointmentResponse,
)
async def reschedule_appointment(
    appointment_id: int,
    data: AppointmentReschedule,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    appointment = get_booked_appointment(
        appointment_id,
        current_user,
        db,
    )

    check_two_hour_cutoff(appointment)

    if appointment.reschedule_count >= 2:
        raise HTTPException(
            status_code=409,
            detail="Maximum of 2 reschedules reached. Cancel and book again",
        )

    if (
        appointment.appointment_date == data.appointment_date
        and appointment.slot_time == data.slot_time
    ):
        raise HTTPException(
            status_code=422,
            detail="Choose a different date or time",
        )

    validate_reschedule_slot(
        appointment,
        data.appointment_date,
        data.slot_time,
        db,
    )

    try:
        old_date = appointment.appointment_date
        old_status = appointment.status.value

        appointment.appointment_date = data.appointment_date
        appointment.slot_time = data.slot_time
        appointment.reschedule_count += 1

        db.add(
            AppointmentHistory(
                appointment_id=appointment.id,
                old_status=old_status,
                new_status=AppointmentStatus.BOOKED.value,
                changed_by=current_user.id,
            )
        )

        db.flush()

        recalculate_daily_tokens(
            db,
            appointment.doctor_id,
            old_date,
        )
        recalculate_daily_tokens(
            db,
            appointment.doctor_id,
            appointment.appointment_date,
        )

        db.commit()
        db.refresh(appointment)

        doctor_user_id = appointment.doctor.user_id
        appointment_id_value = appointment.id
        appointment_number = appointment.appointment_number
        new_date = appointment.appointment_date
        new_time = appointment.slot_time
        doctor_id = appointment.doctor_id
        patient_id = appointment.patient_id

        await broadcast_queue_update(db, doctor_id, old_date)
        await broadcast_queue_update(db, doctor_id, new_date)

        await send_appointment_notification(
            patient_id=patient_id,
            doctor_user_id=doctor_user_id,
            message={
                "event": "appointment_rescheduled",
                "appointment_id": appointment_id_value,
                "appointment_number": appointment_number,
                "appointment_date": str(new_date),
                "slot_time": str(new_time),
                "message": "Your appointment has been rescheduled successfully.",
            },
        )

        return appointment

    except Exception:
        db.rollback()
        raise


@router.put(
    "/{appointment_id}/cancel",
    response_model=AppointmentResponse,
)
async def cancel_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    appointment = get_booked_appointment(
        appointment_id,
        current_user,
        db,
    )

    check_two_hour_cutoff(appointment)

    try:
        old_status = appointment.status.value
        doctor_id = appointment.doctor_id
        appointment_date = appointment.appointment_date

        appointment.status = AppointmentStatus.CANCELLED

        db.add(
            AppointmentHistory(
                appointment_id=appointment.id,
                old_status=old_status,
                new_status=AppointmentStatus.CANCELLED.value,
                changed_by=current_user.id,
            )
        )

        recalculate_daily_tokens(
            db,
            doctor_id,
            appointment_date,
        )

        db.commit()
        db.refresh(appointment)

        doctor_user_id = appointment.doctor.user_id
        patient_id = appointment.patient_id
        appointment_id_value = appointment.id
        appointment_number = appointment.appointment_number

        await broadcast_queue_update(
            db,
            doctor_id,
            appointment_date,
        )

        await send_appointment_notification(
            patient_id=patient_id,
            doctor_user_id=doctor_user_id,
            message={
                "event": "appointment_cancelled",
                "appointment_id": appointment_id_value,
                "appointment_number": appointment_number,
                "message": "Your appointment has been cancelled.",
            },
        )

        return appointment

    except Exception:
        db.rollback()
        raise


@router.put(
    "/{appointment_id}/check-in",
    response_model=AppointmentResponse,
)
async def check_in_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    admin=Depends(get_current_user),
):
    if role_value(admin) != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=403,
            detail="Only admins can check in patients",
        )

    appointment = (
        db.query(Appointment)
        .filter(Appointment.id == appointment_id)
        .with_for_update()
        .first()
    )

    if appointment is None:
        raise HTTPException(
            status_code=404,
            detail="Appointment not found",
        )

    if appointment.status != AppointmentStatus.BOOKED:
        raise HTTPException(
            status_code=409,
            detail="Only Booked appointments can be checked in",
        )

    now = datetime.now()
    slot_datetime = datetime.combine(
        appointment.appointment_date,
        appointment.slot_time,
    )

    earliest_check_in = slot_datetime - timedelta(minutes=30)
    latest_check_in = slot_datetime + timedelta(minutes=30)

    if not earliest_check_in <= now <= latest_check_in:
        raise HTTPException(
            status_code=422,
            detail=(
                "Check-in is allowed only on the appointment date, "
                "from 30 minutes before until 30 minutes after the slot time"
            ),
        )

    try:
        appointment.status = AppointmentStatus.CHECKED_IN

        db.add(
            AppointmentHistory(
                appointment_id=appointment.id,
                old_status=AppointmentStatus.BOOKED.value,
                new_status=AppointmentStatus.CHECKED_IN.value,
                changed_by=admin.id,
            )
        )

        db.commit()
        db.refresh(appointment)

        doctor_user_id = appointment.doctor.user_id
        patient_id = appointment.patient_id
        appointment_id_value = appointment.id
        appointment_number = appointment.appointment_number
        doctor_id = appointment.doctor_id
        appointment_date = appointment.appointment_date

        await broadcast_queue_update(
            db,
            doctor_id,
            appointment_date,
        )

        await send_appointment_notification(
            patient_id=patient_id,
            doctor_user_id=doctor_user_id,
            message={
                "event": "patient_checked_in",
                "appointment_id": appointment_id_value,
                "appointment_number": appointment_number,
                "message": "You have checked in successfully.",
            },
        )

        return appointment

    except Exception:
        db.rollback()
        raise



