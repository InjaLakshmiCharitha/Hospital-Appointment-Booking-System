from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.auth.security import decode_token
from app.database import SessionLocal
from app.models.models import User
from app.websockets.manager import manager


router = APIRouter(tags=["Notifications"])


@router.websocket("/ws/notifications")
async def notifications_websocket(
    websocket: WebSocket,
    token: str = Query(...),
):
    db = SessionLocal()
    connected = False
    user_id = None

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

        room = f"notifications:{user.id}"

        await manager.connect(websocket, room)
        connected = True

        await websocket.send_json({
            "type": "connected",
            "message": "Personal notifications connected successfully.",
        })

        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        pass

    except Exception:
        try:
            await websocket.close(code=1008)
        except Exception:
            pass

    finally:
        if connected and user_id is not None:
            manager.disconnect(websocket, f"notifications:{user_id}")

        db.close()
