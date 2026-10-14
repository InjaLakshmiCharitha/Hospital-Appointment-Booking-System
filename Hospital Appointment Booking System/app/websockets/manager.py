
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.active_connections = {}
        self.connection_metadata = {}

    async def connect(self, websocket: WebSocket, room: str, metadata=None):
        await websocket.accept()

        if room not in self.active_connections:
            self.active_connections[room] = []

        self.active_connections[room].append(websocket)
        self.connection_metadata[websocket] = metadata or {}

    def disconnect(self, websocket: WebSocket, room: str):
        if room in self.active_connections:
            if websocket in self.active_connections[room]:
                self.active_connections[room].remove(websocket)

            if not self.active_connections[room]:
                del self.active_connections[room]

        self.connection_metadata.pop(websocket, None)

    def get_connections(self, room: str):
        return [
            (connection, self.connection_metadata.get(connection, {}))
            for connection in self.active_connections.get(room, []).copy()
        ]

    async def broadcast(self, room: str, message: dict):
        connections = self.active_connections.get(room, [])

        for connection in connections.copy():
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection, room)


manager = ConnectionManager()

