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
