# Phase 1: Directory & File Renames

## Context
- Parent plan: [plan.md](plan.md)
- Brainstorm: [brainstormer report](../reports/brainstormer-260222-1535-nanobot-to-miubot-rebrand.md)

## Overview
- **Priority**: P1 (must be done first)
- **Status**: pending
- **Description**: Rename main package directory and asset files using `git mv` to preserve history

## Key Insights
- `git mv` preserves git blame/history tracking
- Must rename directory before updating file contents (imports reference `nanobot.*`)
- Clean `__pycache__` dirs before rename to avoid stale bytecode

## Requirements
- Rename `nanobot/` → `miubot/`
- Rename `nanobot_logo.png` → `miubot_logo.png`
- Rename `nanobot_arch.png` → `miubot_arch.png`
- Remove all `__pycache__/` directories before rename

## Related Code Files
- `nanobot/` (entire directory — 55+ Python files)
- `nanobot_logo.png`
- `nanobot_arch.png`

## Implementation Steps

1. Remove all `__pycache__` directories:
   ```bash
   find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
   ```

2. Rename main package directory:
   ```bash
   git mv nanobot/ miubot/
   ```

3. Rename asset files:
   ```bash
   git mv nanobot_logo.png miubot_logo.png
   git mv nanobot_arch.png miubot_arch.png
   ```

## Todo List
- [ ] Clean __pycache__ directories
- [ ] `git mv nanobot/ miubot/`
- [ ] `git mv nanobot_logo.png miubot_logo.png`
- [ ] `git mv nanobot_arch.png miubot_arch.png`
- [ ] Verify git status shows renames (not delete+create)

## Success Criteria
- `miubot/` directory exists with all files
- `nanobot/` directory no longer exists
- `git status` shows renames
- Asset files renamed

## Risk Assessment
- **Low**: `git mv` is safe and reversible
- If `.venv/` contains installed nanobot package, it may have stale references — handled in Phase 3

## Next Steps
- Phase 2: Global content replacement
