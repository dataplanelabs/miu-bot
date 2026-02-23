"""Context builder for assembling agent prompts."""

import base64
import mimetypes
import platform
from pathlib import Path
from typing import Any

from miu_bot.agent.memory import MemoryStore
from miu_bot.agent.skills import SkillsLoader


_ZALO_FORMATTING_RULES = (
    "\n\nFORMATTING RULES (MANDATORY):"
    "\n- Zalo does NOT support markdown. NEVER use: ## headings, **bold**, *italic*, `code`, tables (|---|), or > quotes."
    "\n- Use plain text only: VIET HOA for headings, bullet '-' for lists, '---' for separators."
    "\n- NEVER use emojis as decorative headers. Minimal emoji only if contextually needed."
    "\n- NEVER output tables. Use simple lists instead."
    "\n- Answer directly and concisely."
    "\n\nSENDING MEDIA:"
    "\n- Image: [send-image:https://direct-image-url.jpg]"
    "\n- File: [send-file:/absolute/path/or/https://url]"
    "\n- File with caption: [send-file:/path/to/file|Caption text]"
    "\n- Use send-image for jpg/png/gif/webp; send-file for pdf/zip/docx/etc."
    "\n- IMPORTANT: URLs must be DIRECT image links. Never guess or fabricate URLs."
)

_TELEGRAM_FORMATTING_RULES = (
    "\n\nFORMATTING RULES (MANDATORY — Telegram):"
    "\n- Telegram supports: **bold**, _italic_, `inline code`, ```code blocks```, [links](url), ~~strikethrough~~."
    "\n- Telegram does NOT support markdown tables. NEVER use | column | syntax or table formatting."
    "\n- For tabular/comparison data, use one of these formats instead:"
    "\n  • Labeled list: **Label:** value (one item per line)"
    "\n  • Grouped sections: bold header + indented bullet items"
    "\n  • Code block: ```monospace aligned text``` for small aligned data"
    "\n- Keep messages well-structured with bold headers and bullet lists."
    "\n- No character limit, but prefer concise answers."
)


def _append_session_info(prompt: str, channel: str | None, chat_id: str | None) -> str:
    """Append channel/session info to prompt (shared by all build methods)."""
    if not channel or not chat_id:
        return prompt
    session_info = f"\n\n## Current Session\nChannel: {channel}\nChat ID: {chat_id}"
    if channel == "zalo":
        session_info += _ZALO_FORMATTING_RULES
    elif channel == "telegram":
        session_info += _TELEGRAM_FORMATTING_RULES
    return prompt + session_info


class ContextBuilder:
    """
    Builds the context (system prompt + messages) for the agent.
    
    Assembles bootstrap files, memory, skills, and conversation history
    into a coherent prompt for the LLM.
    """
    
    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md", "IDENTITY.md"]
    
    def __init__(self, workspace: Path | None):
        self.workspace = workspace
        self.memory = MemoryStore(workspace) if workspace else None
        self.skills = SkillsLoader(workspace) if workspace else None
    
    def build_system_prompt(self, skill_names: list[str] | None = None) -> str:
        """
        Build the system prompt from bootstrap files, memory, and skills.
        
        Args:
            skill_names: Optional list of skills to include.
        
        Returns:
            Complete system prompt.
        """
        parts = []
        
        # Core identity
        parts.append(self._get_identity())
        
        # Bootstrap files
        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)
        
        # Memory context
        memory = self.memory.get_memory_context()
        if memory:
            parts.append(f"# Memory\n\n{memory}")
        
        # Skills - progressive loading
        # 1. Always-loaded skills: include full content
        always_skills = self.skills.get_always_skills()
        if always_skills:
            always_content = self.skills.load_skills_for_context(always_skills)
            if always_content:
                parts.append(f"# Active Skills\n\n{always_content}")
        
        # 2. Available skills: only show summary (agent uses read_file to load)
        skills_summary = self.skills.build_skills_summary()
        if skills_summary:
            parts.append(f"""# Skills

The following skills extend your capabilities. To use a skill, read its SKILL.md file using the read_file tool.
Skills with available="false" need dependencies installed first - you can try installing them with apt/brew.

{skills_summary}""")
        
        return "\n\n---\n\n".join(parts)
    
    def _get_identity(self) -> str:
        """Get the core identity section."""
        from datetime import datetime
        import time as _time
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        tz = _time.strftime("%Z") or "UTC"
        workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"
        
        return f"""# miu_bot 🐈

You are miu_bot, a helpful AI assistant. You have access to tools that allow you to:
- Read, write, and edit files
- Execute shell commands
- Search the web and fetch web pages
- Send messages to users on chat channels
- Spawn subagents for complex background tasks

## Current Time
{now} ({tz})

## Runtime
{runtime}

## Workspace
Your workspace is at: {workspace_path}
- Long-term memory: {workspace_path}/memory/MEMORY.md
- History log: {workspace_path}/memory/HISTORY.md (grep-searchable)
- Custom skills: {workspace_path}/skills/{{skill-name}}/SKILL.md

IMPORTANT: When responding to direct questions or conversations, reply directly with your text response.
Only use the 'message' tool when you need to send a message to a specific chat channel (like WhatsApp).
For normal conversation, just respond with text - do not call the message tool.

Always be helpful, accurate, and concise. When using tools, think step by step: what you know, what you need, and why you chose this tool.
When remembering something important, write to {workspace_path}/memory/MEMORY.md
To recall past events, grep {workspace_path}/memory/HISTORY.md"""
    
    def _load_bootstrap_files(self) -> str:
        """Load all bootstrap files from workspace."""
        parts = []
        
        for filename in self.BOOTSTRAP_FILES:
            file_path = self.workspace / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")
        
        return "\n\n".join(parts) if parts else ""
    
    def build_workspace_messages(
        self,
        identity: "IdentityDoc",
        memories: str,
        history: list[dict[str, Any]],
        current_message: str,
        channel: str | None = None,
        chat_id: str | None = None,
        media: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Build messages using workspace identity instead of bootstrap files."""
        from miu_bot.workspace.identity import render_system_prompt
        prompt = render_system_prompt(identity, memories)
        # Add runtime info
        from datetime import datetime
        import time as _time
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        tz = _time.strftime("%Z") or "UTC"
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"
        prompt += f"\n\n## Runtime\nTime: {now} ({tz})\n{runtime}"
        prompt = _append_session_info(prompt, channel, chat_id)

        messages: list[dict[str, Any]] = [{"role": "system", "content": prompt}]
        messages.extend(history)
        user_content = self._build_user_content(current_message, media)
        messages.append({"role": "user", "content": user_content})
        return messages

    def build_workspace_messages_from_prompt(
        self,
        prompt: str,
        history: list[dict[str, Any]],
        current_message: str,
        channel: str | None = None,
        chat_id: str | None = None,
        media: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Build messages using a pre-composed prompt string."""
        from datetime import datetime
        import time as _time
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        tz = _time.strftime("%Z") or "UTC"
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"
        prompt += f"\n\n## Runtime\nTime: {now} ({tz})\n{runtime}"
        prompt = _append_session_info(prompt, channel, chat_id)

        messages: list[dict[str, Any]] = [{"role": "system", "content": prompt}]
        messages.extend(history)
        user_content = self._build_user_content(current_message, media)
        messages.append({"role": "user", "content": user_content})
        return messages

    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        media: list[str] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Build the complete message list for an LLM call.

        Args:
            history: Previous conversation messages.
            current_message: The new user message.
            skill_names: Optional skills to include.
            media: Optional list of local file paths for images/media.
            channel: Current channel (telegram, feishu, etc.).
            chat_id: Current chat/user ID.

        Returns:
            List of messages including system prompt.
        """
        messages = []

        # System prompt
        system_prompt = self.build_system_prompt(skill_names)
        system_prompt = _append_session_info(system_prompt, channel, chat_id)
        messages.append({"role": "system", "content": system_prompt})

        # History
        messages.extend(history)

        # Current message (with optional image attachments)
        user_content = self._build_user_content(current_message, media)
        messages.append({"role": "user", "content": user_content})

        return messages

    def _build_user_content(self, text: str, media: list[str] | None) -> str | list[dict[str, Any]]:
        """Build user message content with optional base64-encoded images.

        Currently reads from local file paths. SeaweedFS keys are stored in
        message metadata for persistence; local files still exist during
        processing so no remote fetch is needed yet.
        TODO: fetch from SeaweedFS when local file is missing (distributed worker mode).
        """
        if not media:
            return text

        images = []
        for path in media:
            p = Path(path)
            mime, _ = mimetypes.guess_type(path)
            if not p.is_file() or not mime or not mime.startswith("image/"):
                continue
            b64 = base64.b64encode(p.read_bytes()).decode()
            images.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
        
        if not images:
            return text
        return images + [{"type": "text", "text": text}]
    
    def add_tool_result(
        self,
        messages: list[dict[str, Any]],
        tool_call_id: str,
        tool_name: str,
        result: str
    ) -> list[dict[str, Any]]:
        """
        Add a tool result to the message list.
        
        Args:
            messages: Current message list.
            tool_call_id: ID of the tool call.
            tool_name: Name of the tool.
            result: Tool execution result.
        
        Returns:
            Updated message list.
        """
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": result
        })
        return messages
    
    def add_assistant_message(
        self,
        messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
        reasoning_content: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Add an assistant message to the message list.
        
        Args:
            messages: Current message list.
            content: Message content.
            tool_calls: Optional tool calls.
            reasoning_content: Thinking output (Kimi, DeepSeek-R1, etc.).
        
        Returns:
            Updated message list.
        """
        msg: dict[str, Any] = {"role": "assistant", "content": content or ""}
        
        if tool_calls:
            msg["tool_calls"] = tool_calls
        
        # Thinking models reject history without this
        if reasoning_content:
            msg["reasoning_content"] = reasoning_content
        
        messages.append(msg)
        return messages
