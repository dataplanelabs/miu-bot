"""Workspace model, identity parsing, and config management."""

from miu_bot.workspace.identity import IdentityDoc, parse_identity, render_system_prompt
from miu_bot.workspace.config_merge import deep_merge
from miu_bot.workspace.service import WorkspaceService

__all__ = [
    "IdentityDoc",
    "parse_identity",
    "render_system_prompt",
    "deep_merge",
    "WorkspaceService",
]
