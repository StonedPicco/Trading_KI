"""FastAPI application: REST + WebSocket push. Analysis only – no order execution exists."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.container import Container, build_container
from app.core.config import PROJECT_ROOT, Settings, get_settings
from app.core.errors import AppError, ProviderError
from app.core.jsonsafe import to_jsonable
from app.core.logging import configure_logging
from app.db import repositories as repo
from app.services.watchlist import ensure_default_watchlist

log = logging.getLogger(__name__)


class WebSocketHub:
    """Tails the ``events`` outbox table and broadcasts new rows to connected clients."""

    def __init__(self, c: Container, poll_seconds: float = 2.0) -> None:
        self.c = c
        self.poll_seconds = poll_seconds
        self.clients: set[WebSocket] = set()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        async with self.c.db.session() as s:
            self.last_id = await repo.max_event_id(s)
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        while True:
            try:
                async with self.c.db.session() as s:
                    events = await repo.events_after(s, self.last_id)
                for e in events:
                    self.last_id = e.id
                    await self.broadcast(
                        {
                            "id": e.id,
                            "type": e.type,
                            "symbol": e.symbol,
                            "payload": e.payload,
                            "created_at": e.created_at,
                        }
                    )
            except Exception:
                log.exception("outbox tail failed")
            await asyncio.sleep(self.poll_seconds)

    async def broadcast(self, message: dict[str, Any]) -> None:
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_json(to_jsonable(message))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        c = container or build_container(settings)
        if c.db.dialect == "sqlite":
            await c.db.create_all()  # quick-start / tests; PostgreSQL uses Alembic
        await ensure_default_watchlist(c)
        app.state.container = c
        hub = WebSocketHub(c)
        await hub.start()
        app.state.hub = hub
        scheduler = None
        if settings.run_worker_in_api and settings.app_env != "test":
            from app.workers.scheduler import build_scheduler

            scheduler = build_scheduler(c)
            scheduler.start()
        log.info("api started", extra={"provider": c.provider.name, "env": settings.app_env})
        try:
            yield
        finally:
            if scheduler:
                scheduler.shutdown(wait=False)
            await hub.stop()
            await c.aclose()

    app = FastAPI(
        title="AI Stock Trading Intelligence Platform",
        version="0.1.0",
        description="Marktanalysen und Szenarien. Keine Anlageberatung, keine Orderausführung.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    token = settings.api_token.get_secret_value() if settings.api_token else None

    @app.middleware("http")
    async def auth(request: Request, call_next):  # type: ignore[no-untyped-def]
        if token and request.url.path.startswith("/api") and request.url.path != "/api/health":
            header = request.headers.get("authorization", "")
            if not secrets.compare_digest(header, f"Bearer {token}"):
                return JSONResponse({"detail": "unauthorized"}, status_code=401)
        return await call_next(request)

    @app.exception_handler(ProviderError)
    async def provider_error(_: Request, exc: ProviderError) -> JSONResponse:
        return JSONResponse({"detail": str(exc), "provider": exc.provider}, status_code=502)

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    app.include_router(router)

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        if token and not secrets.compare_digest(websocket.query_params.get("token", ""), token):
            await websocket.close(code=4401)
            return
        await websocket.accept()
        hub: WebSocketHub = websocket.app.state.hub
        hub.clients.add(websocket)
        try:
            while True:
                await websocket.receive_text()  # keep-alive / ignore client messages
        except WebSocketDisconnect:
            pass
        finally:
            hub.clients.discard(websocket)

    # One-click start: serve the prebuilt static dashboard (web/, frontend/scripts/build-web.mjs)
    # from the same origin. Mounted last so /api and /ws keep precedence.
    web_dir = PROJECT_ROOT / "web"
    if (web_dir / "index.html").is_file():
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")

    return app


app = create_app()
