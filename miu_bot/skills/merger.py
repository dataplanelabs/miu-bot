"""Skill merger — builds final system prompt from skills."""

from __future__ import annotations

from miu_bot.skills.schema import SkillConfig


def merge_skills_into_prompt(
    base_identity: str,
    skills: list[SkillConfig],
) -> tuple[str, dict[str, dict], list[str]]:
    """Merge skills into final system prompt.

    Returns: (augmented_identity, merged_mcp_servers, all_rules)
    """
    parts = [base_identity.strip()]
    all_rules: list[str] = []
    merged_mcp: dict[str, dict] = {}

    if skills:
        parts.append("\n\n[Skills Active]\n")
        for skill in skills:
            if skill.identity:
                parts.append(f"## {skill.name}\n{skill.identity.strip()}\n")
            if skill.rules:
                all_rules.extend(skill.rules)
            if skill.mcp_servers:
                merged_mcp.update(skill.mcp_servers)

    if all_rules:
        parts.append("\n[Rules]\n")
        for rule in all_rules:
            parts.append(f"- {rule}")

    return "\n".join(parts), merged_mcp, all_rules
