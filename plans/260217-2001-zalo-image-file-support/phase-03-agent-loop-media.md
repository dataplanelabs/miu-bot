# Phase 03 — Agent Loop: Media Marker Convention & System Prompt

## Context Links
- Agent loop: `nanobot/agent/loop.py` (lines 417–422 — OutboundMessage construction)
- System prompt config: check `nanobot/config/` for system prompt injection point
- Zalo channel: `nanobot/channels/zalo.py`
- Phase 02: [phase-02-nanobot-zalo-media.md](./phase-02-nanobot-zalo-media.md)
- Plan overview: [plan.md](./plan.md)

## Overview

- **Priority**: P3
- **Status**: complete
- **Effort**: 0.5h
- **Description**: No code changes to `loop.py`. Document the marker convention and ensure the LLM system prompt teaches the model when and how to emit `[send-image:…]` / `[send-file:…]` markers so they get picked up by `zalo.py`.

## Key Insights

- The agent loop passes `final_content` (raw LLM text) directly into `OutboundMessage.content`
- `zalo.py` extracts markers from that content string — the loop is transparent
- The only requirement is that the LLM knows the convention; this is a system prompt concern
- `OutboundMessage.media` field remains unused — no changes to `events.py` either
- If a tool (e.g., ai-multimodal) saves an image to disk and returns the path in its result text, the LLM can echo that path wrapped in a marker

## Requirements

**Functional**
- Locate where the Zalo-specific system prompt (or global system prompt) is configured
- Add a short section teaching the LLM the marker convention
- Cover: when to use, format, local paths vs URLs, file vs image distinction

**Non-functional**
- Prompt addition must be concise (≤10 lines) to minimise token cost
- No new Python files; edit existing prompt/config only

## Architecture

```
Tool result: "Image saved to /tmp/chart-20260217.png"
    │
    ▼
LLM reasoning: user asked for a chart → include in response
    │
    ▼
LLM output: "Here's your chart [send-image:/tmp/chart-20260217.png]"
    │
    ▼
loop.py: OutboundMessage(content="Here's your chart [send-image:/tmp/chart-20260217.png]")
    │
    ▼
zalo.py send(): extracts marker → WS send-image → strips marker → sends "Here's your chart"
```

## Related Code Files

**Investigate to find prompt injection point**
- `nanobot/config/schema.py` — look for `system_prompt` field
- `nanobot/agent/loop.py` — look for where system prompt is assembled
- `nanobot/channels/zalo.py` — `ZaloConfig` may have channel-level prompt override

**Modify (one of the above, whichever is the right injection point)**
- The file that holds or assembles the system prompt for the Zalo channel / global agent

## Implementation Steps

### 1. Locate the system prompt injection point

```bash
grep -rn "system_prompt\|system prompt" nanobot/ --include="*.py" | head -30
```

Check if there is:
- A global `system_prompt` in agent config
- A per-channel prompt override in `ZaloConfig`
- A hard-coded prompt string in `loop.py`

### 2. Draft the marker convention text

Add the following block to the system prompt (adapt formatting to match existing style):

```
## Sending Media to Zalo

When you want to send an image or file to the user, embed a marker in your response:
- Image: [send-image:/absolute/path/or/https://url]
- File:  [send-file:/absolute/path/or/https://url]
- File with caption: [send-file:/path/to/file|Caption text here]

Rules:
- Use [send-image] for jpg/jpeg/png/gif/webp/bmp files; use [send-file] for all others (pdf, zip, docx, …)
- Place the marker inline; it will be stripped before the text is sent to the user
- Only include a marker when you have a real file path or URL — never fabricate paths
- If a tool returns a file path, you may include it directly in the marker
```

### 3. Insert the block in the correct location

- If global system prompt string: append the block at the end
- If YAML/TOML config field: add as a multiline string entry
- If per-channel config: add to ZaloConfig's `system_prompt` field if it exists

### 4. Smoke-test prompt injection

Run the agent locally against a test Zalo conversation and ask it to:
1. "Generate a small chart and send it" — confirm the LLM emits a `[send-image:…]` marker
2. "Send me a PDF" (after saving a test PDF via a tool) — confirm `[send-file:…]` marker

## Todo List

- [x] Run grep to find system prompt injection point
- [x] Draft and insert marker convention block (≤10 lines)
- [x] Confirm prompt is received by the LLM (check agent debug logs)
- [x] Smoke-test: LLM emits valid marker after tool saves a file
- [x] Smoke-test: marker-only response (no text) sends media without error

## Success Criteria

- System prompt includes the marker convention
- LLM correctly emits `[send-image:/tmp/foo.png]` when a tool produces an image at that path
- LLM does not emit fabricated/hallucinated paths
- End-to-end flow (tool → LLM → marker → zalo.py → bridge → Zalo chat) works

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| LLM ignores convention or hallucinates paths | Medium | Keep prompt instruction short and clear; add "only use real paths" rule |
| System prompt location not found / no injection mechanism | Low | Fall back to hard-coded prefix in `ZaloChannel._handle_message` context |
| Prompt token cost increase | Low | Block is ≤10 lines; negligible |

## Security Considerations

- Prompt injection via user input crafting a fake marker: mitigated because `zalo.py` sends the file path to the bridge which runs on the same trusted machine — no external path traversal
- LLM must be instructed not to fabricate paths to prevent sending incorrect files

## Next Steps

- After all three phases: manual end-to-end test across the full stack (bridge + nanobot + Zalo)
- Post-validation: update `docs/system-architecture.md` with the media flow
- Future: populate `OutboundMessage.media` from tool results directly (removes LLM marker dependency) if this proves fragile
