"""Bot definitions loaded from bots.yaml."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from loguru import logger
from pydantic import BaseModel, Field


class BotProviderConfig(BaseModel):
    """Per-bot LLM provider config."""
    model: str = ""  # LiteLLM model string, e.g. "openai/gpt-4o"
    vision_fallback_model: str = ""  # Vision model for image description (e.g. "glm-4v")
    api_key: str = ""  # Resolved from api_key_env
    api_key_env: str = ""  # Env var name for api_key (stored as-is, worker resolves)
    api_base: str = ""  # Resolved from api_base_env
    api_base_env: str = ""  # Env var name for api_base (stored as-is, worker resolves)


class BotChannelConfig(BaseModel):
    """Per-bot channel config (type-agnostic)."""
    token: str = ""  # Resolved from token_env
    allow_from: list[str] = Field(default_factory=list)
    proxy: str | None = None


class BotMCPServerConfig(BaseModel):
    """Per-bot MCP server config (HTTP only for V1)."""
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    headers_env: dict[str, str] = Field(default_factory=dict)  # Env var names, worker resolves
    # stdio fields (deferred to V2)
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)


class BotToolsConfig(BaseModel):
    """Per-bot tools config."""
    mcp_servers: dict[str, BotMCPServerConfig] = Field(default_factory=dict)


class JobTarget(BaseModel):
    """Target channel/group for cron job output."""
    channel: str
    chat_id: str = ""
    chat_id_env: str = ""
    thread_type: int | None = None  # Zalo: 1=user, 2=group


class JobConfig(BaseModel):
    """Cron job definition for a bot."""
    description: str = ""
    schedule: str  # Cron expression e.g. "0 8 * * 1-6"
    timezone: str = "UTC"
    enabled: bool = True
    prompt: str  # What to ask the bot
    targets: list[JobTarget] = Field(default_factory=list)


class BotConfig(BaseModel):
    """Single bot definition from bots.yaml."""
    name: str = ""  # Set from dict key
    identity: str = ""  # Legacy (backward compat — used if soul/user/agents absent)
    # Separated workspace templates (new)
    soul: str = ""
    user: str = ""
    agents: str = ""
    # Heartbeat config (schema only, separate plan)
    heartbeat: dict[str, Any] = Field(default_factory=dict)
    # Existing fields
    provider: BotProviderConfig = Field(default_factory=BotProviderConfig)
    channels: dict[str, BotChannelConfig] = Field(default_factory=dict)
    tools: BotToolsConfig = Field(default_factory=BotToolsConfig)
    skills: list[dict] = Field(default_factory=list)  # BotSkillRef dicts
    tools_preset: str = ""  # Reference to tools_presets key
    jobs: dict[str, JobConfig] = Field(default_factory=dict)


def _resolve_env_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Resolve *_env fields from os.environ.

    For a key like 'token_env' with value 'MY_TG_TOKEN':
    - Removes 'token_env' from dict
    - Sets 'token' = os.environ['MY_TG_TOKEN']

    For 'headers_env' (dict values):
    - Each value is an env var name
    - Resolved to actual env var value
    """
    resolved = {}
    for key, value in data.items():
        if key.endswith("_env"):
            target_key = key[:-4]  # Remove '_env' suffix
            if not value:
                # Skip empty _env fields (default Pydantic values)
                continue
            if isinstance(value, dict):
                # headers_env: {Authorization: ENV_VAR_NAME}
                resolved[target_key] = {
                    k: os.environ.get(v, "")
                    for k, v in value.items()
                }
                missing = [v for v in value.values() if v not in os.environ]
                if missing:
                    logger.warning(f"Missing env vars for {key}: {missing}")
            else:
                # scalar: token_env: ENV_VAR_NAME
                env_val = os.environ.get(value, "")
                if not env_val:
                    logger.warning(f"Env var '{value}' not set for field '{key}'")
                resolved[target_key] = env_val
        elif isinstance(value, dict):
            resolved[key] = _resolve_env_fields(value)
        else:
            resolved[key] = value
    return resolved


DEFAULT_BOTS_CONFIG_PATH = Path("/etc/miu-bot/bots.yaml")


def load_bots(path: Path | None = None) -> dict[str, BotConfig]:
    """Load bot definitions from bots.yaml.

    Resolves *_env for channels only (gateway needs tokens).
    Provider/tools *_env stored as-is for worker runtime resolution.

    Returns:
        Dict mapping bot_name -> BotConfig.
    """
    config_path = path or DEFAULT_BOTS_CONFIG_PATH
    if not config_path.exists():
        logger.info(f"No bots config at {config_path} — no bots loaded")
        return {}

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not raw or "bots" not in raw:
        return {}

    # Load tools presets if present
    tools_presets = raw.get("tools_presets", {})

    bots: dict[str, BotConfig] = {}
    for bot_name, bot_data in raw["bots"].items():
        if not isinstance(bot_data, dict):
            continue

        # Merge tools preset if referenced
        preset_name = bot_data.pop("tools_preset", None)
        if preset_name and preset_name in tools_presets:
            preset = tools_presets[preset_name]
            # Merge: bot-specific tools override preset
            merged_tools = {**preset}
            if "tools" in bot_data:
                for k, v in bot_data["tools"].items():
                    if k in merged_tools and isinstance(v, dict):
                        merged_tools[k] = {**merged_tools[k], **v}
                    else:
                        merged_tools[k] = v
            bot_data["tools"] = merged_tools

        # Resolve *_env ONLY for channels (gateway needs tokens)
        if "channels" in bot_data:
            bot_data["channels"] = _resolve_env_fields(bot_data["channels"])

        # Provider and tools *_env preserved as-is (worker resolves at runtime)
        bot_data["name"] = bot_name
        try:
            bots[bot_name] = BotConfig.model_validate(bot_data)
        except Exception as e:
            raise ValueError(f"Invalid config for bot '{bot_name}': {e}") from e

    logger.info(f"Loaded {len(bots)} bot(s) from {config_path}: {list(bots.keys())}")
    return bots
