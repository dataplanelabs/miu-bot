"""Skill source resolver — resolves inline, local, git skill sources."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from miu_bot.db.backend import WorkspaceSkill


def resolve_skill_sources(
    skill_defs: list[dict[str, Any]],
) -> list[WorkspaceSkill]:
    """Resolve skill definitions from bots.yaml into WorkspaceSkill objects.

    Supports:
    - inline: skill defined directly in YAML
    - local:/path: read SKILL.yaml from filesystem
    - git:org/repo/skill: V2 stub (logs warning)
    """
    resolved: list[WorkspaceSkill] = []
    now = datetime.now(timezone.utc)

    for skill_def in skill_defs:
        name = skill_def.get("name", "")
        source = skill_def.get("source", "")

        if source.startswith("git:"):
            logger.warning(f"Git skill source '{source}' not yet supported (V2) — skipping '{name}'")
            continue

        if source.startswith("local:"):
            path = Path(source[6:])  # strip "local:"
            skill_data = _load_local_skill(path)
            if not skill_data:
                logger.warning(f"Local skill not found at {path} — skipping '{name}'")
                continue
            ws_skill = _dict_to_workspace_skill(skill_data, source=source, now=now)
            if ws_skill:
                resolved.append(ws_skill)
            continue

        # Inline: skill defined directly in the YAML dict
        ws_skill = _dict_to_workspace_skill(skill_def, source="inline", now=now)
        if ws_skill:
            resolved.append(ws_skill)

    return resolved


def _load_local_skill(path: Path) -> dict | None:
    """Load skill data from a local SKILL.yaml file."""
    if path.is_dir():
        path = path / "SKILL.yaml"
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        logger.error(f"Failed to read skill file {path}: {e}")
        return None


def _dict_to_workspace_skill(
    data: dict, source: str, now: datetime,
) -> WorkspaceSkill | None:
    """Convert a skill dict to a WorkspaceSkill dataclass."""
    name = data.get("name", "")
    if not name:
        logger.warning("Skill missing 'name' field — skipping")
        return None

    return WorkspaceSkill(
        id="",  # Set by DB on upsert
        workspace_id="",  # Set by caller
        name=name,
        description=data.get("description", ""),
        identity=data.get("identity", ""),
        rules=data.get("rules", []),
        mcp_servers=data.get("mcp_servers", {}),
        tags=data.get("tags", []),
        source=source,
        source_version=data.get("source_version", ""),
        enabled=data.get("enabled", True),
        created_at=now,
        updated_at=now,
        # MIU-1: new skill config fields (default-safe for old YAML)
        handler_type=data.get("handler_type", "prompt"),
        config=data.get("config", {}),
        config_schema=data.get("config_schema", {}),
    )
