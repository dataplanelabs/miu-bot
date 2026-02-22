---
phase: 1
title: "ZCA Bridge Server"
status: complete
priority: P1
---

# Phase 1: ZCA Bridge Server (TypeScript)

## Context

- Parent plan: [plan.md](./plan.md)
- ZCA-CLI repo: `/Users/vanducng/git/personal/dataplanelabs/zca/zca-cli-ts/`
- Reference: WhatsApp bridge server at `nanobot/bridge/src/server.ts`
- Reference: ZCA listen command at `zca-cli-ts/src/commands/listen.ts`

## Overview

Create `src/commands/bridge.ts` in ZCA-CLI that starts a WebSocket server (localhost-bound), logs into Zalo via `zca-js`, listens for incoming messages, and accepts send commands from nanobot.

## Key Insights

- `listen.ts` already does 80% of what we need: it logs in, starts `api.listener`, handles messages
- WhatsApp bridge `server.ts` provides exact WS server pattern: auth handshake, broadcast, command handling
- `zca-js` API: `api.sendMessage(text, threadId, ThreadType.User|Group)`
- Message events: `msg.threadId`, `msg.uidFrom`, `msg.data?.content`
- Group detection: `msg.threadId !== msg.uidFrom`
- Contact names via `getFriendName()` / `getGroupName()` from `lib/contacts`
- `createZalo()` + `zalo.login(credentials)` pattern from `lib/api.ts`

## Requirements

- WS server on configurable port (default 3002), bound to 127.0.0.1
- Optional token auth (same pattern as WhatsApp bridge)
- Broadcast incoming Zalo messages to all connected WS clients
- Accept `{ type: "send" }` commands and call `api.sendMessage()`
- Keep-alive with reconnection on Zalo disconnect
- Register as `zca bridge` CLI command

## Related Code Files

**Create:**
- `src/commands/bridge.ts` — Bridge server command

**Modify:**
- `src/index.ts` — Register bridge command
- `package.json` — Add `ws` dependency

## Implementation Steps

1. Install `ws` dependency:
   ```bash
   cd /Users/vanducng/git/personal/dataplanelabs/zca/zca-cli-ts
   bun add ws && bun add -d @types/ws
   ```

2. Create `src/commands/bridge.ts`:
   ```typescript
   import { Command } from 'commander';
   import { WebSocketServer, WebSocket } from 'ws';
   import { ThreadType, type Message } from 'zca-js';
   import { createZalo } from '../lib/api';
   import { getCredentials } from '../lib/config';
   import { getFriendName, getGroupName } from '../lib/contacts';
   import { wrapAction } from '../utils/error';
   import { info, success, warn, error } from '../utils/output';

   export const bridgeCommand = new Command('bridge')
     .description('Start WebSocket bridge server for nanobot integration')
     .option('-p, --port <port>', 'WebSocket server port', '3002')
     .option('-t, --token <token>', 'Auth token for client connections')
     .option('-k, --keep-alive', 'Auto-restart on disconnect')
     .action(wrapAction(async (options) => {
       const port = parseInt(options.port, 10);
       const token = options.token || process.env.ZCA_BRIDGE_TOKEN;

       // Login to Zalo
       const credentials = getCredentials();
       if (!credentials) {
         error("Not logged in. Run 'zca auth login' first.");
         return;
       }
       const zalo = createZalo();
       const api = await zalo.login(credentials);

       // Track connected WS clients
       const clients = new Set<WebSocket>();

       const broadcast = (msg: Record<string, unknown>) => {
         const data = JSON.stringify(msg);
         for (const client of clients) {
           if (client.readyState === WebSocket.OPEN) {
             client.send(data);
           }
         }
       };

       // Setup client connection (after auth)
       const setupClient = (ws: WebSocket) => {
         clients.add(ws);
         ws.on('message', async (raw) => {
           try {
             const cmd = JSON.parse(raw.toString());
             if (cmd.type === 'send') {
               const threadType = cmd.threadType === 2 ? ThreadType.Group : ThreadType.User;
               await api.sendMessage(cmd.text, cmd.to, threadType);
               ws.send(JSON.stringify({ type: 'sent', to: cmd.to }));
             }
           } catch (err) {
             ws.send(JSON.stringify({ type: 'error', error: String(err) }));
           }
         });
         ws.on('close', () => { clients.delete(ws); info('Client disconnected'); });
         ws.on('error', () => { clients.delete(ws); });
       };

       // Start WS server (localhost only)
       const wss = new WebSocketServer({ host: '127.0.0.1', port });
       info(`Bridge server on ws://127.0.0.1:${port}`);

       wss.on('connection', (ws) => {
         if (token) {
           const timeout = setTimeout(() => ws.close(4001, 'Auth timeout'), 5000);
           ws.once('message', (data) => {
             clearTimeout(timeout);
             try {
               const msg = JSON.parse(data.toString());
               if (msg.type === 'auth' && msg.token === token) {
                 info('Client authenticated');
                 setupClient(ws);
               } else {
                 ws.close(4003, 'Invalid token');
               }
             } catch { ws.close(4003, 'Bad auth'); }
           });
         } else {
           info('Client connected');
           setupClient(ws);
         }
       });

       // Start Zalo listener
       const startListener = () => {
         const listener = api.listener;

         listener.on('message', async (msg: Message) => {
           const isGroup = msg.threadId !== msg.uidFrom;
           const senderName = getFriendName(msg.uidFrom) || msg.uidFrom;
           const threadName = isGroup ? (getGroupName(msg.threadId) || msg.threadId) : senderName;

           broadcast({
             type: 'message',
             threadType: isGroup ? 'group' : 'user',
             threadId: msg.threadId,
             threadName,
             senderId: msg.uidFrom,
             senderName,
             content: msg.data?.content || '',
             timestamp: Date.now(),
           });
         });

         listener.on('error', (err: Error) => {
           warn(`Listener error: ${err.message}`);
           broadcast({ type: 'status', status: 'disconnected' });
           if (options.keepAlive) scheduleReconnect();
         });

         listener.on('closed', () => {
           warn('Zalo connection closed');
           broadcast({ type: 'status', status: 'disconnected' });
           if (options.keepAlive) scheduleReconnect();
         });

         listener.start();
         broadcast({ type: 'status', status: 'connected' });
         success('Bridge running. Listening for Zalo messages...');
       };

       let reconnectAttempts = 0;
       const scheduleReconnect = () => {
         reconnectAttempts++;
         const delay = Math.min(1000 * 2 ** reconnectAttempts, 60000);
         warn(`Reconnecting in ${delay / 1000}s...`);
         setTimeout(startListener, delay);
       };

       startListener();
     }));
   ```

3. Register in `src/index.ts`:
   - Add import: `import { bridgeCommand } from './commands/bridge';`
   - Add: `program.addCommand(bridgeCommand);`

## Todo

- [x] Install `ws` + `@types/ws` in ZCA-CLI
- [x] Create `src/commands/bridge.ts`
- [x] Register command in `src/index.ts`
- [x] Test: `bun run src/index.ts bridge --port 3002`

## Success Criteria

- `zca bridge` starts WS server on localhost:3002
- Incoming Zalo messages are broadcast as JSON to WS clients
- Send commands from WS clients trigger `api.sendMessage()`
- Optional token auth works
- Keep-alive reconnects on Zalo disconnect

## Risk Assessment

- **zca-js listener stability**: Zalo may disconnect; mitigated by keep-alive option
- **Single listener per account**: Zalo only allows one listener; running `zca listen` and `zca bridge` simultaneously will conflict

## Security

- WS server bound to 127.0.0.1 only (no external access)
- Optional token auth for client connections
- No credentials exposed over WebSocket
