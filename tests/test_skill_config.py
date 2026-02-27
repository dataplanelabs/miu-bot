"""Unit tests for miu_bot.skills.schema.SkillConfig (MIU-1 new fields)."""
import pytest

from miu_bot.skills.schema import BotSkillRef, SkillConfig, SkillPreset


# ---------------------------------------------------------------------------
# SkillConfig defaults
# ---------------------------------------------------------------------------

def test_skill_config_minimal_required_fields():
    skill = SkillConfig(name="coding")
    assert skill.name == "coding"
    assert skill.description == ""
    assert skill.identity == ""
    assert skill.rules == []
    assert skill.mcp_servers == {}
    assert skill.tags == []


def test_skill_config_miu1_defaults():
    """MIU-1 new fields must default correctly."""
    skill = SkillConfig(name="coding")
    assert skill.handler_type == "prompt"
    assert skill.config == {}
    assert skill.config_schema == {}


def test_skill_config_full_population():
    skill = SkillConfig(
        name="weather",
        description="Provides weather forecasts",
        identity="You are a weather expert.",
        rules=["Always cite sources", "Use Celsius"],
        tags=["weather", "utility"],
        handler_type="function",
        config={"api_key": "secret", "units": "metric"},
        config_schema={"type": "object", "properties": {"api_key": {"type": "string"}}},
    )
    assert skill.handler_type == "function"
    assert skill.config["api_key"] == "secret"
    assert skill.config_schema["type"] == "object"
    assert len(skill.rules) == 2


def test_skill_config_handler_type_api():
    skill = SkillConfig(name="search", handler_type="api")
    assert skill.handler_type == "api"


def test_skill_config_config_dict_arbitrary_keys():
    skill = SkillConfig(name="x", config={"a": 1, "b": [1, 2], "c": {"nested": True}})
    assert skill.config["c"]["nested"] is True


def test_skill_config_from_dict_validation():
    """SkillConfig.model_validate round-trip."""
    data = {
        "name": "coding",
        "description": "helps code",
        "handler_type": "function",
        "config": {"max_lines": 100},
        "config_schema": {"type": "object"},
    }
    skill = SkillConfig.model_validate(data)
    assert skill.name == "coding"
    assert skill.handler_type == "function"
    assert skill.config["max_lines"] == 100


def test_skill_config_model_dump_preserves_new_fields():
    skill = SkillConfig(
        name="test",
        handler_type="api",
        config={"url": "https://api.example.com"},
        config_schema={"type": "object"},
    )
    dumped = skill.model_dump()
    assert dumped["handler_type"] == "api"
    assert dumped["config"]["url"] == "https://api.example.com"
    assert dumped["config_schema"]["type"] == "object"


# ---------------------------------------------------------------------------
# WorkspaceSkill dataclass (MIU-1 new fields)
# ---------------------------------------------------------------------------

def test_workspace_skill_new_field_defaults():
    from datetime import datetime, timezone
    from miu_bot.db.backend import WorkspaceSkill

    now = datetime.now(timezone.utc)
    skill = WorkspaceSkill(
        id="sk-1",
        workspace_id="ws-1",
        name="coding",
        description="code help",
        identity="",
        rules=[],
        mcp_servers={},
        tags=[],
        source="inline",
        source_version="",
        enabled=True,
        created_at=now,
        updated_at=now,
    )
    # MIU-1 defaults
    assert skill.handler_type == "prompt"
    assert skill.config == {}
    assert skill.config_schema == {}


def test_workspace_skill_with_miu1_fields():
    from datetime import datetime, timezone
    from miu_bot.db.backend import WorkspaceSkill

    now = datetime.now(timezone.utc)
    skill = WorkspaceSkill(
        id="sk-2",
        workspace_id="ws-1",
        name="weather",
        description="weather tool",
        identity="You forecast weather.",
        rules=["Use Celsius"],
        mcp_servers={},
        tags=["weather"],
        source="local",
        source_version="v1",
        enabled=True,
        created_at=now,
        updated_at=now,
        config={"api_key": "test-key"},
        handler_type="function",
        config_schema={"type": "object"},
    )
    assert skill.config["api_key"] == "test-key"
    assert skill.handler_type == "function"
    assert skill.config_schema["type"] == "object"


# ---------------------------------------------------------------------------
# SkillPreset
# ---------------------------------------------------------------------------

def test_skill_preset_defaults():
    preset = SkillPreset()
    assert preset.description == ""
    assert preset.skills == []
    assert preset.identity == ""
    assert preset.mcp_servers == {}


def test_skill_preset_full():
    preset = SkillPreset(
        description="Dev toolkit",
        skills=["coding", "git"],
        identity="You are a developer.",
        mcp_servers={"git-server": {"url": "http://localhost:8000"}},
    )
    assert len(preset.skills) == 2
    assert "git-server" in preset.mcp_servers


# ---------------------------------------------------------------------------
# BotSkillRef
# ---------------------------------------------------------------------------

def test_bot_skill_ref_defaults():
    ref = BotSkillRef()
    assert ref.name == ""
    assert ref.preset == ""
    assert ref.source == ""
    assert ref.inline is None
    assert ref.override == {}


def test_bot_skill_ref_with_inline():
    inline = SkillConfig(name="inline-skill", handler_type="function")
    ref = BotSkillRef(inline=inline)
    assert ref.inline.name == "inline-skill"
    assert ref.inline.handler_type == "function"
