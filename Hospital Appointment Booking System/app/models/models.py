from datetime import date, datetime, time
from enum import Enum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SQLAlchemyEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UserRole(str, Enum):
    ADMIN = "admin"
    DOCTOR = "doctor"
    PATIENT = "patient"


class AppointmentStatus(str, Enum):
    BOOKED = "Booked"
    CHECKED_IN = "Checked-In"
    IN_CONSULTATION = "In Consultation"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"
    NO_SHOW = "No-Show"


class FileType(str, Enum):
    LAB_REPORT = "Lab Report"
    PRESCRIPTION = "Prescription"
    SCAN = "Scan"


class Department(TimestampMixin, Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    doctors: Mapped[list["Doctor"]] = relationship(back_populates="department")


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(10), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SQLAlchemyEnum(UserRole, values_callable=lambda enum: [item.value for item in enum]),
        nullable=False,
        default=UserRole.PATIENT,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    doctor_profile: Mapped["Doctor | None"] = relationship(
        back_populates="user", uselist=False
    )
    patient_appointments: Mapped[list["Appointment"]] = relationship(
        back_populates="patient",
        foreign_keys="Appointment.patient_id",
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user"
    )


class Doctor(TimestampMixin, Base):
    __tablename__ = "doctors"
    __table_args__ = (
        CheckConstraint("experience_years >= 0", name="ck_doctor_experience_nonnegative"),
        CheckConstraint("consultation_fee > 0", name="ck_doctor_fee_positive"),
        CheckConstraint(
            "slot_duration_minutes IN (10, 15, 20, 30)",
            name="ck_doctor_slot_duration",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), nullable=False)
    specialization: Mapped[str] = mapped_column(String(100), nullable=False)
    qualification: Mapped[str] = mapped_column(String(150), nullable=False)
    experience_years: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consultation_fee: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    slot_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped["User"] = relationship(back_populates="doctor_profile")
    department: Mapped["Department"] = relationship(back_populates="doctors")
    schedules: Mapped[list["DoctorSchedule"]] = relationship(
        back_populates="doctor", cascade="all, delete-orphan"
    )
    leaves: Mapped[list["DoctorLeave"]] = relationship(
        back_populates="doctor", cascade="all, delete-orphan"
    )
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="doctor")


class DoctorSchedule(TimestampMixin, Base):
    __tablename__ = "doctor_schedules"
    __table_args__ = (
        CheckConstraint("end_time > start_time", name="ck_schedule_end_after_start"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"), nullable=False)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    break_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    break_end: Mapped[time | None] = mapped_column(Time, nullable=True)

    doctor: Mapped["Doctor"] = relationship(back_populates="schedules")


class DoctorLeave(TimestampMixin, Base):
    __tablename__ = "doctor_leaves"
    __table_args__ = (
        UniqueConstraint("doctor_id", "leave_date", name="uq_doctor_leave_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"), nullable=False)
    leave_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    doctor: Mapped["Doctor"] = relationship(back_populates="leaves")


class Appointment(TimestampMixin, Base):
    __tablename__ = "appointments"
    __table_args__ = (
        UniqueConstraint(
            "doctor_id", "appointment_date", "slot_time",
            name="uq_appointment_doctor_date_slot",
        ),
        UniqueConstraint("appointment_number", name="uq_appointment_number"),
        UniqueConstraint("patient_id", "appointment_date", "slot_time",
                         name="uq_patient_date_slot"),
        CheckConstraint("consultation_fee > 0", name="ck_appointment_fee_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    appointment_number: Mapped[str] = mapped_column(String(30), nullable=False)
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"), nullable=False)
    appointment_date: Mapped[date] = mapped_column(Date, nullable=False)
    slot_time: Mapped[time] = mapped_column(Time, nullable=False)
    token_number: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[AppointmentStatus] = mapped_column(
        SQLAlchemyEnum(
            AppointmentStatus,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=AppointmentStatus.BOOKED,
        nullable=False,
    )
    consultation_fee: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    reschedule_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    patient: Mapped["User"] = relationship(
        back_populates="patient_appointments", foreign_keys=[patient_id]
    )
    doctor: Mapped["Doctor"] = relationship(back_populates="appointments")
    consultation: Mapped["Consultation | None"] = relationship(
        back_populates="appointment", uselist=False
    )
    history: Mapped[list["AppointmentHistory"]] = relationship(
        back_populates="appointment"
    )


class Consultation(TimestampMixin, Base):
    __tablename__ = "consultations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id"), unique=True, nullable=False
    )
    symptoms: Mapped[str] = mapped_column(Text, nullable=False)
    diagnosis: Mapped[str] = mapped_column(Text, nullable=False)
    prescription: Mapped[str | None] = mapped_column(Text, nullable=True)
    advice: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_up_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    appointment: Mapped["Appointment"] = relationship(back_populates="consultation")
    files: Mapped[list["UploadedFile"]] = relationship(back_populates="consultation")
    follow_up_email_sent: Mapped[bool] = mapped_column (Boolean, nullable=False, default=False)

class UploadedFile(TimestampMixin, Base):
    __tablename__ = "uploaded_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id"), nullable=False
    )
    consultation_id: Mapped[int | None] = mapped_column(
        ForeignKey("consultations.id"), nullable=True
    )
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    file_type: Mapped[FileType] = mapped_column(
        SQLAlchemyEnum(FileType, values_callable=lambda enum: [item.value for item in enum]),
        nullable=False,
    )
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    size_kb: Mapped[int] = mapped_column(Integer, nullable=False)

    consultation: Mapped["Consultation | None"] = relationship(back_populates="files")


class RefreshToken(TimestampMixin, Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")


class AppointmentHistory(TimestampMixin, Base):
    __tablename__ = "appointment_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id"), nullable=False
    )
    old_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    new_status: Mapped[str] = mapped_column(String(30), nullable=False)
    changed_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    appointment: Mapped["Appointment"] = relationship(back_populates="history")


class DoctorFeedback(TimestampMixin, Base):
    __tablename__ = "doctor_feedback"
    __table_args__ = (
        UniqueConstraint("appointment_id", name="uq_feedback_appointment"),
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_feedback_rating"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id"), nullable=False
    )
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)


class AppointmentRating(Base):
    __tablename__ = "appointment_ratings"

    id = mapped_column(Integer, primary_key=True, index=True)
    appointment_id = mapped_column(
        Integer,
        ForeignKey("appointments.id"),
        unique=True,
        nullable=False,
    )
    patient_id = mapped_column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
    )
    doctor_id = mapped_column(
        Integer,
        ForeignKey("doctors.id"),
        nullable=False,
    )
    rating = mapped_column(Integer, nullable=False)
    feedback = mapped_column(String(1000), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "rating >= 1 AND rating <= 5",
            name="check_appointment_rating_1_to_5",
        ),
    )