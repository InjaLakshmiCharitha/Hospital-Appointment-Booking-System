from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_roles
from app.database import get_db
from app.models.models import Doctor, DoctorSchedule, UserRole
from app.schemas.schedule import (
    ScheduleCreate,
    ScheduleResponse,
    ScheduleUpdate,
)
from typing import Optional

router = APIRouter(prefix="/schedules", tags=["Doctor Schedules"])


def get_schedule_or_404(db: Session, schedule_id: int):
    schedule = db.query(DoctorSchedule).filter(
        DoctorSchedule.id == schedule_id
    ).first()

    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")

    return schedule


def validate_doctor(db: Session, doctor_id: int):
    doctor = db.query(Doctor).filter(
        Doctor.id == doctor_id,
        Doctor.is_active.is_(True),
    ).first()

    if doctor is None:
        raise HTTPException(status_code=404, detail="Active doctor not found")

    return doctor



def verify_schedule_permission(schedule, current_user):
    
    if current_user.role.value == "admin":
        return

    if current_user.role.value == "doctor":
        doctor = current_user.doctor_profile

        if doctor is None or doctor.id != schedule.doctor_id:
            raise HTTPException(
                status_code=403,
                detail="You can manage only your own schedules",
            )
        return

    raise HTTPException(
        status_code=403,
        detail="You do not have permission to manage schedules",
    )


@router.get("/", response_model=list[ScheduleResponse])
def list_schedules(
    doctor_id: Optional[int] = Query(default=None, gt=0),
    day_of_week: Optional[int] = Query(default=None, ge=0, le=6),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(DoctorSchedule)

    # Filter schedules by doctor
    if doctor_id is not None:
        validate_doctor(db, doctor_id)
        query = query.filter(
            DoctorSchedule.doctor_id == doctor_id
        )

    # Filter schedules by day of the week (0-6)
    if day_of_week is not None:
        query = query.filter(
            DoctorSchedule.day_of_week == day_of_week
        )

    # Apply pagination
    schedules = (
        query
        .order_by(
            DoctorSchedule.doctor_id,
            DoctorSchedule.day_of_week,
            DoctorSchedule.start_time,
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return schedules



@router.post(
    "/",
    response_model=ScheduleResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_schedule(
    data: ScheduleCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.role.value == "doctor":
          if (
               current_user.doctor_profile is None
               or current_user.doctor_profile.id != data.doctor_id
           ):
            raise HTTPException(
               status_code=403,
               detail="You can manage only your own schedules",
            )
    elif current_user.role.value != "admin":
        raise HTTPException(
             status_code=403,
             detail="You do not have permission to manage schedules",
        )

    validate_doctor(db, data.doctor_id)

    if data.break_start is not None:
        if not (
            data.start_time < data.break_start
            < data.break_end < data.end_time
        ):
            raise HTTPException(
                status_code=422,
                detail="Break must be inside the working hours",
            )

    existing = db.query(DoctorSchedule).filter(
        DoctorSchedule.doctor_id == data.doctor_id,
        DoctorSchedule.day_of_week == data.day_of_week,
    ).all()

    for item in existing:
        overlaps = (
            data.start_time < item.end_time
            and item.start_time < data.end_time
        )
        if overlaps:
            raise HTTPException(
                status_code=409,
                detail="Schedule overlaps with an existing schedule for this day",
            )

    schedule = DoctorSchedule(**data.model_dump())
    db.add(schedule)

    try:
        db.commit()
        db.refresh(schedule)
    except Exception:
        db.rollback()
        raise

    return schedule


@router.put("/{schedule_id}", response_model=ScheduleResponse)
def update_schedule(
    schedule_id: int,
    data: ScheduleUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    schedule = get_schedule_or_404(db, schedule_id)
    verify_schedule_permission(schedule, current_user)
    changes = data.model_dump(exclude_unset=True)

    candidate = {
        "day_of_week": schedule.day_of_week,
        "start_time": schedule.start_time,
        "end_time": schedule.end_time,
        "break_start": schedule.break_start,
        "break_end": schedule.break_end,
    }
    candidate.update(changes)

    if candidate["start_time"] is None or candidate["end_time"] is None:
        raise HTTPException(status_code=422, detail="Start and end times are required")

    if candidate["end_time"] <= candidate["start_time"]:
        raise HTTPException(status_code=422, detail="End time must be after start time")

    if (candidate["break_start"] is None) != (candidate["break_end"] is None):
        raise HTTPException(status_code=422, detail="Provide both break times")

    if candidate["break_start"] is not None:
        if not (
            candidate["start_time"] < candidate["break_start"]
            < candidate["break_end"] < candidate["end_time"]
        ):
            raise HTTPException(status_code=422, detail="Break must be inside working hours")

    other_schedules = db.query(DoctorSchedule).filter(
        DoctorSchedule.doctor_id == schedule.doctor_id,
        DoctorSchedule.day_of_week == candidate["day_of_week"],
        DoctorSchedule.id != schedule_id,
    ).all()

    for item in other_schedules:
        if (
            candidate["start_time"] < item.end_time
            and item.start_time < candidate["end_time"]
        ):
            raise HTTPException(status_code=409, detail="Schedule overlaps another schedule")

    for field, value in changes.items():
        setattr(schedule, field, value)

    try:
        db.commit()
        db.refresh(schedule)
    except Exception:
        db.rollback()
        raise

    return schedule


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    schedule = get_schedule_or_404(db, schedule_id)
    verify_schedule_permission(schedule, current_user)
    db.delete(schedule)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    return None