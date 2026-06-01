import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from bot.api.routes import router
from bot.api.sse import SSEBroadcaster
from bot.core.engine import Engine
from bot.utils.logging import get_log_queue

_BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", "."))
_DIST = _BUNDLE_DIR / "frontend" / "dist"


def create_app(engine: Engine) -> FastAPI:
    log_broadcaster = SSEBroadcaster()
    status_broadcaster = SSEBroadcaster()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        asyncio.create_task(log_broadcaster.run(get_log_queue()))
        asyncio.create_task(status_broadcaster.run(engine.status_queue))
        engine.api_ready.set()
        yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)

    # Dev CORS: allow Vite dev server (ignored in production — no :5173 requests)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.engine = engine
    app.state.log_broadcaster = log_broadcaster
    app.state.status_broadcaster = status_broadcaster

    app.include_router(router)

    # Serve bundled frontend in production; skipped when dist/ doesn't exist (dev mode)
    if _DIST.exists():
        app.mount("/", StaticFiles(directory=_DIST, html=True), name="static")

    return app
