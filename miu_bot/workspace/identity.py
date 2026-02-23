"""Identity markdown parser for workspace personas."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from miu_bot.db.backend import WorkspaceTemplate


@dataclass
class IdentityDoc:
    name: str = ""
    version: str = "1.0"
    language: str = "en"
    template: str | None = None
    identity: str = ""
    soul: str = ""
    context: str = ""
    skills: str = ""
    constraints: str = ""
    raw: str = ""


_SECTION_NAMES = {"identity", "soul", "context", "skills", "constraints"}


def parse_identity(markdown: str) -> IdentityDoc:
    """Parse identity markdown with YAML frontmatter + ## sections."""
    doc = IdentityDoc(raw=markdown)

    # Extract YAML frontmatter
    body = markdown
    if markdown.startswith("---"):
        parts = markdown.split("---", 2)
        if len(parts) >= 3:
            try:
                fm = yaml.safe_load(parts[1]) or {}
                doc.name = fm.get("name", "")
                doc.version = fm.get("version", "1.0")
                doc.language = fm.get("language", "en")
                doc.template = fm.get("template")
            except yaml.YAMLError:
                pass
            body = parts[2]

    # Split by ## headers
    sections: dict[str, str] = {}
    current_section: str | None = None
    current_lines: list[str] = []

    for line in body.splitlines():
        header_match = re.match(r"^##\s+(.+)$", line)
        if header_match:
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = header_match.group(1).strip().lower()
            current_lines = []
        else:
            current_lines.append(line)

    if current_section:
        sections[current_section] = "\n".join(current_lines).strip()

    for name in _SECTION_NAMES:
        if name in sections:
            setattr(doc, name, sections[name])

    return doc


def render_system_prompt(identity: IdentityDoc, memories: str = "") -> str:
    """Render identity sections into a system prompt string.

    If the identity contains recognized sections (identity/soul/context/skills/
    constraints) they are rendered in order.  Otherwise the raw markdown body
    (everything after frontmatter) is used as-is — this supports identities
    written in any language with arbitrary section names.
    """
    parts: list[str] = []
    has_sections = any([
        identity.identity, identity.soul, identity.context,
        identity.skills, identity.constraints,
    ])

    if has_sections:
        if identity.identity:
            parts.append(f"## Identity\n{identity.identity}")
        if identity.soul:
            parts.append(f"## Soul\n{identity.soul}")
        if identity.context:
            parts.append(f"## Context\n{identity.context}")
        if identity.skills:
            parts.append(f"## Skills\n{identity.skills}")
        if identity.constraints:
            parts.append(f"## Constraints\n{identity.constraints}")
    elif identity.raw:
        # No recognized sections — use raw body (strip frontmatter)
        body = identity.raw
        if body.startswith("---"):
            fm_parts = body.split("---", 2)
            if len(fm_parts) >= 3:
                body = fm_parts[2]
        parts.append(body.strip())

    if memories:
        parts.append(f"## Memories\n{memories}")
    return "\n\n".join(parts)


def compose_from_templates(
    templates: list["WorkspaceTemplate"],
    memories: str = "",
) -> str:
    """Compose system prompt from separated workspace templates.

    Assembles soul + user + agents in order, with memories appended.
    """
    parts: list[str] = []

    # Order: soul -> user -> agents
    template_map = {t.template_type: t for t in templates}
    for ttype in ("soul", "user", "agents"):
        tmpl = template_map.get(ttype)
        if tmpl and tmpl.content.strip():
            parts.append(f"## {ttype.title()}\n{tmpl.content.strip()}")

    if memories:
        parts.append(f"## Memories\n{memories}")

    return "\n\n".join(parts)
