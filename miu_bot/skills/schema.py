"""Skill configuration schema."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SkillConfig(BaseModel):
    """Single skill definition."""
    name: str
    description: str = ""
    identity: str = ""  # System prompt fragment
    rules: list[str] = Field(default_factory=list)
    mcp_servers: dict[str, dict] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    # MIU-1: handler type and per-workspace config (Open WebUI valves pattern)
    handler_type: str = "prompt"  # prompt | function | api
    config: dict[str, Any] = Field(default_factory=dict)
    config_schema: dict[str, Any] = Field(default_factory=dict)


class SkillPreset(BaseModel):
    """Reusable skill bundle."""
    description: str = ""
    skills: list[str] = Field(default_factory=list)  # Skill names to include
    identity: str = ""  # Additional identity for this preset
    mcp_servers: dict[str, dict] = Field(default_factory=dict)


class BotSkillRef(BaseModel):
    """Bot's reference to a skill."""
    name: str = ""
    preset: str = ""  # Reference to skills_presets key
    source: str = ""  # "local" or "github:org/repo" (V2)
    inline: SkillConfig | None = None  # Inline skill definition
    override: dict = Field(default_factory=dict)  # Override fields
