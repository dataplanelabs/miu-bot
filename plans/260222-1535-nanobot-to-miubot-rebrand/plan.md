---
title: "Rebrand nanobot to miubot"
description: "Comprehensive rename of nanobot to miubot across entire codebase, fresh venv, test, commit and push"
status: complete
priority: P1
effort: 2h
branch: main
tags: [rebrand, rename, refactor]
created: 2026-02-22
---

# Rebrand nanobot to miubot

## Summary

Full project rename from "nanobot" → "miubot". Covers package name, module directory, CLI command, config paths, all imports, docs, tests, assets, Dockerfile, bridge code. Fresh Python 3.13 venv via uv + mise. Test everything. Commit and push.

## Decisions

| Decision | Value |
|----------|-------|
| PyPI package name | `miubot` |
| Config directory | `~/.miubot/` |
| CLI command | `miubot` |
| Backward compat | None |
| Python version | 3.13 (via mise) |
| Package manager | uv |
| Logo | Keep cat emoji |
| GitHub refs | `dataplanelabs/miubot` |
| Push remote | `dataplane` |

## Scope

- 90 files reference "nanobot"
- 55 Python files in `nanobot/` directory
- 165+ import references across 43 files
- 6 docs, 6 workspace templates, 8 skill files, 6 test files
- Dockerfile, bridge code (TypeScript), README, SECURITY, LICENSE

## Phases

| # | Phase | Status | Est |
|---|-------|--------|-----|
| 1 | [Directory & file renames](phase-01-directory-renames.md) | complete | 10m |
| 2 | [Global content replacement](phase-02-content-replacement.md) | complete | 30m |
| 3 | [Tooling setup (mise + uv)](phase-03-tooling-setup.md) | complete | 15m |
| 4 | [Validation](phase-04-validation.md) | complete | 20m |
| 5 | [Commit & push](phase-05-commit-push.md) | complete | 5m |

## Dependencies

- None (standalone refactoring task)

## Risk

- **Low**: Mechanical find-replace, verified by grep post-replacement
- **Mitigation**: Run full test suite + zero-nanobot-reference grep before commit
