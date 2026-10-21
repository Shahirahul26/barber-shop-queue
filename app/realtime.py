from collections import defaultdict
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, shop_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections[shop_id].add(websocket)

    def disconnect(self, shop_id: int, websocket: WebSocket) -> None:
        self.connections[shop_id].discard(websocket)

    async def queue_changed(self, shop_id: int) -> None:
        stale: list[WebSocket] = []
        for websocket in self.connections[shop_id]:
            try:
                await websocket.send_json({"type": "queue.changed", "shop_id": shop_id})
            except RuntimeError:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(shop_id, websocket)


manager = ConnectionManager()
