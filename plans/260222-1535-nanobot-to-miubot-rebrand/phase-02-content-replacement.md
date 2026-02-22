# Phase 2: Global Content Replacement

## Context
- Parent plan: [plan.md](plan.md)
- Depends on: [Phase 1](phase-01-directory-renames.md)

## Overview
- **Priority**: P1
- **Status**: complete
- **Description**: Replace all "nanobot" references in file contents across the entire codebase

## Key Insights
- Case-sensitive replacement: `nanobot` → `miubot`, `Nanobot` → `Miubot`
- Must NOT touch `.git/` directory or binary files (PNG, GIF)
- `nanobot-ai` (PyPI name) → `miubot`
- `HKUDS/nanobot` (GitHub URL) → `dataplanelabs/miubot`
- Config paths: `~/.nanobot` → `~/.miubot`
- The `uv.lock` file will be regenerated in Phase 3, skip it

## Requirements

### Replacement Rules (in order of specificity)
1. `nanobot-ai` → `miubot` (PyPI package name, badges, install commands)
2. `nanobot-whatsapp-bridge` → `miubot-whatsapp-bridge` (bridge package.json)
3. `HKUDS/nanobot` → `dataplanelabs/miubot` (GitHub URLs)
4. `nanobot_logo` → `miubot_logo` (asset references)
5. `nanobot_arch` → `miubot_arch` (asset references)
6. `nanobot contributors` → `miubot contributors` (pyproject authors)
7. `.nanobot` → `.miubot` (dotdir config path — careful, appears in Path refs)
8. `nanobot` → `miubot` (all remaining: imports, strings, CLI name, comments, docs)

### Files to Modify

**Python files (imports + strings)**:
- `miubot/__init__.py` — docstring
- `miubot/__main__.py` — module import
- `miubot/cli/commands.py` — CLI name, help text, user-facing strings, import paths
- `miubot/config/loader.py` — config path, import paths
- `miubot/config/schema.py` — workspace default, import paths
- `miubot/utils/helpers.py` — data path, docstrings
- `miubot/agent/*.py` — all import paths
- `miubot/agent/tools/*.py` — all import paths
- `miubot/channels/*.py` — all import paths (14 files)
- `miubot/providers/*.py` — all import paths
- `miubot/bus/*.py` — import paths
- `miubot/session/*.py` — import paths
- `miubot/cron/*.py` — import paths
- `miubot/heartbeat/*.py` — import paths

**Config & build files**:
- `pyproject.toml` — package name, scripts, hatch build paths, all nanobot refs
- `Dockerfile` — directory refs, config path, entrypoint

**Bridge (TypeScript/JSON)**:
- `bridge/package.json` — name, description
- `bridge/src/*.ts` — any nanobot refs in comments

**Documentation**:
- `README.md` — extensive nanobot references (CLI, install, config, structure)
- `SECURITY.md` — config paths, install commands, user references
- `LICENSE` — check if mentions nanobot
- `docs/code-standards.md` — project structure, references
- `docs/system-architecture.md` — module paths, config paths, mermaid diagrams
- `docs/development-roadmap.md`
- `docs/project-changelog.md`
- `docs/setup-telegram-guide.md`
- `docs/setup-zalo-guide.md`

**Workspace templates** (embedded in `commands.py` and standalone):
- `workspace/AGENTS.md`
- `workspace/SOUL.md`
- `workspace/USER.md`
- `workspace/TOOLS.md`
- `workspace/HEARTBEAT.md`
- `workspace/memory/MEMORY.md`

**Skills**:
- `miubot/skills/README.md`
- `miubot/skills/*/SKILL.md` (8 skill files)

**Scripts**:
- `core_agent_lines.sh` — directory refs

**Tests**:
- `tests/*.py` — import paths (6 test files)

## Implementation Steps

1. **Python files**: Use editor/sed to replace all `from nanobot` → `from miubot`, `import nanobot` → `import miubot`, string literals
2. **pyproject.toml**: Update name, scripts, hatch build paths
3. **Dockerfile**: Update dir refs, config path, entrypoint
4. **bridge/package.json**: Update name, description
5. **Documentation**: Replace all nanobot refs in .md files
6. **Workspace templates**: Replace in standalone files and embedded strings in commands.py
7. **Skills**: Replace in SKILL.md files
8. **Scripts**: Update core_agent_lines.sh
9. **Tests**: Update import paths

### Approach
For efficiency, use a combination of:
- `sed` for bulk replacements across many files
- Manual edit for files needing careful, context-aware changes (pyproject.toml, Dockerfile)

## Todo List
- [ ] Replace in Python source files (miubot/**/*.py)
- [ ] Replace in pyproject.toml
- [ ] Replace in Dockerfile
- [ ] Replace in bridge/package.json and bridge/src/*.ts
- [ ] Replace in README.md
- [ ] Replace in SECURITY.md
- [ ] Replace in docs/*.md
- [ ] Replace in workspace/*.md templates
- [ ] Replace in miubot/skills/**/*.md
- [ ] Replace in core_agent_lines.sh
- [ ] Replace in tests/*.py
- [ ] Verify: grep for any remaining "nanobot" refs (excluding .git/, plans/, .venv/)

## Success Criteria
- Zero `nanobot` references in source code, configs, docs (excluding .git/, plans/, .venv/)
- All Python imports use `miubot.*`
- CLI name is `miubot` in help text and entrypoint
- Config paths reference `~/.miubot/`

## Risk Assessment
- **Medium**: Large number of files — missing a reference could cause runtime error
- **Mitigation**: Post-replacement grep to find stragglers; run full test suite in Phase 4

## Security Considerations
- No security impact — pure renaming operation

## Next Steps
- Phase 3: Tooling setup
