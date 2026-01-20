# Wirechat

Wirechat is a **minimal experimental chat system** using a small, custom **text-based wire protocol over WebSockets**.

It consists of:

* a Python asyncio WebSocket **server**
* a Python terminal **client**
* (optionally) a very simple browser client

This project is intended for **learning, experimentation, and exploration of protocol and server design**.
It is **not** intended for production use.

---

## Features

* Custom, human-readable wire protocol
* WebSocket transport (ws / wss)
* Single shared chat room
* Nickname-based identity (no accounts)
* Message broadcast
* `/who` command
* Bounded message replay on join
* Graceful shutdown
* Simple logging
* No database
* No authentication

---

## Non-goals

Wirechat intentionally does **not** include:

* User accounts or passwords
* Authentication or authorization
* Channels or rooms
* Message editing or deletion
* End-to-end encryption
* Moderation roles
* Scalability guarantees
* Protocol stability guarantees

If you need any of the above, this is the wrong project.

---

## Repository layout

```
.
├── server/
│   └── chat-server.py
├── client-python/
│   └── chat-client.py
├── client-browser/
│   └── index.html
└── logs/
```

(Names may vary slightly depending on your local setup.)

---

## Running locally

### Requirements

* Python 3.10+
* `websockets` library

Install dependencies:

```bash
pip install websockets
```

---

### Start the server

```bash
python chat-server.py
```

The server listens on:

```
ws://127.0.0.1:12345
```

---

### Run the Python client

```bash
python chat-client.py
```

When prompted:

```
Host: localhost
Port: 12345
```

---

## Deployment notes

In production, Wirechat is typically run:

```
Client ──(WSS/TLS)──▶ Nginx ──(WS)──▶ Python server
```

TLS termination is handled by Nginx (e.g. via Let’s Encrypt).
The Python server itself uses plain WebSockets.

---

## Wire protocol (overview)

All messages are UTF-8 text frames.

### Handshake

Client → Server:

```
NICK <nickname>
```

Server → Client:

```
SYS <message>
```

---

### Sending messages

Client → Server:

```
MSG <text>
```

Server → Clients:

```
MSG [<ISO-8601 timestamp>] <nickname>: <text>
```

---

### Commands

| Command | Description          |
| ------- | -------------------- |
| `WHO`   | List connected users |
| `QUIT`  | Cleanly disconnect   |

---

### Replay

On successful join, the server may send:

```
SYS Replay start (N messages)
MSG ...
SYS Replay end
```

These messages are sent **only to the joining client**.

---

## Logging

Operational logs and message persistence are kept separate.

* Operational logs: connections, errors, lifecycle
* Message logs: canonical message history for replay

Logs are written to daily files under `logs/`.

---

## License

MIT License.

See `LICENSE` for details.

---

## Disclaimer

This project is intentionally small and intentionally incomplete.
The protocol and implementation may change at any time.

Use it to learn. Break it. Modify it. Don’t rely on it.
