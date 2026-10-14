
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.models import Appointment, UploadedFile, UserRole
from app.schemas.file import UploadedFileResponse
from app.utils.utils import (
    MAX_FILE_SIZE,
    validate_file_extension,
    validate_file_size,
    validate_file_content,
    generate_unique_filename,
)

router = APIRouter(tags=["Files"])

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def role_value(user):
    """Return the user's role as a string."""
    return user.role.value if hasattr(user.role, "value") else user.role


def check_file_access(appointment, current_user):
    """Allow access only to the appointment's patient, doctor, or an admin."""
    role = role_value(current_user)

    if role == UserRole.ADMIN.value:
        return True

    if role == UserRole.PATIENT.value:
        return appointment.patient_id == current_user.id

    if role == UserRole.DOCTOR.value:
        doctor = current_user.doctor_profile

        return (
            doctor is not None
            and appointment.doctor_id == doctor.id
        )

    return False


@router.post(
    "/appointments/{appointment_id}/files",
    response_model=UploadedFileResponse,
    status_code=201,
)
async def upload_appointment_file(
    appointment_id: int,
    file_type: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Upload an appointment-related PDF, JPG, or PNG file."""

    appointment = (
        db.query(Appointment)
        .filter(Appointment.id == appointment_id)
        .first()
    )

    if not appointment:
        raise HTTPException(
            status_code=404,
            detail="Appointment not found",
        )

    role = role_value(current_user)

    if not check_file_access(appointment, current_user):
        raise HTTPException(
            status_code=403,
            detail="Access denied",
        )

    if role == UserRole.PATIENT.value and file_type != "Lab Report":
        raise HTTPException(
            status_code=403,
            detail="Patients can upload only lab reports",
        )

    if role == UserRole.DOCTOR.value and file_type not in {
        "Prescription",
        "Scan",
    }:
        raise HTTPException(
            status_code=403,
            detail="Doctors can upload only prescriptions or scans",
        )

    if role not in {
        UserRole.PATIENT.value,
        UserRole.DOCTOR.value,
        UserRole.ADMIN.value,
    }:
        raise HTTPException(
            status_code=403,
            detail="Access denied",
        )

    # Validate file extension.
    try:
        extension = validate_file_extension(file.filename or "")
    except ValueError as exc:
        raise HTTPException(
            status_code=415,
            detail=str(exc),
        ) from exc

    # Read at most 5 MB plus one byte to detect oversized files.
    try:
        content = await file.read(MAX_FILE_SIZE + 1)

        validate_file_size(content)

        validate_file_content(content, extension)

    except OverflowError as exc:
        raise HTTPException(
            status_code=413,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        status_code = 400 if not content else 415

        raise HTTPException(
            status_code=status_code,
            detail=str(exc),
        ) from exc

    stored_name = generate_unique_filename(extension)
    file_path = UPLOAD_DIR / stored_name

    try:
        file_path.write_bytes(content)

        uploaded = UploadedFile(
            appointment_id=appointment.id,
            uploaded_by=current_user.id,
            file_type=file_type,
            original_name=Path(file.filename or "upload").name,
            stored_name=stored_name,
            size_kb=round(len(content) / 1024, 2),
        )

        db.add(uploaded)
        db.commit()
        db.refresh(uploaded)

        return uploaded

    except Exception as exc:
        db.rollback()

        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            pass

        raise HTTPException(
            status_code=500,
            detail="File upload failed",
        ) from exc

    finally:
        await file.close()


@router.get(
    "/appointments/{appointment_id}/files",
    response_model=list[UploadedFileResponse],
)
def list_appointment_files(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List files belonging to an appointment."""

    appointment = (
        db.query(Appointment)
        .filter(Appointment.id == appointment_id)
        .first()
    )

    if not appointment:
        raise HTTPException(
            status_code=404,
            detail="Appointment not found",
        )

    if not check_file_access(appointment, current_user):
        raise HTTPException(
            status_code=403,
            detail="Access denied",
        )

    return (
        db.query(UploadedFile)
        .filter(UploadedFile.appointment_id == appointment_id)
        .all()
    )


@router.get("/files/{file_id}/download")
def download_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Download an uploaded file if the user has permission."""

    uploaded = (
        db.query(UploadedFile)
        .filter(UploadedFile.id == file_id)
        .first()
    )

    if not uploaded:
        raise HTTPException(
            status_code=404,
            detail="File not found",
        )

    appointment = (
        db.query(Appointment)
        .filter(Appointment.id == uploaded.appointment_id)
        .first()
    )

    if not appointment or not check_file_access(
        appointment, current_user
    ):
        raise HTTPException(
            status_code=403,
            detail="Access denied",
        )

    file_path = UPLOAD_DIR / uploaded.stored_name

    if not file_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Stored file not found",
        )

    return FileResponse(
        path=file_path,
        filename=uploaded.original_name,
        media_type="application/octet-stream",
    )


