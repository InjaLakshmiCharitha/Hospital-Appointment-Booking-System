from datetime import datetime
from pydantic import BaseModel, ConfigDict


class UploadedFileResponse(BaseModel):
    id: int
    appointment_id: int
    uploaded_by: int
    file_type: str
    original_name: str
    stored_name: str
    size_kb: float
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
