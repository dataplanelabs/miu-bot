---
title: "Zalo WebSocket Bridge Integration"
description: "Add Zalo channel to nanobot via WebSocket bridge connecting to ZCA-CLI"
status: complete
priority: P2
effort: 3h
branch: main
tags: [zalo, websocket, channel, bridge, integration]
created: 2026-02-16
---

# Zalo WebSocket Bridge Integration

## Overview

Add Zalo messaging channel to nanobot using the same WebSocket bridge pattern as WhatsApp. Two components: a TypeScript bridge server in ZCA-CLI that connects to Zalo via `zca-js`, and a Python channel in nanobot that connects to the bridge as a WS client.

## Architecture

```
Zalo Servers <-> zca-js library <-> ZCA Bridge Server (TypeScript)
                                         |
                                    WebSocket (ws://localhost:3002)
                                         |
                                    NanoBot ZaloChannel (Python)
                                         |
                                    MessageBus -> AgentLoop -> LLM
```

## Phases

| # | Phase | Status | Files |
|---|-------|--------|-------|
| 1 | [ZCA Bridge Server](./phase-01-zca-bridge-server.md) | complete | `zca-cli-ts/src/commands/bridge.ts`, `zca-cli-ts/src/index.ts` |
| 2 | [Nanobot Zalo Channel](./phase-02-nanobot-zalo-channel.md) | complete | `nanobot/channels/zalo.py`, `nanobot/config/schema.py`, `nanobot/channels/manager.py`, `~/.nanobot/config.json` |

## Key Dependencies

- ZCA-CLI repo: `/Users/vanducng/git/personal/dataplanelabs/zca/zca-cli-ts/`
- nanobot repo: `/Users/vanducng/git/personal/agents/nanobot/`
- Reference: WhatsApp bridge (`bridge/src/server.ts`) + channel (`nanobot/channels/whatsapp.py`)
- Library: `zca-js` v2.0.4 (already installed in ZCA-CLI)
- Library: `ws` (needs install in ZCA-CLI for WS server)

## WS Protocol

Bridge -> Python:
- `{ type: "message", threadId, senderId, senderName, threadName, content, timestamp, threadType: "user"|"group" }`
- `{ type: "status", status: "connected"|"disconnected" }`
- `{ type: "error", error: "..." }`

Python -> Bridge:
- `{ type: "auth", token: "..." }` (if token configured)
- `{ type: "send", to: "<threadId>", text: "...", threadType: 1|2 }` (1=User, 2=Group)
