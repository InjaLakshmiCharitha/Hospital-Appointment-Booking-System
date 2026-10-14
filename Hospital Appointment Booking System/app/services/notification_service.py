from app.websockets.manager import manager


async def send_user_notification(user_id: int, message: dict):
    await manager.broadcast(
        f"notifications:{user_id}",
        message,
    )


async def send_appointment_notification(
    patient_id: int,
    doctor_user_id: int,
    message: dict,
):
    notification = {
        "type": "appointment_notification",
        **message,
    }

    await send_user_notification(patient_id, notification)
    await send_user_notification(doctor_user_id, notification)
