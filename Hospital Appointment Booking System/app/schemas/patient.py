
from datetime import date, datetime, time
from pydantic import BaseModel, ConfigDict
from app.schemas.file import UploadedFileResponse


class PatientHistoryItem(BaseModel):
    appointment_id: int
    appointment_number: str
    doctor_id: int
    appointment_date: date
    slot_time: time
    status: str
    diagnosis: str | None = None
    files: list[UploadedFileResponse] = []

    model_config = ConfigDict(from_attributes=True)
