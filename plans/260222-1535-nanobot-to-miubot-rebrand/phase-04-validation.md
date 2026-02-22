# Phase 4: Validation

## Context
- Parent plan: [plan.md](plan.md)
- Depends on: [Phase 3](phase-03-tooling-setup.md)

## Overview
- **Priority**: P1
- **Status**: pending
- **Description**: Validate the rebrand is complete and functional

## Requirements
- Zero "nanobot" references remaining in source code
- All imports resolve correctly
- Linting passes
- All tests pass
- CLI works

## Implementation Steps

1. **Import check**:
   ```bash
   .venv/bin/python -c "import miubot; print(miubot.__version__, miubot.__logo__)"
   ```

2. **Lint check**:
   ```bash
   .venv/bin/ruff check miubot/
   ```

3. **Run tests**:
   ```bash
   .venv/bin/pytest tests/ -v
   ```

4. **CLI check**:
   ```bash
   .venv/bin/miubot --help
   .venv/bin/miubot --version
   ```

5. **Straggler check** — verify zero remaining "nanobot" references:
   ```bash
   grep -r "nanobot" \
     --include="*.py" --include="*.toml" --include="*.md" \
     --include="*.ts" --include="*.json" --include="*.sh" \
     miubot/ tests/ docs/ workspace/ bridge/ \
     pyproject.toml Dockerfile README.md SECURITY.md \
     core_agent_lines.sh .mise.toml 2>/dev/null
   ```
   Expected: zero matches (excluding plans/ and .venv/)

6. **Fix any issues found** in steps 1-5

## Todo List
- [ ] Import check passes
- [ ] Ruff lint passes
- [ ] All tests pass
- [ ] CLI --help and --version work
- [ ] Zero nanobot stragglers in source/docs
- [ ] Fix any issues found

## Success Criteria
- All 5 checks pass with zero errors
- No "nanobot" references remain in active code/docs

## Risk Assessment
- **Medium**: Tests may fail due to missed references
- **Mitigation**: Fix issues iteratively until all pass

## Next Steps
- Phase 5: Commit & push
