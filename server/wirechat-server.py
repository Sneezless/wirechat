import asyncio
import websockets
from datetime import date, datetime
import signal
import os
import time

# ---------- graceful shutdown ----------

stop_event = asyncio.Event()

def shutdown():
    stop_event.set()

signal.signal(signal.SIGTERM, lambda *_: shutdown())
signal.signal(signal.SIGINT, lambda *_: shutdown())


def is_restart():
    return os.path.exists("/run/chat-server.restart")

# ---------- config ----------

SERVER_START_TIME = time.monotonic()
LOG_DIR = "logs"
HOST = "127.0.0.1"
PORT = 12345
MAX_MSG_LEN = 2048
HISTORY_LINES = 50
VERSION = "1.0.0" #* MAJOR.MINOR.PATCH

clients = {}  # websocket -> nickname
unformattedDate = date.today()

os.makedirs(LOG_DIR, exist_ok=True)

COMMAND_HELP = {
    "WHO":  "List connected users",
    "CMDS": "Show available commands",
    "HELP": "An alias of CMDS",
    "QUIT": "Disconnect from the server",
    "PING": "A simple PING PONG command",
    "UPTIME": "Get uptime",
    "STATS": "Get server stats"
}

stats = {
    "messages_session": 0,
    "messages_total": 0,
}


# ---------- logging ----------

def log_line(filename, message):
    t = datetime.now().strftime("%H.%M.%S")
    with open(filename, "a", encoding="utf-8") as f:
        f.write(f"\n{t}: {message}")

def log_safe(filename, message):
    try:
        log_line(filename, message)
    except Exception:
        pass

def log_file(kind):
    return f"{LOG_DIR}/{unformattedDate.isoformat()}-{kind}.txt"

def persist_message(filename, message):
    with open(filename, "a", encoding="utf-8") as f:
        f.write(message + "\n")

# ---------- helpers ----------

def valid_nickname(nick):
    return (
        1 <= len(nick) <= 20
        and nick.isprintable()
        and " " not in nick
    )

async def broadcast(message):
    dead = []
    for ws in clients:
        try:
            await ws.send(message)
        except Exception as e:
            dead.append(ws)
            log_safe(log_file("errors"), f"BROADCAST_FAIL {clients.get(ws)} {e}")

    for ws in dead:
        clients.pop(ws, None)

def load_recent_messages():
    path = f"{LOG_DIR}/{unformattedDate.isoformat()}-messages.txt"
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            return lines[-HISTORY_LINES:]
    except FileNotFoundError:
        return []
    
async def shutdown_server():
    if is_restart():
        await broadcast("SYS Server restarting")
        log_safe(log_file("server"), "SERVER_RESTART")
    else:
        await broadcast("SYS Server shutting down")
        log_safe(log_file("server"), "SERVER_SHUTDOWN")

    for ws in list(clients.keys()):
        try:
            await ws.close(code=1001, reason="Server restart" if is_restart() else "Server shutdown")
        except Exception:
            pass

def format_uptime(seconds):
    mins, sec = divmod(int(seconds), 60)
    hrs, mins = divmod(mins, 60)
    days, hrs = divmod(hrs, 24)

    if days:
        return f"{days}d {hrs}h {mins}m"
    if hrs:
        return f"{hrs}h {mins}m"
    if mins:
        return f"{mins}m {sec}s"
    return f"{sec}s"

# ---------- client handler ----------

async def handle_client(websocket):
    peer = websocket.remote_address
    log_safe(log_file("connections"), f"CONNECT_ATTEMPT {peer}")

    await websocket.send("SYS Send: NICK <name>")

    try:
        raw = await websocket.recv()
    except Exception as e:
        log_safe(log_file("errors"), f"HANDSHAKE_FAIL {peer} {e}")
        return

    if not raw.startswith("NICK "):
        await websocket.send("ERR Expected: NICK <name>")
        log_safe(log_file("errors"), f"BAD_HANDSHAKE {peer} {raw!r}")
        await websocket.close()
        return

    nickname = raw[5:].strip()

    if not valid_nickname(nickname):
        await websocket.send("ERR Invalid nickname")
        log_safe(log_file("errors"), f"BAD_NICK {peer} {nickname!r}")
        await websocket.close()
        return

    if nickname in clients.values():
        await websocket.send("ERR Nickname already in use")
        log_safe(log_file("errors"), f"DUPLICATE_NICK {peer} {nickname}")
        await websocket.close()
        return

    clients[websocket] = nickname
    log_safe(log_file("connections"), f"CONNECT {nickname} {peer}")
    await broadcast(f"SYS {nickname} joined the chat!")

    history = load_recent_messages()
    if history:
        await websocket.send(
            f"SYS Replay start ({len(history)} messages)"
        )

        for line in history:
            await websocket.send(f"MSG {line.strip()}")

        await websocket.send("SYS Replay end")

    # --- message loop ---
    try:
        async for raw in websocket:
            raw = raw.strip()
            if len(raw) > MAX_MSG_LEN:
                await websocket.send("ERR Message too large")
                log_safe(log_file("errors"), f"MSG_TOO_LARGE {nickname}")
                await websocket.close(code=1009)
                break

            if raw == "QUIT":
                log_safe(log_file("connections"), f"QUIT {nickname}")
                break

            if raw == "WHO":
                names = sorted(clients.values())
                await websocket.send(f"SYS Online ({len(names)}): " + ", ".join(names))
                continue

            if raw == "VERSION":
                await websocket.send(f"SYS Wirechat server v{VERSION}")
                continue

            if raw == "CMDS":
                lines = ["Available commands:"]
                for name, desc in sorted(COMMAND_HELP.items()):
                    lines.append(f"/{name.lower()} – {desc}")

                await websocket.send("SYS " + " | ".join(lines))
                continue

            if raw == "PING":
                await websocket.send("PONG")
                continue

            if raw == "UPTIME":
                uptime = time.monotonic() - SERVER_START_TIME
                await websocket.send(f"SYS Uptime: {format_uptime(uptime)}")   
                continue

            if raw == "STATS":
                uptime = time.monotonic() - SERVER_START_TIME
                await websocket.send(
                    f"SYS Users: {len(clients)} | "
                    f"Uptime: {format_uptime(uptime)} | "
                    f"Messages (session): {stats['messages_session']}"
                )
                continue

            if not raw.startswith("MSG "):
                await websocket.send("ERR Expected: MSG <text>")
                log_safe(log_file("errors"), f"BAD_MSG {nickname} {raw!r}")
                continue

            text = raw[4:].strip()
            timestamp = datetime.now().isoformat(timespec="seconds")
            sender = clients.get(websocket, "unknown")

            line = f"[{timestamp}] {sender}: {text}"
            stats['messages_session'] += 1
            persist_message(
                f"{LOG_DIR}/{unformattedDate.isoformat()}-messages.txt",
                line
            )   

            await broadcast(f"MSG {line}")

    except Exception as e:
        log_safe(log_file("errors"), f"CLIENT_ERROR {nickname} {e}")

    finally:
        left = clients.pop(websocket, None)
        if left:
            log_safe(log_file("connections"), f"DISCONNECT {left}")
            await broadcast(f"SYS {left} left the chat!")

# ---------- main ----------

async def main():
    log_safe(log_file("server"), "SERVER_START")
    print("WS server listening...")

    async with websockets.serve(
        handle_client,
        HOST,
        PORT,
        ping_interval=30,
        ping_timeout=10
    ):
        await stop_event.wait()
        log_safe(log_file("server"), "SERVER_SHUTDOWN")
        await shutdown_server()


    log_safe(log_file("server"), "SERVER_STOP")

asyncio.run(main())
