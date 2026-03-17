# Setup Guide: Zalo AI Assistant

Step-by-step guide to connect miu-bot to Zalo via the ZCA-CLI WebSocket bridge.

## Architecture

```
Zalo Servers <-> zca-js <-> ZCA Bridge Server (TypeScript)
                                    |
                               WebSocket (ws://127.0.0.1:3002)
                                    |
                               Miu-Bot ZaloChannel (Python)
                                    |
                               MessageBus -> AgentLoop -> LLM
```

Two processes run on the same machine:
1. **ZCA Bridge** — TypeScript process that logs into Zalo and exposes a WebSocket server
2. **Miu-Bot Gateway** — Python process that connects to the bridge as a WebSocket client

## Prerequisites

- miu-bot installed (pip, uv, or from source)
- ZCA-CLI repo cloned with `bun` installed
- Zalo account (personal account, not OA)
- LLM API key (any supported provider)

## 1. Setup ZCA-CLI

```bash
git clone <zca-cli-repo-url>
cd zca-cli-ts
bun install
```

## 2. Login to Zalo

```bash
# Login via QR code — scan with Zalo mobile app
bun run src/index.ts auth login

# Verify login
bun run src/index.ts auth status

# Cache contacts (enables sender name resolution)
bun run src/index.ts auth cache-refresh
```

The QR code appears in your terminal. Open Zalo on your phone, go to **Settings > QR Scanner**, and scan it.

## 3. Start the Bridge

```bash
# Basic (no auth)
bun run src/index.ts bridge

# With auth token (recommended)
bun run src/index.ts bridge --token YOUR_SECRET_TOKEN

# With auto-reconnect on Zalo disconnect
bun run src/index.ts bridge --keep-alive --token YOUR_SECRET_TOKEN

# Custom port
bun run src/index.ts bridge --port 3002
```

| Option | Default | Description |
|--------|---------|-------------|
| `-p, --port` | `3002` | WebSocket server port |
| `-t, --token` | none | Auth token for client connections (or `ZCA_BRIDGE_TOKEN` env) |
| `-k, --keep-alive` | off | Auto-restart listener on Zalo disconnect |

## 4. Test the Bridge (Optional)

Open another terminal and connect with `wscat`:

```bash
# Install wscat
npm i -g wscat

# Connect
wscat -c ws://127.0.0.1:3002
```

- **Receive**: Send a message to the logged-in Zalo account from another phone — JSON appears in wscat
- **Send**: Type a send command:
  ```json
  {"type":"send","to":"THREAD_ID","text":"Hello from bridge","threadType":1}
  ```
  - `threadType`: `1` = DM, `2` = Group
  - `to`: use the `threadId` from a received message

If using token auth, send auth first:
```json
{"type":"auth","token":"YOUR_SECRET_TOKEN"}
```

## 5. Configure Miu-Bot

Edit `~/.miu_bot/config.json`:

```json
{
  "providers": {
    "anthropic": {
      "apiKey": "sk-ant-..."
    }
  },
  "channels": {
    "zalo": {
      "enabled": true,
      "bridgeUrl": "ws://localhost:3002",
      "bridgeToken": "YOUR_SECRET_TOKEN",
      "allowFrom": []
    }
  }
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `enabled` | Yes | Set `true` to activate |
| `bridgeUrl` | No | WebSocket URL (default: `ws://localhost:3002`) |
| `bridgeToken` | No | Must match bridge `--token` value. Empty = no auth |
| `allowFrom` | No | Zalo user IDs allowed to chat. Empty = anyone |

## 6. Start Miu-Bot

```bash
# Start bridge first (keep running)
bun run src/index.ts bridge --keep-alive --token YOUR_SECRET_TOKEN

# Then start miu-bot (in another terminal)
miu-bot gateway
```

Miu-Bot auto-connects to the bridge. If the bridge isn't up yet, it retries every 5 seconds.

## 7. Run as Background Services (Production)

### Bridge (systemd)

Create `/etc/systemd/system/zca-bridge.service`:

```ini
[Unit]
Description=ZCA Bridge Server for Miu-Bot
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/path/to/zca-cli-ts
ExecStart=/usr/local/bin/bun run src/index.ts bridge --keep-alive --token YOUR_SECRET_TOKEN
Restart=always
RestartSec=10
Environment=HOME=/home/YOUR_USERNAME

[Install]
WantedBy=multi-user.target
```

### Miu-Bot (systemd)

Create `/etc/systemd/system/miu-bot.service`:

```ini
[Unit]
Description=Miu-Bot AI Assistant Gateway
After=network.target zca-bridge.service

[Service]
Type=simple
User=YOUR_USERNAME
ExecStart=/usr/local/bin/miu-bot gateway
Restart=always
RestartSec=10
Environment=HOME=/home/YOUR_USERNAME

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable zca-bridge miu-bot
sudo systemctl start zca-bridge miu-bot
```

### tmux (quick setup)

```bash
tmux new -s zca-bridge
bun run src/index.ts bridge --keep-alive --token YOUR_SECRET_TOKEN
# Ctrl+B, D to detach

tmux new -s miu-bot
miu-bot gateway
# Ctrl+B, D to detach
```

## 8. Security

- Bridge binds to `127.0.0.1` only — no external network access
- Use `--token` to prevent unauthorized WebSocket connections
- Set `allowFrom` with specific Zalo user IDs to restrict access
- Protect config file: `chmod 600 ~/.miu_bot/config.json`
- Only one Zalo listener per account — don't run `zca listen` and `zca bridge` simultaneously

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Bridge won't start | Run `zca auth status` — must be logged in first |
| QR code expired | Run `zca auth login` again |
| Miu-Bot can't connect | Check bridge is running. Verify port and token match |
| Messages not received | Check `allowFrom` includes sender's user ID (or leave empty) |
| Zalo disconnects | Use `--keep-alive` flag for auto-reconnect |
| Wrong reply target | Verify `threadType` is correct: 1=DM, 2=Group |
| Duplicate messages | Don't run `zca listen` and `zca bridge` at the same time |
