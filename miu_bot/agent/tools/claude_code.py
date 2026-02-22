"""Claude Code tool — delegates tasks to Claude Code CLI via claude-code-sdk."""

import asyncio
from typing import TYPE_CHECKING, Any

from loguru import logger

from miu_bot.agent.tools.base import Tool

if TYPE_CHECKING:
    from miu_bot.config.schema import ClaudeCodeConfig


class ClaudeCodeTool(Tool):
    """Run a task using the Claude Code CLI (requires `claude` installed and authenticated)."""

    def __init__(self, config: "ClaudeCodeConfig", workspace: str = ""):
        self._cfg = config
        self._workspace = workspace

    @property
    def name(self) -> str:
        return "claude_code"

    @property
    def description(self) -> str:
        return (
            "Delegate a coding task to Claude Code (an autonomous coding agent). "
            "Use for complex multi-file edits, refactoring, writing tests, or any task "
            "that benefits from an agentic coding workflow. The agent has full file system "
            "and shell access within the working directory."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The coding task to perform",
                },
                "working_dir": {
                    "type": "string",
                    "description": "Working directory (default: agent workspace)",
                },
            },
            "required": ["task"],
        }

    async def execute(self, task: str, working_dir: str = "", **kwargs: Any) -> str:
        try:
            from claude_code_sdk import ClaudeCodeOptions, query
        except ImportError:
            return (
                "Error: claude-code-sdk is not installed. "
                "Install it with: pip install 'miu_bot-ai[claude]'"
            )

        cwd = working_dir or self._cfg.working_dir or self._workspace
        options = ClaudeCodeOptions(
            max_turns=self._cfg.max_turns,
            permission_mode=self._cfg.permission_mode,
        )
        if cwd:
            options.cwd = cwd

        logger.info(f"claude_code: starting task in {cwd or '(default)'}")

        try:
            result_text = ""
            last_assistant_text = ""

            async def _run() -> str:
                nonlocal result_text, last_assistant_text
                async for msg in query(prompt=task, options=options):
                    # ResultMessage carries the final output
                    if hasattr(msg, "result") and msg.result is not None:
                        result_text = msg.result
                    # Track last assistant text as fallback
                    if hasattr(msg, "content") and msg.content:
                        for block in msg.content:
                            if hasattr(block, "text") and block.text:
                                last_assistant_text = block.text
                return result_text or last_assistant_text or "Task completed (no output)."

            output = await asyncio.wait_for(_run(), timeout=self._cfg.timeout)

        except asyncio.TimeoutError:
            return f"Error: claude_code timed out after {self._cfg.timeout}s."
        except Exception as e:
            err_name = type(e).__name__
            logger.error(f"claude_code failed: {err_name}: {e}")
            return f"Error: {err_name}: {e}"

        # Truncate if too long
        if len(output) > self._cfg.max_output_chars:
            half = self._cfg.max_output_chars // 2
            output = output[:half] + "\n\n... [truncated] ...\n\n" + output[-half:]

        logger.info(f"claude_code: completed ({len(output)} chars)")
        return output
