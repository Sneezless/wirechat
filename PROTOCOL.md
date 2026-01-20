# Wirechat Protocol

This document describes the Wirechat wire protocol as implemented by the reference server and client.

Wirechat is a **line-oriented, text-based protocol** transported over WebSockets.
It is intentionally simple, human-readable, and server-authoritative.

---

## Transport

* WebSocket (`ws://` or `wss://`)
* UTF-8 text frames only
* One command or message per frame

Binary frames are not used.

---

## Connection Lifecycle

1. Client connects to the server
2. Server prompts for nickname
3. Client sends nickname
4. Server acknowledges and optionally sends replay
5. Normal message/command exchange begins
6. Either side may close the connection at any time

---

## Handshake

### Server → Client

```
SYS Send: NICK <name>
```

### Client → Server

```
NICK <nickname>
```

Nickname rules:

* 1–20 characters
* printable ASCII
* no spaces
* must be unique among connected clients

If the nickname is invalid or already in use, the server responds with an error and closes the connection.

---

## Server Messages

Server-originated messages always begin with one of the following prefixes:

### `SYS`

Informational messages (joins, leaves, notices, status).

Example:

```
SYS greg joined the chat!
```

### `ERR`

Protocol or validation errors.

Example:

```
ERR Invalid nickname
```

---

## Client Messages

### Chat messages

```
MSG <text>
```

* `<text>` may be any printable UTF-8 string
* maximum length enforced by server
* messages are broadcast to all connected clients

---

## Commands

Commands are sent as **single uppercase words** with no leading slash.

Clients may provide a slash-prefixed UI (`/stats`, `/who`, etc), but the wire protocol does not include `/`.

### Supported Commands

#### `WHO`

List currently connected users.

Response:

```
SYS Online (N): user1, user2, ...
```

---

#### `PING`

Health check.

Response:

```
PONG
```

---

#### `UPTIME`

Server uptime since last start.

Response:

```
SYS Uptime: <human-readable>
```

---

#### `STATS`

Basic server statistics.

Response:

```
SYS Users: N | Uptime: X | Messages (session): Y
```

---

#### `VERSION`

Server version string.

Response:

```
SYS Wirechat server vX.Y.Z
```

---

#### `CMDS`

List available commands.

Response:

```
SYS Available commands: /who – ..., /stats – ...
```

---

#### `QUIT`

Client requests clean disconnect.

The server closes the connection.

---

## Replay

On successful handshake, the server may send recent messages:

```
SYS Replay start (N messages)
MSG [timestamp] user: text
...
SYS Replay end
```

Replay:

* is bounded
* is informational
* does not imply delivery guarantees

---

## Errors

If a client sends an invalid command or malformed message, the server responds with `ERR` and continues the session where possible.

Certain errors (e.g. oversized messages) may cause the server to close the connection.

---

## Protocol Guarantees

Wirechat intentionally **does not** provide:

* authentication
* identity persistence
* message delivery guarantees
* message ordering guarantees across reconnects
* private messages
* channels or rooms

All state is scoped to a single connection session.

---

## Design Goals

* Simple to implement
* Easy to debug with raw text
* Safe for small deployments
* Explicit server authority
* No hidden state

---

## Versioning

Protocol changes that break compatibility should increment the server protocol version and be documented here.

---

## Summary

Wirechat is a deliberately minimal chat protocol designed for clarity and reliability over feature completeness.

If you need accounts, permissions, channels, or moderation, this protocol is intentionally not the right tool.
