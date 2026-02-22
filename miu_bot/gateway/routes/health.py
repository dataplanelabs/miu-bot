"""Health check endpoint."""

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health(request: Request):
    backend = request.app.state.backend
    db_ok = True
    if hasattr(backend, "health_check"):
        db_ok = await backend.health_check()
    return {"status": "ok" if db_ok else "degraded", "db": db_ok}
