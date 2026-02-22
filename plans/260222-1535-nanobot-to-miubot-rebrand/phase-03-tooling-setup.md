# Phase 3: Tooling Setup (mise + uv)

## Context
- Parent plan: [plan.md](plan.md)
- Depends on: [Phase 2](phase-02-content-replacement.md)

## Overview
- **Priority**: P1
- **Status**: pending
- **Description**: Set up mise for tooling management, create fresh Python 3.13 venv via uv, install project

## Key Insights
- User wants `mise` for tooling management (Python version)
- User wants `uv` for package management and runtime
- Old `.venv/` uses Python 3.14 — must recreate with 3.13
- No existing `.mise.toml` in project — must create one

## Requirements
- Create `.mise.toml` with Python 3.13 config
- Remove old `.venv/` directory
- Create new venv with `uv venv --python 3.13`
- Install project in editable mode: `uv pip install -e ".[dev,claude]"`
- Verify `miubot` CLI command works

## Related Code Files
- `.mise.toml` (new)
- `pyproject.toml` (already updated in Phase 2)
- `.venv/` (recreate)

## Implementation Steps

1. Create `.mise.toml`:
   ```toml
   [tools]
   python = "3.13"
   ```

2. Install Python 3.13 via mise:
   ```bash
   mise install
   ```

3. Remove old venv and caches:
   ```bash
   rm -rf .venv/
   ```

4. Create new venv with uv:
   ```bash
   uv venv --python 3.13
   ```

5. Install project:
   ```bash
   uv pip install -e ".[dev,claude]"
   ```

6. Verify CLI:
   ```bash
   .venv/bin/miubot --help
   ```

7. Regenerate lock file:
   ```bash
   uv lock
   ```

## Todo List
- [ ] Create `.mise.toml` with Python 3.13
- [ ] `mise install` to get Python 3.13
- [ ] Remove old `.venv/`
- [ ] `uv venv --python 3.13`
- [ ] `uv pip install -e ".[dev,claude]"`
- [ ] Verify `miubot --help` works
- [ ] `uv lock` to regenerate lock file

## Success Criteria
- `.mise.toml` exists with Python 3.13
- `.venv/` uses Python 3.13
- `miubot` CLI command responds to `--help`
- `python -c "import miubot"` succeeds
- `uv.lock` regenerated

## Risk Assessment
- **Low**: Standard tooling setup
- If Python 3.13 not available via mise, may need `mise install python@3.13`
- Some dependencies may have issues with Python 3.13 (unlikely — project already runs on 3.14)

## Next Steps
- Phase 4: Validation
