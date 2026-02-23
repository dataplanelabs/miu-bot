"""Internal endpoints for worker-to-gateway communication."""

import os

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel


async def _verify_internal_key(x_internal_key: str = Header(default="")) -> None:
    expected = os.environ.get("MIU_BOT_INTERNAL_KEY")
    if not expected:
        return  # No key configured — allow (dev/localhost)
    if x_internal_key != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


router = APIRouter(dependencies=[Depends(_verify_internal_key)])


class SendRequest(BaseModel):
    channel: str
    chat_id: str
    content: str
    metadata: dict = {}
    bot_name: str = ""


@router.post("/send")
async def send_message(req: SendRequest, request: Request):
    """Receive a response from a worker and dispatch to the channel."""
    from miu_bot.bus.events import OutboundMessage

    bus = request.app.state.bus
    if not bus:
        return {"status": "error", "message": "no message bus configured"}

    await bus.publish_outbound(OutboundMessage(
        channel=req.channel,
        chat_id=req.chat_id,
        content=req.content,
        metadata=req.metadata,
        bot_name=req.bot_name,
    ))
    return {"status": "ok"}


class ZaloCommandRequest(BaseModel):
    bot_name: str
    cmd: dict
    expected_type: str


@router.post("/zalo/command")
async def zalo_command(req: ZaloCommandRequest, request: Request):
    """Proxy a Zalo bridge command from worker to the gateway's ZaloChannel."""
    bot_mgr = getattr(request.app.state, "bot_mgr", None)
    if not bot_mgr:
        raise HTTPException(status_code=503, detail="No bot manager available")

    from miu_bot.channels.zalo import ZaloChannel

    key = f"{req.bot_name}:zalo"
    channel = bot_mgr.channels.get(key)
    if not channel or not isinstance(channel, ZaloChannel):
        raise HTTPException(status_code=404, detail=f"Zalo channel '{key}' not found")

    result = await channel.send_and_wait(req.cmd, req.expected_type)
    return result
