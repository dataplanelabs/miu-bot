"""FastAPI application factory for the miu_bot gateway."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI

if TYPE_CHECKING:
    from miu_bot.bus.queue import MessageBus
    from miu_bot.db.backend import MemoryBackend


def create_app(
    backend: "MemoryBackend",
    bus: "MessageBus | None" = None,
) -> FastAPI:
    """Create the FastAPI application with routes mounted."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield

    app = FastAPI(title="miubot Gateway", lifespan=lifespan)

    from miu_bot.gateway.routes.admin import router as admin_router
    from miu_bot.gateway.routes.internal import router as internal_router
    from miu_bot.gateway.routes.health import router as health_router

    app.include_router(admin_router, prefix="/api")
    app.include_router(internal_router, prefix="/internal")
    app.include_router(health_router)

    app.state.backend = backend
    app.state.bus = bus

    return app
