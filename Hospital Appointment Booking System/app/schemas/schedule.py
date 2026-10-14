from datetime import datetime, time

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScheduleCreate(BaseModel):
    doctor_id: int = Field(..., gt=0)
    day_of_week: int = Field(..., ge=0, le=6)
    start_time: time
    end_time: time
    break_start: time | None = None
    break_end: time | None = None

    @model_validator(mode="after")
    def validate_schedule(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")

        if (self.break_start is None) != (self.break_end is None):
            raise ValueError("Provide both break_start and break_end")

        if self.break_start is not None:
            if not (
                self.start_time < self.break_start
                < self.break_end < self.end_time
            ):
                raise ValueError("Break must be inside the working hours")

        return self


class ScheduleUpdate(BaseModel):
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    start_time: time | None = None
    end_time: time | None = None
    break_start: time | None = None
    break_end: time | None = None


class ScheduleResponse(BaseModel):
    id: int
    doctor_id: int
    day_of_week: int
    start_time: time
    end_time: time
    break_start: time | None
    break_end: time | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)