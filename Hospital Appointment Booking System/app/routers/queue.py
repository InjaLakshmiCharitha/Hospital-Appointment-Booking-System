
from datetime import date
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.security import decode_token
from app.database import SessionLocal, get_db
from app.models.models import (
    Appointment,
    AppointmentHistory,
    AppointmentStatus,
    Doctor,
    User,
    UserRole,
)
from app.services.notification_service import send_appointment_notification
from app.websockets.manager import manager


router = APIRouter(tags=["Live Queue"])


def role_value(user):
    return user.role.value if hasattr(user.role, "value") else user.role


def get_doctor_for_user(db: Session, user_id: int):
    return db.query(Doctor).filter(Doctor.user_id == user_id).first()


def queue_data(
    db: Session,
    doctor_id: int,
    queue_date: date,
    patient_id: Optional[int] = None,
):
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()

    if not doctor:
        return {
            "doctor_id": doctor_id,
            "date": str(queue_date),
            "current_token": None,
            "waiting_count": 0,
            "your_token": None,
            "your_position": None,
            "estimated_wait_minutes": None,
            "is_next": None,
            "slot_duration_minutes": None,
            "queue": [],
        }

    appointments = (
        db.query(Appointment)
        .filter(
            Appointment.doctor_id == doctor_id,
            Appointment.appointment_date == queue_date,
            Appointment.status.in_(
                [
                    AppointmentStatus.CHECKED_IN,
                    AppointmentStatus.IN_CONSULTATION,
                ]
            ),
        )
        .order_by(
            Appointment.token_number,
            Appointment.slot_time,
        )
        .all()
    )

    current = next(
        (
            appointment
            for appointment in appointments
            if appointment.status == AppointmentStatus.IN_CONSULTATION
        ),
        None,
    )

    waiting = [
        appointment
        for appointment in appointments
        if appointment.status == AppointmentStatus.CHECKED_IN
    ]

    your_appointment = next(
        (
            appointment
            for appointment in appointments
            if patient_id is not None
            and appointment.patient_id == patient_id
        ),
        None,
    )

    your_position = None
    estimated_wait = None
    your_token = None
    is_next = None

    if your_appointment:
        your_token = your_appointment.token_number

        if your_appointment.status == AppointmentStatus.IN_CONSULTATION:
            your_position = 0
            estimated_wait = 0
            is_next = False
        else:
            patients_ahead = sum(
                1
                for appointment in waiting
                if appointment.token_number < your_appointment.token_number
            )

            your_position = patients_ahead + 1
            estimated_wait = (
                patients_ahead * doctor.slot_duration_minutes
            )
            is_next = your_position == 1

    return {
        "doctor_id": doctor_id,
        "date": str(queue_date),
        "current_token": current.token_number if current else None,
        "waiting_count": len(waiting),
        "your_token": your_token,
        "your_position": your_position,
        "estimated_wait_minutes": estimated_wait,
        "is_next": is_next,
        "slot_duration_minutes": doctor.slot_duration_minutes,
        "queue": [
            {
                "token_number": appointment.token_number,
                "status": (
                    appointment.status.value
                    if hasattr(appointment.status, "value")
                    else appointment.status
                ),
            }
            for appointment in appointments
        ],
    }


async def broadcast_queue_update(
    db: Session,
    doctor_id: int,
    queue_date: Optional[date] = None,
):
    selected_date = queue_date or date.today()
    room = f"queue:{doctor_id}"

    for connection, metadata in manager.get_connections(room):
        try:
            patient_id = metadata.get("patient_id")

            payload = queue_data(
                db,
                doctor_id,
                selected_date,
                patient_id,
            )

            await connection.send_json(
                {
                    "type": "queue_update",
                    **payload,
                }
            )
        except Exception:
            manager.disconnect(connection, room)


@router.get("/doctors/{doctor_id}/queue")
def get_live_queue(
    doctor_id: int,
    queue_date: date = Query(default_factory=date.today),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    role = role_value(current_user)

    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()

    if not doctor:
        raise HTTPException(
            status_code=404,
            detail="Doctor not found",
        )

    if role == UserRole.DOCTOR.value:
        own_doctor = get_doctor_for_user(db, current_user.id)

        if not own_doctor or own_doctor.id != doctor_id:
            raise HTTPException(
                status_code=403,
                detail="Access denied",
            )

    elif role not in {
        UserRole.PATIENT.value,
        UserRole.ADMIN.value,
    }:
        raise HTTPException(
            status_code=403,
            detail="Access denied",
        )

    patient_id = (
        current_user.id
        if role == UserRole.PATIENT.value
        else None
    )

    return queue_data(
        db,
        doctor_id,
        queue_date,
        patient_id,
    )


@router.websocket("/ws/queue/{doctor_id}")
async def queue_websocket(
    websocket: WebSocket,
    doctor_id: int,
    token: str = Query(...),
):
    room = f"queue:{doctor_id}"
    db = SessionLocal()
    connected = False

    try:
        payload = decode_token(token)

        if not payload or payload.get("type") != "access":
            await websocket.close(code=1008)
            return

        subject = payload.get("sub")

        if not subject or not str(subject).isdigit():
            await websocket.close(code=1008)
            return

        user_id = int(subject)
        user = db.query(User).filter(User.id == user_id).first()

        if not user or not user.is_active:
            await websocket.close(code=1008)
            return

        doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()

        if not doctor:
            await websocket.close(code=1008)
            return

        role = role_value(user)

        if role == UserRole.DOCTOR.value:
            own_doctor = get_doctor_for_user(db, user.id)

            if not own_doctor or own_doctor.id != doctor_id:
                await websocket.close(code=1008)
                return

        elif role not in {
            UserRole.PATIENT.value,
            UserRole.ADMIN.value,
        }:
            await websocket.close(code=1008)
            return

        patient_id = (
            user.id
            if role == UserRole.PATIENT.value
            else None
        )

        await manager.connect(
            websocket,
            room,
            metadata={
                "user_id": user.id,
                "role": role,
                "patient_id": patient_id,
            },
        )
        connected = True

        await websocket.send_json(
            {
                "type": "queue_update",
                **queue_data(
                    db,
                    doctor_id,
                    date.today(),
                    patient_id,
                ),
            }
        )

        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        pass

    except Exception:
        if connected:
            manager.disconnect(websocket, room)
            connected = False
        else:
            try:
                await websocket.close(code=1008)
            except Exception:
                pass

    finally:
        if connected:
            manager.disconnect(websocket, room)

        db.close()


@router.put("/doctors/me/call-next")
async def call_next_patient(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if role_value(current_user) != UserRole.DOCTOR.value:
        raise HTTPException(
            status_code=403,
            detail="Only doctors can call the next patient",
        )

    doctor = get_doctor_for_user(db, current_user.id)

    if not doctor:
        raise HTTPException(
            status_code=404,
            detail="Doctor profile not found",
        )

    current_appointment = (
        db.query(Appointment)
        .filter(
            Appointment.doctor_id == doctor.id,
            Appointment.appointment_date == date.today(),
            Appointment.status == AppointmentStatus.IN_CONSULTATION,
        )
        .first()
    )

    if current_appointment:
        raise HTTPException(
            status_code=409,
            detail=(
                "Complete the current consultation before "
                "calling the next patient"
            ),
        )

    try:
        next_appointment = (
            db.query(Appointment)
            .filter(
                Appointment.doctor_id == doctor.id,
                Appointment.appointment_date == date.today(),
                Appointment.status == AppointmentStatus.CHECKED_IN,
            )
            .order_by(
                Appointment.token_number,
                Appointment.slot_time,
            )
            .with_for_update()
            .first()
        )

        if not next_appointment:
            raise HTTPException(
                status_code=404,
                detail="No checked-in patients in the queue",
            )

        old_status = next_appointment.status.value

        next_appointment.status = AppointmentStatus.IN_CONSULTATION

        db.add(
            AppointmentHistory(
                appointment_id=next_appointment.id,
                old_status=old_status,
                new_status=AppointmentStatus.IN_CONSULTATION.value,
                changed_by=current_user.id,
            )
        )

        db.commit()
        db.refresh(next_appointment)

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        raise

    message = {
        "type": "patient_called",
        "doctor_id": doctor.id,
        "appointment_id": next_appointment.id,
        "token_number": next_appointment.token_number,
        "appointment_number": next_appointment.appointment_number,
        "message": "You are next, please be ready.",
    }

    await send_appointment_notification(
        patient_id=next_appointment.patient_id,
        doctor_user_id=doctor.user_id,
        message={
            "event": "patient_called",
            "appointment_id": next_appointment.id,
            "token_number": next_appointment.token_number,
            "appointment_number": next_appointment.appointment_number,
            "message": "You are next, please be ready.",
        },
    )

    await broadcast_queue_update(
        db,
        doctor.id,
        date.today(),
    )

    return message


    
