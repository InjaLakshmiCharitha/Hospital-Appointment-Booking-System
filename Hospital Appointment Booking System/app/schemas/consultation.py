
from datetime import date

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)


class ConsultationCreate(BaseModel):
    symptoms: str = Field(
        ...,
        min_length=2,
        max_length=2000,
    )
    diagnosis: str = Field(
        ...,
        min_length=2,
        max_length=2000,
    )
    prescription: str = Field(
        ...,
        min_length=1,
        max_length=3000,
    )
    advice: str | None = Field(
        default=None,
        max_length=2000,
    )
    follow_up_date: date | None = None

    @field_validator(
        "symptoms",
        "diagnosis",
        "prescription",
    )
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("This field cannot be empty")

        return value

    @field_validator("advice")
    @classmethod
    def validate_advice(
        cls,
        value: str | None,
    ) -> str | None:
        if value is not None:
            value = value.strip()

            if not value:
                return None

        return value


class ConsultationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    appointment_id: int
    symptoms: str
    diagnosis: str
    prescription: str
    advice: str | None = None
    follow_up_date: date | None = None

