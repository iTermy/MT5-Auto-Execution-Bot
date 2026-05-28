import asyncio
import json


class SSEBroadcaster:
    """Fans out messages from a single source queue to all connected SSE clients."""

    def __init__(self) -> None:
        self._clients: set[asyncio.Queue] = set()
        self.last_msg: dict | None = None

    def add_client(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._clients.add(q)
        return q

    def remove_client(self, q: asyncio.Queue) -> None:
        self._clients.discard(q)

    async def broadcast(self, data: dict) -> None:
        self.last_msg = data
        for q in list(self._clients):
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                pass

    async def run(self, source: asyncio.Queue) -> None:
        """Drain source queue forever and fan out to all connected clients."""
        while True:
            msg = await source.get()
            await self.broadcast(msg)

    def make_generator(self, event_type: str):
        """Return an async generator for use with EventSourceResponse."""
        client_q = self.add_client()

        async def _gen():
            try:
                while True:
                    try:
                        msg = await asyncio.wait_for(client_q.get(), timeout=15)
                        yield {"event": event_type, "data": json.dumps(msg)}
                    except asyncio.TimeoutError:
                        yield {"event": "heartbeat", "data": ""}
            finally:
                self.remove_client(client_q)

        return _gen()
