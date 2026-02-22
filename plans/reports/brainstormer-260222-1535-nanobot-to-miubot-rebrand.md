# Brainstorm: Rebrand nanobot to miubot

## Problem Statement
Rename entire project from "nanobot" to "miubot" — package, module, CLI, config paths, docs, tests, assets, all references. Fresh Python 3.13 venv. Test everything. Commit and push.

## Decisions Made

| Decision | Choice |
|----------|--------|
| PyPI package name | `miubot` |
| Config directory | `~/.miubot/` |
| Backward compat | None — full replace |
| Python version | 3.13 |
| Logo/branding | Keep cat emoji |
| Asset files | Rename `nanobot_*` → `miubot_*` |
| GitHub refs | Update to `dataplanelabs/miubot` |

## Scope

- **90 files** reference "nanobot"
- **55 Python files** in `nanobot/` directory
- **43 files** with `from nanobot.*` imports
- **165+ import references** total
- Config paths, CLI strings, docs, tests, Dockerfile, bridge code

## Approach: git mv + global find-replace

### Phase 1: Directory & file renames
- `git mv nanobot/ miubot/`
- `git mv nanobot_logo.png miubot_logo.png`
- `git mv nanobot_arch.png miubot_arch.png`

### Phase 2: Global content replacement
- `nanobot` → `miubot` in all Python, config, docs, templates
- `nanobot-ai` → `miubot` (PyPI name)
- `~/.nanobot` → `~/.miubot` (config paths)
- `HKUDS/nanobot` → `dataplanelabs/miubot` (GitHub URLs)
- `nanobot_logo`/`nanobot_arch` → `miubot_*` in references

### Phase 3: Fresh venv + install
- Remove `.venv/`, create Python 3.13 venv
- `pip install -e ".[dev,claude]"`

### Phase 4: Validation
- Lint: `ruff check miubot/`
- Tests: `pytest tests/`
- CLI: `miubot --help`, `miubot status`
- Import check: `python -c "import miubot"`

### Phase 5: Commit & push
- Single commit: `feat: rebrand nanobot to miubot`
- Push to `dataplane` remote (dataplanelabs/miubot)

## Risks

| Risk | Mitigation |
|------|-----------|
| Missed string replacement | Post-replace grep for remaining "nanobot" refs |
| Import cycle | Validate with `python -c "import miubot"` |
| Bridge TS refs | Update package.json and TS source files |
| Existing ~/.nanobot/ config | Users re-run `miubot onboard` |

## Not Doing
- No migration tool ~/.nanobot/ → ~/.miubot/ (YAGNI)
- No backward compat aliases
- No PyPI publish
