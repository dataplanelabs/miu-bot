"""Zalo tool for bridge-specific operations (reminders, etc.)."""

import asyncio
import json
from typing import Any, Callable, Awaitable

from miu_bot.agent.tools.base import Tool


class ZaloTool(Tool):
    """Tool for Zalo-specific bridge operations like reminders."""

    def __init__(
        self,
        send_and_wait: Callable[[dict, str], Awaitable[dict]] | None = None,
    ):
        self._send_and_wait = send_and_wait
        self._channel = ""
        self._chat_id = ""
        self._thread_type = 1

    def set_context(self, channel: str, chat_id: str, thread_type: int = 1) -> None:
        """Set current session context."""
        self._channel = channel
        self._chat_id = chat_id
        self._thread_type = thread_type

    @property
    def name(self) -> str:
        return "zalo"

    @property
    def description(self) -> str:
        return (
            "Manage Zalo-native reminders. Actions: create_reminder, list_reminders, "
            "remove_reminder. Reminders appear in Zalo UI with push notifications."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create_reminder", "list_reminders", "remove_reminder"],
                    "description": "Action to perform",
                },
                "title": {
                    "type": "string",
                    "description": "Reminder title (for create_reminder)",
                },
                "time": {
                    "type": "string",
                    "description": "ISO 8601 datetime for reminder (e.g. '2026-02-24T10:00:00Z')",
                },
                "thread_id": {
                    "type": "string",
                    "description": "Target thread ID (defaults to current chat)",
                },
                "thread_type": {
                    "type": "integer",
                    "description": "1=user, 2=group (defaults to current context)",
                },
                "reminder_id": {
                    "type": "string",
                    "description": "Reminder ID (for remove_reminder)",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str,
        title: str = "",
        time: str = "",
        thread_id: str = "",
        thread_type: int | None = None,
        reminder_id: str = "",
        **kwargs: Any,
    ) -> str:
        if self._channel != "zalo":
            return "Error: zalo tool only works on the Zalo channel"
        if not self._send_and_wait:
            return "Error: Zalo bridge not configured"

        tid = thread_id or self._chat_id
        tt = thread_type if thread_type is not None else self._thread_type

        if action == "create_reminder":
            return await self._create_reminder(tid, tt, title, time)
        elif action == "list_reminders":
            return await self._list_reminders(tid, tt)
        elif action == "remove_reminder":
            return await self._remove_reminder(tid, tt, reminder_id)
        return f"Unknown action: {action}"

    async def _create_reminder(self, tid: str, tt: int, title: str, time: str) -> str:
        if not title:
            return "Error: title is required for create_reminder"
        cmd: dict[str, Any] = {
            "type": "create-reminder",
            "threadId": tid,
            "title": title,
            "threadType": tt,
        }
        if time:
            cmd["time"] = time
        resp = await self._send_and_wait(cmd, "reminder-created")
        if resp.get("type") == "error":
            return f"Error: {resp.get('error')}"
        return f"Reminder created: {title}" + (f" at {time}" if time else "")

    async def _list_reminders(self, tid: str, tt: int) -> str:
        cmd = {"type": "list-reminders", "threadId": tid, "threadType": tt}
        resp = await self._send_and_wait(cmd, "reminders")
        if resp.get("type") == "error":
            return f"Error: {resp.get('error')}"
        reminders = resp.get("reminders", [])
        if not reminders:
            return "No reminders found."
        lines = []
        for r in reminders:
            rid = r.get("id", r.get("reminderId", "?"))
            rtitle = r.get("title", r.get("content", "?"))
            lines.append(f"- {rtitle} (id: {rid})")
        return "Reminders:\n" + "\n".join(lines)

    async def _remove_reminder(self, tid: str, tt: int, reminder_id: str) -> str:
        if not reminder_id:
            return "Error: reminder_id is required for remove_reminder"
        cmd = {
            "type": "remove-reminder",
            "reminderId": reminder_id,
            "threadId": tid,
            "threadType": tt,
        }
        resp = await self._send_and_wait(cmd, "reminder-removed")
        if resp.get("type") == "error":
            return f"Error: {resp.get('error')}"
        return f"Reminder {reminder_id} removed."
