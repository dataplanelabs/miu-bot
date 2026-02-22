"""Skill loader — discovers and loads skill.yaml files."""

from __future__ import annotations

from pathlib import Path

import yaml
from loguru import logger

from miu_bot.skills.schema import BotSkillRef, SkillConfig, SkillPreset


def load_skill_from_dir(skill_dir: Path) -> SkillConfig | None:
    """Load a single skill from a directory containing skill.yaml."""
    skill_file = skill_dir / "skill.yaml"
    if not skill_file.exists():
        return None
    raw = yaml.safe_load(skill_file.read_text(encoding="utf-8"))
    if not raw:
        return None
    return SkillConfig.model_validate(raw)


def discover_local_skills(paths: list[Path]) -> dict[str, SkillConfig]:
    """Scan directories for skill.yaml files. Returns {name: SkillConfig}."""
    skills: dict[str, SkillConfig] = {}
    for base_path in paths:
        if not base_path.exists():
            continue
        for skill_dir in sorted(base_path.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill = load_skill_from_dir(skill_dir)
            if skill:
                skills[skill.name] = skill
                logger.debug(f"Loaded skill '{skill.name}' from {skill_dir}")
    logger.info(f"Discovered {len(skills)} local skill(s): {list(skills.keys())}")
    return skills


def resolve_bot_skills(
    bot_skill_refs: list[BotSkillRef],
    presets: dict[str, SkillPreset],
    available_skills: dict[str, SkillConfig],
) -> list[SkillConfig]:
    """Resolve bot's skill references to concrete SkillConfig list."""
    resolved: list[SkillConfig] = []
    seen: set[str] = set()

    for ref in bot_skill_refs:
        if ref.preset and ref.preset in presets:
            # Expand preset: load each referenced skill
            preset = presets[ref.preset]
            for skill_name in preset.skills:
                if skill_name in available_skills and skill_name not in seen:
                    resolved.append(available_skills[skill_name])
                    seen.add(skill_name)
            # Add preset-level identity/mcp as a synthetic skill
            if preset.identity or preset.mcp_servers:
                resolved.append(SkillConfig(
                    name=f"_preset_{ref.preset}",
                    identity=preset.identity,
                    mcp_servers=preset.mcp_servers,
                ))
        elif ref.inline:
            # Inline skill definition
            resolved.append(ref.inline)
            seen.add(ref.inline.name)
        elif ref.name and ref.name in available_skills:
            if ref.name not in seen:
                skill = available_skills[ref.name]
                # Apply overrides if any
                if ref.override:
                    data = skill.model_dump()
                    data.update(ref.override)
                    skill = SkillConfig.model_validate(data)
                resolved.append(skill)
                seen.add(ref.name)
        else:
            logger.warning(f"Skill '{ref.name or ref.preset}' not found — skipping")

    return resolved
