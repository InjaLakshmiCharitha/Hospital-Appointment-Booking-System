
from pydantic import BaseModel, ConfigDict, Field


class RatingCreate(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    feedback: str | None = Field(default=None, max_length=1000)


class RatingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    appointment_id: int
    patient_id: int
    doctor_id: int
    rating: int
    feedback: str | None = None
