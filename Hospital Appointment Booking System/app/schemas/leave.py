from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class LeaveCreate(BaseModel):
    doctor_id: int = Field(..., gt=0)
    leave_date: date
    reason: str | None = Field(default=None, max_length=255)


class LeaveResponse(BaseModel):
    id: int
    doctor_id: int
    leave_date: date
    reason: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)