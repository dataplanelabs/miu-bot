"""Unit tests for miu_bot.skills.loader and miu_bot.skills.merger."""
from pathlib import Path

import pytest

from miu_bot.skills.loader import (
    discover_local_skills,
    load_skill_from_dir,
    resolve_bot_skills,
)
from miu_bot.skills.merger import merge_skills_from_db, merge_skills_into_prompt
from miu_bot.skills.schema import BotSkillRef, SkillConfig, SkillPreset


# ---------------------------------------------------------------------------
# load_skill_from_dir
# ---------------------------------------------------------------------------

def test_load_skill_returns_none_when_no_yaml(tmp_path):
    skill = load_skill_from_dir(tmp_path)
    assert skill is None


def test_load_skill_returns_none_for_empty_yaml(tmp_path):
    (tmp_path / "skill.yaml").write_text("")
    skill = load_skill_from_dir(tmp_path)
    assert skill is None


def test_load_skill_parses_minimal_yaml(tmp_path):
    (tmp_path / "skill.yaml").write_text("name: coding\ndescription: helps code\n")
    skill = load_skill_from_dir(tmp_path)
    assert skill is not None
    assert skill.name == "coding"
    assert skill.description == "helps code"


def test_load_skill_default_miu1_fields(tmp_path):
    """MIU-1: handler_type, config, config_schema default correctly from YAML."""
    (tmp_path / "skill.yaml").write_text("name: coding\ndescription: helps code\n")
    skill = load_skill_from_dir(tmp_path)
    assert skill.handler_type == "prompt"
    assert skill.config == {}
    assert skill.config_schema == {}


def test_load_skill_with_handler_type_function(tmp_path):
    yaml_content = "name: weather\ndescription: weather tool\nhandler_type: function\n"
    (tmp_path / "skill.yaml").write_text(yaml_content)
    skill = load_skill_from_dir(tmp_path)
    assert skill.handler_type == "function"


def test_load_skill_with_config_dict(tmp_path):
    yaml_content = (
        "name: search\n"
        "description: web search\n"
        "config:\n"
        "  api_key: test-key\n"
        "  max_results: 5\n"
    )
    (tmp_path / "skill.yaml").write_text(yaml_content)
    skill = load_skill_from_dir(tmp_path)
    assert skill.config["api_key"] == "test-key"
    assert skill.config["max_results"] == 5


def test_load_skill_with_rules_and_tags(tmp_path):
    yaml_content = (
        "name: coding\n"
        "rules:\n"
        "  - Always write tests\n"
        "  - Use type hints\n"
        "tags: [python, dev]\n"
    )
    (tmp_path / "skill.yaml").write_text(yaml_content)
    skill = load_skill_from_dir(tmp_path)
    assert len(skill.rules) == 2
    assert "python" in skill.tags


# ---------------------------------------------------------------------------
# discover_local_skills
# ---------------------------------------------------------------------------

def test_discover_local_skills_finds_subdirs(tmp_path):
    for name in ["coding", "weather", "search"]:
        skill_dir = tmp_path / name
        skill_dir.mkdir()
        (skill_dir / "skill.yaml").write_text(f"name: {name}\n")
    skills = discover_local_skills([tmp_path])
    assert len(skills) == 3
    assert "coding" in skills
    assert "weather" in skills


def test_discover_local_skills_skips_nonexistent_path():
    result = discover_local_skills([Path("/nonexistent/path/xyz")])
    assert result == {}


def test_discover_local_skills_ignores_files_not_dirs(tmp_path):
    (tmp_path / "not-a-skill.txt").write_text("hello")
    skill_dir = tmp_path / "real-skill"
    skill_dir.mkdir()
    (skill_dir / "skill.yaml").write_text("name: real-skill\n")
    skills = discover_local_skills([tmp_path])
    assert len(skills) == 1
    assert "real-skill" in skills


def test_discover_local_skills_skips_dir_without_yaml(tmp_path):
    empty_dir = tmp_path / "empty-skill"
    empty_dir.mkdir()
    skills = discover_local_skills([tmp_path])
    assert skills == {}


# ---------------------------------------------------------------------------
# resolve_bot_skills
# ---------------------------------------------------------------------------

def _make_skill(name: str, **kwargs) -> SkillConfig:
    return SkillConfig(name=name, description=f"{name} skill", **kwargs)


def test_resolve_bot_skills_by_name():
    available = {"coding": _make_skill("coding")}
    refs = [BotSkillRef(name="coding")]
    result = resolve_bot_skills(refs, {}, available)
    assert len(result) == 1
    assert result[0].name == "coding"


def test_resolve_bot_skills_missing_skips_no_exception():
    refs = [BotSkillRef(name="nonexistent")]
    result = resolve_bot_skills(refs, {}, {})
    assert result == []


def test_resolve_bot_skills_inline():
    inline = _make_skill("inline-tool", handler_type="function")
    refs = [BotSkillRef(inline=inline)]
    result = resolve_bot_skills(refs, {}, {})
    assert len(result) == 1
    assert result[0].name == "inline-tool"
    assert result[0].handler_type == "function"


def test_resolve_bot_skills_preset_expands():
    available = {
        "coding": _make_skill("coding"),
        "git": _make_skill("git"),
    }
    presets = {"dev": SkillPreset(skills=["coding", "git"])}
    refs = [BotSkillRef(preset="dev")]
    result = resolve_bot_skills(refs, presets, available)
    names = [s.name for s in result]
    assert "coding" in names
    assert "git" in names


def test_resolve_bot_skills_deduplicates():
    available = {"coding": _make_skill("coding")}
    refs = [BotSkillRef(name="coding"), BotSkillRef(name="coding")]
    result = resolve_bot_skills(refs, {}, available)
    assert len(result) == 1


def test_resolve_bot_skills_with_override():
    available = {"coding": SkillConfig(name="coding", description="original")}
    refs = [BotSkillRef(name="coding", override={"description": "overridden"})]
    result = resolve_bot_skills(refs, {}, available)
    assert result[0].description == "overridden"


# ---------------------------------------------------------------------------
# merge_skills_into_prompt
# ---------------------------------------------------------------------------

def test_merge_skills_into_prompt_combines_identity():
    skills = [
        SkillConfig(name="coding", identity="You code well."),
        SkillConfig(name="git", identity="You use git."),
    ]
    identity, mcp, rules = merge_skills_into_prompt("Base identity.", skills)
    assert "Base identity." in identity
    assert "You code well." in identity
    assert "You use git." in identity
    assert "[Skills Active]" in identity


def test_merge_skills_into_prompt_collects_rules():
    skills = [
        SkillConfig(name="coding", rules=["Write tests", "Use types"]),
    ]
    identity, mcp, rules = merge_skills_into_prompt("Base.", skills)
    assert "Write tests" in rules
    assert "Use types" in rules
    assert "[Rules]" in identity


def test_merge_skills_into_prompt_merges_mcp_servers():
    skills = [
        SkillConfig(name="a", mcp_servers={"srv-a": {"url": "http://a"}}),
        SkillConfig(name="b", mcp_servers={"srv-b": {"url": "http://b"}}),
    ]
    _, mcp, _ = merge_skills_into_prompt("Base.", skills)
    assert "srv-a" in mcp
    assert "srv-b" in mcp


def test_merge_skills_into_prompt_no_skills():
    identity, mcp, rules = merge_skills_into_prompt("Base identity.", [])
    assert "Base identity." in identity
    assert mcp == {}
    assert rules == []


# ---------------------------------------------------------------------------
# merge_skills_from_db
# ---------------------------------------------------------------------------

def test_merge_skills_from_db_empty_list():
    section, mcp, rules = merge_skills_from_db([])
    assert section == ""
    assert mcp == {}
    assert rules == []


def test_merge_skills_from_db_with_skills():
    from datetime import datetime, timezone
    from miu_bot.db.backend import WorkspaceSkill

    now = datetime.now(timezone.utc)
    ws_skill = WorkspaceSkill(
        id="sk-1", workspace_id="ws-1", name="coding",
        description="code", identity="You are a coder.",
        rules=["Write tests"], mcp_servers={"srv": {"url": "http://srv"}},
        tags=[], source="inline", source_version="", enabled=True,
        created_at=now, updated_at=now,
    )
    section, mcp, rules = merge_skills_from_db([ws_skill])
    assert "coding" in section
    assert "You are a coder." in section
    assert "Write tests" in rules
    assert "srv" in mcp
