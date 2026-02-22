# Phase 5: Commit & Push

## Context
- Parent plan: [plan.md](plan.md)
- Depends on: [Phase 4](phase-04-validation.md)

## Overview
- **Priority**: P1
- **Status**: complete
- **Description**: Stage, commit, and push all rebrand changes

## Requirements
- All validation passes (Phase 4)
- Single clean commit
- Push to `dataplane` remote on `main` branch

## Implementation Steps

1. Stage all changes:
   ```bash
   git add -A
   ```

2. Review staged changes:
   ```bash
   git status
   git diff --cached --stat
   ```

3. Commit:
   ```bash
   git commit -m "feat: rebrand nanobot to miubot

   - Rename package directory nanobot/ → miubot/
   - Update PyPI package name to miubot
   - Update CLI command to miubot
   - Update config path to ~/.miubot/
   - Update all imports, docs, tests, Dockerfile
   - Add mise + uv tooling setup
   - Update GitHub refs to dataplanelabs/miubot"
   ```

4. Push to dataplane remote:
   ```bash
   git push dataplane main
   ```

## Todo List
- [ ] Stage all changes
- [ ] Review diff looks correct
- [ ] Commit with descriptive message
- [ ] Push to dataplane remote
- [ ] Verify push succeeded

## Success Criteria
- Clean commit on main branch
- Pushed to dataplanelabs/miubot on GitHub
- No uncommitted changes remain

## Risk Assessment
- **Low**: Standard git operations
- Pushing to main directly — user confirmed this is desired
