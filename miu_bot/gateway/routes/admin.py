"""Admin REST API for workspace CRUD."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel


async def _verify_admin_key(x_admin_key: str = Header(default="")) -> None:
    expected = os.environ.get("MIU_BOT_ADMIN_KEY")
    if not expected:
        return  # No key configured — allow (dev mode)
    if x_admin_key != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


router = APIRouter(dependencies=[Depends(_verify_admin_key)])


class CreateWorkspaceRequest(BaseModel):
    name: str
    identity: str = ""
    config_overrides: dict[str, Any] = {}


class UpdateWorkspaceRequest(BaseModel):
    config_overrides: dict[str, Any] | None = None
    status: str | None = None
    identity: str | None = None


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    status: str
    identity: str
    config_overrides: dict[str, Any]
    created_at: str
    updated_at: str


def _ws_to_response(ws) -> WorkspaceResponse:
    return WorkspaceResponse(
        id=ws.id, name=ws.name, status=ws.status,
        identity=ws.identity, config_overrides=ws.config_overrides,
        created_at=ws.created_at.isoformat(), updated_at=ws.updated_at.isoformat(),
    )


@router.get("/workspaces")
async def list_workspaces(request: Request):
    from miu_bot.workspace.service import WorkspaceService
    svc = WorkspaceService(request.app.state.backend)
    workspaces = await svc.list()
    return [_ws_to_response(ws) for ws in workspaces]


@router.post("/workspaces", status_code=201)
async def create_workspace(req: CreateWorkspaceRequest, request: Request):
    from miu_bot.workspace.service import WorkspaceService
    svc = WorkspaceService(request.app.state.backend)
    ws = await svc.create(req.name, identity_text=req.identity, config_overrides=req.config_overrides)
    return _ws_to_response(ws)


@router.get("/workspaces/{name}")
async def get_workspace(name: str, request: Request):
    from miu_bot.workspace.service import WorkspaceService
    svc = WorkspaceService(request.app.state.backend)
    ws = await svc.get(name)
    if not ws:
        raise HTTPException(status_code=404, detail=f"Workspace '{name}' not found")
    return _ws_to_response(ws)


@router.patch("/workspaces/{name}")
async def update_workspace(name: str, req: UpdateWorkspaceRequest, request: Request):
    from miu_bot.workspace.service import WorkspaceService
    svc = WorkspaceService(request.app.state.backend)
    ws = await svc.get(name)
    if not ws:
        raise HTTPException(status_code=404, detail=f"Workspace '{name}' not found")

    kwargs = {}
    if req.config_overrides is not None:
        kwargs["config_overrides"] = req.config_overrides
    if req.status is not None:
        kwargs["status"] = req.status
    if req.identity is not None:
        kwargs["identity"] = req.identity

    backend = request.app.state.backend
    updated = await backend.update_workspace(ws.id, **kwargs)
    if not updated:
        raise HTTPException(status_code=500, detail="Update failed")
    return _ws_to_response(updated)


@router.delete("/workspaces/{name}")
async def delete_workspace(name: str, request: Request):
    from miu_bot.workspace.service import WorkspaceService
    svc = WorkspaceService(request.app.state.backend)
    if not await svc.delete(name):
        raise HTTPException(status_code=404, detail=f"Workspace '{name}' not found")
    return {"status": "deleted"}
