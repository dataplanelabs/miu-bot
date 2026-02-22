# Research Report: Claude Code SDK / Claude Agent SDK

**Date:** 2026-02-19
**Researcher:** ab6d5d9

---

## Executive Summary

The **Claude Code SDK** (now evolving into **Claude Agent SDK**) is Anthropic's official mechanism for using Claude Code programmatically. It differs fundamentally from the Anthropic API SDK: it runs the full Claude Code agent loop (tools, file editing, bash, MCP) rather than just making raw LLM API calls. The SDK operates by spawning the `claude` CLI as a subprocess and communicating via streaming JSON, wrapped in either a Python (`claude-code-sdk` / `claude-agent-sdk`) or TypeScript (`@anthropic-ai/claude-code`) library. Claude Max subscription **is** supported since the SDK piggybacks on the authenticated local Claude CLI session.

---

## Package Names (Definitive)

| Layer | Package | Status |
|---|---|---|
| CLI tool (Node.js) | `@anthropic-ai/claude-code` (npm) | Current: v2.1.45 |
| Python SDK (subprocess wrapper) | `claude-code-sdk` (PyPI) | Current: v0.0.25, older style |
| Python SDK (newer, agent-focused) | `claude-agent-sdk` (PyPI) | Newer, with `ClaudeAgentOptions` |
| TypeScript SDK | bundled in `@anthropic-ai/claude-code` | Same npm package as CLI |

**Important naming reality:** Anthropic is migrating from `claude-code-sdk` → `claude-agent-sdk`. The GitHub repo at `anthropics/claude-code-sdk-python` now redirects to `anthropics/claude-agent-sdk-python`. Both packages exist on PyPI; the agent SDK is the forward path.

---

## 1. What Is It and How Does It Differ from Anthropic API SDK

### Anthropic API SDK (`anthropic` pip package)
- Direct LLM calls: `client.messages.create(...)`
- Developer manages conversation state, tool loops, context
- Requires `ANTHROPIC_API_KEY`; all usage billed per-token via API
- No built-in agentic loop, file tools, bash, or MCP

### Claude Code SDK / Agent SDK
- Spawns the `claude` CLI binary as a subprocess internally
- Provides full agent loop: planning, tool use (Bash, Read, Write, MCP), multi-turn
- Developer gets streaming messages from the agent loop
- Can authenticate via Claude Max session (no per-token API billing required)
- Python API wraps subprocess communication; TypeScript SDK is bundled in `@anthropic-ai/claude-code`

**Key architectural difference:** Claude Agent SDK = subprocess wrapper around a full agentic runtime. Anthropic API SDK = HTTP client to raw model inference.

---

## 2. Authentication and Claude Max Support

The official docs at `https://docs.anthropic.com/en/docs/claude-code/sdk` confirm two auth modes:

### API Key (billing via Anthropic Console)
```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

### Claude Max / Pro Subscription (no API billing)
- Login via browser: `claude login`
- Stores session credentials in `~/.claude/`
- SDK and subprocess both pick up this session automatically
- **No API key needed; usage deducted from Claude Max plan quota**
- Also supported: Amazon Bedrock (`CLAUDE_CODE_USE_BEDROCK=1`), Google Vertex AI (`CLAUDE_CODE_USE_VERTEX=1`)

**Verdict: Claude Max subscription works with the SDK.** The CLI stores OAuth tokens locally; SDK subprocess inherits them.

---

## 3. Installation

### Python (recommended path for Python projects)

```bash
# Install CLI (prerequisite for claude-code-sdk)
npm install -g @anthropic-ai/claude-code

# Install Python SDK (older, stable)
pip install claude-code-sdk

# OR install newer agent SDK (bundled CLI - no separate npm install needed)
pip install claude-agent-sdk
```

Requirements: Python 3.10+, Node.js (for `claude-code-sdk`). The newer `claude-agent-sdk` bundles the CLI binary in the wheel — no Node.js install required.

### TypeScript / JavaScript

```bash
npm install @anthropic-ai/claude-code
```

The TypeScript SDK is included in this same package — it exports a `query()` function.

---

## 4. Basic Usage

### Python (`claude-code-sdk`, subprocess style)

```python
import asyncio
from claude_code_sdk import query, ClaudeCodeOptions

async def main():
    options = ClaudeCodeOptions(
        system_prompt="You are a helpful assistant",
        max_turns=3,
        allowed_tools=["Read", "Write", "Bash"],
        cwd="/path/to/project"
    )
    async for message in query(prompt="Fix the bug in main.py", options=options):
        print(message)

asyncio.run(main())
```

### Python (`claude-agent-sdk`, newer)

```python
import anyio
from claude_agent_sdk import query, ClaudeAgentOptions

async def main():
    options = ClaudeAgentOptions(
        system_prompt="You are a helpful assistant",
        max_turns=5,
        allowed_tools=["Read", "Write", "Bash"],
        permission_mode="acceptEdits",
        cwd="/path/to/project"
    )
    async for message in query(prompt="Refactor the auth module", options=options):
        print(message)

anyio.run(main())
```

### TypeScript

```typescript
import { query, ClaudeCodeOptions } from "@anthropic-ai/claude-code";

const options: ClaudeCodeOptions = {
  maxTurns: 5,
  systemPrompt: "You are a helpful assistant",
  cwd: "/path/to/project",
};

for await (const message of query({ prompt: "Review this PR", options })) {
  console.log(message);
}
```

---

## 5. Key Features

### Session Management
```python
from claude_code_sdk import query, ClaudeCodeOptions

# Resume last session
options = ClaudeCodeOptions(continue_conversation=True)

# Resume by session ID
options = ClaudeCodeOptions(resume="session-id-abc123")

# Sessions stored in ~/.claude/conversations/ as JSON
```

### Tool Control
```python
options = ClaudeCodeOptions(
    allowed_tools=["Read", "Write", "Bash", "mcp__filesystem"],
    disallowed_tools=["WebSearch"],
    permission_mode="acceptEdits"  # or "default" (prompt), "bypassPermissions"
)
```

### Custom In-Process MCP Tools (claude-agent-sdk only)
```python
from claude_agent_sdk import tool, create_sdk_mcp_server, ClaudeAgentOptions, ClaudeSDKClient

@tool("get_price", "Get current price for a symbol", {"symbol": str})
async def get_price(args):
    return {"content": [{"type": "text", "text": f"Price of {args['symbol']}: $100"}]}

server = create_sdk_mcp_server(name="market-tools", version="1.0.0", tools=[get_price])
options = ClaudeAgentOptions(mcp_servers={"market": server})

async with ClaudeSDKClient(options=options) as client:
    await client.query("What is the price of AAPL?")
    async for msg in client.receive_response():
        print(msg)
```

### Hooks (claude-agent-sdk)
Intercept tool calls before/after execution:
```python
from claude_agent_sdk import HookMatcher, ClaudeAgentOptions

async def block_dangerous_commands(input_data, tool_use_id, context):
    if "rm -rf" in input_data.get("tool_input", {}).get("command", ""):
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "Dangerous command blocked"
        }}
    return {}

options = ClaudeAgentOptions(
    hooks={"PreToolUse": [HookMatcher(matcher="Bash", hooks=[block_dangerous_commands])]}
)
```

### Streaming Output Formats
```bash
# Text (default)
claude -p "query" --output-format text

# JSON (structured, with metadata)
claude -p "query" --output-format json

# Streaming JSON (line-delimited, each message as event)
claude -p "query" --output-format stream-json
```

### MCP Configuration (external servers)
```bash
claude -p "query" --mcp-config mcp-servers.json
```

---

## 6. CLI Options (SDK-relevant)

| Flag | Purpose |
|---|---|
| `-p` / `--print` | Non-interactive mode (required for SDK) |
| `--output-format` | `text`, `json`, `stream-json` |
| `--resume` / `-r` | Resume session by ID |
| `--continue` / `-c` | Continue last session |
| `--max-turns` | Limit agentic turns |
| `--system-prompt` | Override system prompt |
| `--append-system-prompt` | Append to default system prompt |
| `--allowedTools` | Whitelist tools |
| `--disallowedTools` | Blacklist tools |
| `--mcp-config` | JSON file with MCP server config |
| `--permission-prompt-tool` | MCP tool for permission decisions |

---

## 7. Best Approach for Python Subagent Integration

**Recommendation: Use `claude-agent-sdk` (newer) if you want in-process MCP tools and hooks. Use `claude-code-sdk` (stable) if you just need simple subprocess queries.**

### For nanobot / Python project integration:

```python
# Option A: Simple query (claude-code-sdk, stable)
pip install claude-code-sdk
npm install -g @anthropic-ai/claude-code  # or use logged-in claude

from claude_code_sdk import query, ClaudeCodeOptions

# Option B: Full agent client (claude-agent-sdk, newer, bundles CLI)
pip install claude-agent-sdk
# No npm install needed - CLI bundled in wheel

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
```

**Auth for Claude Max:** Just ensure `claude login` has been run on the host machine. No API key needed. The SDK subprocess inherits the session.

### Pattern for nanobot subagent:
```python
import anyio
from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock

async def run_subagent(task: str, working_dir: str) -> str:
    result = []
    options = ClaudeAgentOptions(
        cwd=working_dir,
        max_turns=20,
        allowed_tools=["Read", "Write", "Bash", "Edit"],
        permission_mode="acceptEdits",
    )
    async for message in query(prompt=task, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    result.append(block.text)
    return "\n".join(result)
```

---

## Comparative Summary

| Feature | claude-code-sdk (v0.0.25) | claude-agent-sdk (newer) | Anthropic API SDK |
|---|---|---|---|
| Agent loop | Yes (subprocess) | Yes (subprocess) | No (manual) |
| Claude Max auth | Yes | Yes | No (API key only) |
| Streaming | Yes | Yes | Yes |
| Custom tools | Via external MCP | In-process MCP + hooks | Manual tool_use |
| Multi-turn sessions | Yes (-c/-r flags) | Yes + ClaudeSDKClient | Manual state |
| Requires Node.js | Yes | No (bundled) | No |
| PyPI package | `claude-code-sdk` | `claude-agent-sdk` | `anthropic` |
| Stability | Stable (v0.0.x) | Newer, evolving | Very stable |

---

## Sources

- Official SDK docs: https://docs.anthropic.com/en/docs/claude-code/sdk
- npm package: https://www.npmjs.com/package/@anthropic-ai/claude-code (v2.1.45)
- PyPI package: `claude-code-sdk` v0.0.25 (verified via pip index)
- GitHub Python Agent SDK: https://github.com/anthropics/claude-agent-sdk-python
- Gemini research synthesis (Feb 2026)

---

## Unresolved Questions

1. **PyPI `claude-agent-sdk` version:** Gemini reported v0.1.37 but pip index wasn't directly accessible for confirmation. The GitHub repo is authoritative.
2. **Claude Max rate limits via SDK:** Exact quota behavior when Claude Max session is used through SDK (vs interactive CLI) is not documented — may hit same rate limits as interactive use.
3. **`claude-agent-sdk` production readiness:** The migration guide mentions breaking changes from `ClaudeCodeOptions` → `ClaudeAgentOptions`; the newer SDK is still evolving rapidly (bundled CLI version tracking suggests active development).
4. **Session isolation in concurrent subagents:** Whether multiple concurrent `query()` calls with `cwd` set properly maintain isolated sessions or share state needs verification from Anthropic docs or testing.
