
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from sqlalchemy import func

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.models import (
    Appointment,
    AppointmentStatus,
    Doctor,
    User,
    UserRole,
)
from app.models.models import Department

router = APIRouter(
    prefix="/reports",
    tags=["Reports & Analytics"],
)


def role_value(user):
    return user.role.value if hasattr(user.role, "value") else user.role


@router.get("/dashboard")
def dashboard_report(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # Only administrators can view the dashboard report.
    if role_value(current_user) != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=403,
            detail="Only administrators can access dashboard reports",
        )

    today = date.today()

    # Count registered patients.
    total_patients = (
        db.query(User)
        .filter(User.role == UserRole.PATIENT)
        .count()
    )

    # Count active doctors.
    total_doctors = (
        db.query(Doctor)
        .filter(Doctor.is_active.is_(True))
        .count()
    )

    # Count appointments scheduled for today.
    appointments_today = (
        db.query(Appointment)
        .filter(Appointment.appointment_date == today)
        .count()
    )

    # Count completed appointments.
    completed_appointments = (
        db.query(Appointment)
        .filter(
            Appointment.status == AppointmentStatus.COMPLETED
        )
        .count()
    )

    # Count cancelled appointments.
    cancelled_appointments = (
        db.query(Appointment)
        .filter(
            Appointment.status == AppointmentStatus.CANCELLED
        )
        .count()
    )

    # Count patients who did not attend.
    no_show_appointments = (
        db.query(Appointment)
        .filter(
            Appointment.status == AppointmentStatus.NO_SHOW
        )
        .count()
    )

    return {
        "report_date": today,
        "total_patients": total_patients,
        "total_active_doctors": total_doctors,
        "appointments_today": appointments_today,
        "completed_appointments": completed_appointments,
        "cancelled_appointments": cancelled_appointments,
        "no_show_appointments": no_show_appointments,
    }



@router.get("/doctor-performance")
def doctor_performance_report(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # Only administrators can view doctor performance.
    if role_value(current_user) != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=403,
            detail="Only administrators can access this report",
        )

    doctors = (
        db.query(Doctor)
        .filter(Doctor.is_active.is_(True))
        .order_by(Doctor.name)
        .all()
    )

    report = []

    for doctor in doctors:
        appointments = (
            db.query(Appointment)
            .filter(Appointment.doctor_id == doctor.id)
            .all()
        )

        total = len(appointments)

        completed = sum(
            1 for appointment in appointments
            if role_value(appointment.status)
            == AppointmentStatus.COMPLETED.value
        )

        cancelled = sum(
            1 for appointment in appointments
            if role_value(appointment.status)
            == AppointmentStatus.CANCELLED.value
        )

        no_show = sum(
            1 for appointment in appointments
            if role_value(appointment.status)
            == AppointmentStatus.NO_SHOW.value
        )

        report.append({
            "doctor_id": doctor.id,
            "doctor_name": doctor.name,
            "department_id": doctor.department_id,
            "total_appointments": total,
            "completed_appointments": completed,
            "cancelled_appointments": cancelled,
            "no_show_appointments": no_show,
        })

    return report



@router.get("/department-summary")
def department_summary_report(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # Only administrators can access this report.
    if role_value(current_user) != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=403,
            detail="Only administrators can access this report",
        )

    departments = (
        db.query(Department)
        .order_by(Department.name)
        .all()
    )

    report = []

    for department in departments:
        doctors = (
            db.query(Doctor)
            .filter(Doctor.department_id == department.id)
            .all()
        )

        doctor_ids = [doctor.id for doctor in doctors]

        appointments = []
        if doctor_ids:
            appointments = (
                db.query(Appointment)
                .filter(Appointment.doctor_id.in_(doctor_ids))
                .all()
            )

        report.append({
            "department_id": department.id,
            "department_name": department.name,
            "total_doctors": len(doctors),
            "total_appointments": len(appointments),
            "completed_appointments": sum(
                1 for appointment in appointments
                if role_value(appointment.status)
                == AppointmentStatus.COMPLETED.value
            ),
            "cancelled_appointments": sum(
                1 for appointment in appointments
                if role_value(appointment.status)
                == AppointmentStatus.CANCELLED.value
            ),
            "no_show_appointments": sum(
                1 for appointment in appointments
                if role_value(appointment.status)
                == AppointmentStatus.NO_SHOW.value
            ),
        })

    return report



@router.get("/peak-hours")
def peak_hours_report(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # Only administrators can access this report.
    if role_value(current_user) != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=403,
            detail="Only administrators can access this report",
        )

    results = (
        db.query(
            func.hour(Appointment.slot_time).label("hour"),
            func.count(Appointment.id).label("appointment_count"),
        )
        .filter(
            Appointment.status != AppointmentStatus.CANCELLED
        )
        .group_by(
            func.hour(Appointment.slot_time)
        )
        .order_by(
            func.count(Appointment.id).desc()
        )
        .all()
    )

    return [
        {
            "hour": int(row.hour),
            "time_period": f"{int(row.hour):02d}:00-{(int(row.hour) + 1) % 24:02d}:00",
            "appointment_count": row.appointment_count,
        }
        for row in results
    ]



@router.get("/frequent-no-shows")
def frequent_no_shows_report(
    min_no_shows: int = 3,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # Only administrators can access this report.
    if role_value(current_user) != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=403,
            detail="Only administrators can access this report",
        )

    if min_no_shows < 1:
        raise HTTPException(
            status_code=422,
            detail="min_no_shows must be at least 1",
        )

    results = (
        db.query(
            Appointment.patient_id.label("patient_id"),
            func.count(Appointment.id).label("no_show_count"),
        )
        .filter(
            Appointment.status == AppointmentStatus.NO_SHOW
        )
        .group_by(Appointment.patient_id)
        .having(func.count(Appointment.id) >= min_no_shows)
        .order_by(func.count(Appointment.id).desc())
        .all()
    )

    report = []

    for row in results:
        patient = (
            db.query(User)
            .filter(User.id == row.patient_id)
            .first()
        )

        report.append({
            "patient_id": row.patient_id,
            "patient_name": patient.full_name if patient else None,
            "no_show_count": row.no_show_count,
        })

    return report
