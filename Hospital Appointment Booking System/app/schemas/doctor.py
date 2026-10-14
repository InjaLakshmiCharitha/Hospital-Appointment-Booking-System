from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class DoctorCreate(BaseModel):
    user_id: int = Field(..., gt=0)
    name: str = Field(..., min_length=2, max_length=100)
    department_id: int = Field(..., gt=0)
    specialization: str = Field(..., min_length=2, max_length=100)
    qualification: str = Field(..., min_length=2, max_length=150)
    experience_years: int = Field(..., ge=0)
    consultation_fee: Decimal = Field(..., gt=0)
    slot_duration_minutes: int = Field(default=15)


class DoctorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    department_id: int | None = Field(default=None, gt=0)
    specialization: str | None = Field(default=None, min_length=2, max_length=100)
    qualification: str | None = Field(default=None, min_length=2, max_length=150)
    experience_years: int | None = Field(default=None, ge=0)
    consultation_fee: Decimal | None = Field(default=None, gt=0)
    slot_duration_minutes: int | None = None
    is_active: bool | None = None


class DoctorResponse(BaseModel):
    id: int
    user_id: int
    name: str
    department_id: int
    specialization: str
    qualification: str
    experience_years: int
    consultation_fee: Decimal
    slot_duration_minutes: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)