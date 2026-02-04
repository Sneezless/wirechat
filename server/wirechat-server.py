import asyncio
import websockets
from datetime import date, datetime
import signal
import os
import time
import re
from websockets import ConnectionClosed

# ---------- graceful shutdown ----------

# stop_event = asyncio.Event()

# def shutdown():
#     stop_event.set()

# signal.signal(signal.SIGTERM, lambda *_: shutdown())
# signal.signal(signal.SIGINT, lambda *_: shutdown())

stop_event = asyncio.Event()

def request_shutdown():
    stop_event.set()

# ---------- config ----------

SERVER_START_TIME = time.monotonic()
HOST = "127.0.0.1"
PORT = 12345
MAX_MSG_LEN = 2048
HISTORY_LINES = 50
VERSION = "1.2.1" #* MAJOR.MINOR.PATCH
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
CONFIG_PATH = os.path.join(BASE_DIR, "config")

ADMIN_TOKEN = None
# 1) try environment first (production)
if "WIRECHAT_ADMIN_TOKEN" in os.environ:
    ADMIN_TOKEN = os.environ["WIRECHAT_ADMIN_TOKEN"]

# 2) fallback to local config (dev)
else:
    try:
        with open(os.path.join(CONFIG_PATH, "secrets.txt"), "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("ADMIN_TOKEN="):
                    ADMIN_TOKEN = line.strip().split("=",1)[1]
    except FileNotFoundError:
        pass

if not ADMIN_TOKEN:
    raise RuntimeError("ADMIN_TOKEN not set")

def load_forbidden():
    words = []
    with open(os.path.join(CONFIG_PATH,"forbidden.txt"), "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip().lower()
            if line:
                words.append(line)
    return words

FORBIDDEN = load_forbidden()
FORBIDDEN_PATTERNS = []

for word in FORBIDDEN:
    escaped = re.escape(word)

    if " " in word:
        # normal phrase (with spaces)
        FORBIDDEN_PATTERNS.append(
            re.compile(escaped, re.IGNORECASE)
        )

        # merged phrase (no spaces)
        merged = re.escape(word.replace(" ", ""))
        FORBIDDEN_PATTERNS.append(
            re.compile(merged, re.IGNORECASE)
        )

    else:
        # single word with boundaries
        FORBIDDEN_PATTERNS.append(
            re.compile(rf"\b{escaped}\b", re.IGNORECASE)
        )

clients = {}  # websocket -> nickname
admins = set()
kicked = set()

os.makedirs(LOG_DIR, exist_ok=True)

COMMAND_HELP = {
    "WHO":  "List connected users",
    "VERSION": "Get server and client version",
    "CMDS": "Show available commands",
    "HELP": "An alias of CMDS",
    "QUIT": "Disconnect from the server",
    "PING": "A simple PING PONG command",
    "UPTIME": "Get uptime",
    "STATS": "Get server stats",
    "ADMIN": "Enter admin token",
    "IMG": "Sends an image"
}

COMMAND_ADMIN = {
    "KICK": "Kick a user by nickname"
}

stats = {
    "messages_session": 0
}

RESTART_FLAG = os.path.join(BASE_DIR, ".restart")

def is_restart():
    return os.path.exists(RESTART_FLAG)

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
    today = date.today().isoformat()
    return f"{LOG_DIR}/{today}-{kind}.txt"

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
    for ws in list(clients):
        try:
            await ws.send(message)
        except Exception as e:
            dead.append(ws)
            log_safe(log_file("errors"), f"BROADCAST_FAIL {clients.get(ws)} {e}")

    for ws in dead:
        clients.pop(ws, None)

def load_recent_messages():
    today = date.today().isoformat()
    path = f"{LOG_DIR}/{today}-messages.txt"
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            return lines[-HISTORY_LINES:]
    except FileNotFoundError:
        return []
    
async def shutdown_server():
    restarting = is_restart()

    if restarting:
        msg = "SYS Server restarting"
        log_safe(log_file("server"), "SERVER_RESTART")
    else:
        msg = "SYS Server shutting down"
        log_safe(log_file("server"), "SERVER_SHUTDOWN")

    for ws in list(clients.keys()):
        try:
            await asyncio.wait_for(ws.send(msg), timeout=2)
        except Exception:
            pass

        try:
            await asyncio.wait_for(
                ws.close(
                    code=1001,
                    reason="Server restart" if restarting else "Server shutdown"
                ),
                timeout=2
            )
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

LEET_MAP = str.maketrans({
    "0": "o",
    "1": "i",
    "3": "e",
    "4": "a",
    "5": "s",
    "7": "t",
    "@": "a",
    "$": "s",
    "!": "i",
})

def normalise(text):
    text = text.lower()
    text = text.translate(LEET_MAP)

    # remove separators people use to bypass filters
    text = re.sub(r"[\W_]+", " ", text)
    text = re.sub(r"[\u200b\u200c\u200d]+", "", text)

    # collapse spaces
    text = re.sub(r"\s+", " ", text).strip()

    return text


def contains_forbidden(text):
    norm = normalise(text)

    for pattern in FORBIDDEN_PATTERNS:
        if pattern.search(norm):
            return True

    return False


# ---------- client handler ----------

async def handle_client(websocket):
    peer = websocket.remote_address
    log_safe(log_file("connections"), f"CONNECT_ATTEMPT {peer}")

    await websocket.send("SYS Protocol wirechat/1\n")
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
    
    if contains_forbidden(nickname):
        await websocket.send("ERR Nickname contains forbidden words")
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
            line = line.strip()

            # replay images properly
            if ": [IMG] " in line:
                # format: [time] nick: [IMG] url
                prefix, url = line.split(": [IMG] ", 1)

                # prefix is "[time] nick"
                parts = prefix.split(" ", 1)

                if len(parts) == 2:
                    timestamp = parts[0][1:-1]  # remove [ ]
                    sender = parts[1]

                    await websocket.send(f"IMG [{timestamp}] {sender} {url}")
                else:
                    await websocket.send(f"MSG {line}")

            else:
                await websocket.send(f"MSG {line}")


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
                
                if websocket in admins:
                    lines = ["Available admin commands:"]
                    for name, desc in sorted(COMMAND_ADMIN.items()):
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
            
            if raw.startswith("ADMIN "):
                token = raw[6:].strip()

                if token == ADMIN_TOKEN:
                    admins.add(websocket)
                    await websocket.send("SYS Admin privileges granted")
                    log_safe(log_file("server"), f"ADMIN_GRANTED {clients.get(websocket)}")
                else:
                    await websocket.send("ERR Invalid admin token")

                continue
            
            if raw.startswith("KICK "):
                if websocket not in admins:
                    await websocket.send("ERR Admin only command")
                    continue

                target = raw[5:].strip()

                # find websocket for that nickname
                target_ws = None
                for ws, name in clients.items():
                    if name.lower() == target.lower():
                        target_ws = ws
                        break

                if not target_ws:
                    await websocket.send(f"ERR User not found: {target}")
                    continue

                name = clients.get(target_ws)

                # mark as kicked and close connection
                kicked.add(target_ws)
                try:
                    await target_ws.send("SYS You were kicked by an admin")
                except:
                    pass

                await target_ws.close(code=4000, reason="Kicked by admin")

                if name:
                    await broadcast(f"SYS {name} was kicked by an admin")
                    log_safe(log_file("server"), f"KICK {name}")

                continue
            
            if raw.startswith("IMG"):

                parts = raw.split(" ", 1)

                if len(parts) == 1 or not parts[1].strip():
                    await websocket.send("ERR IMG requires a URL")
                    continue

                url = parts[1].strip()

                if not re.match(r"^https?://\S+$", url):
                    await websocket.send("ERR Invalid image URL")
                    continue

                timestamp = datetime.now().isoformat(timespec="seconds")
                sender = clients.get(websocket, "unknown")

                line = f"[{timestamp}] {sender} {url}"

                stats["messages_session"] += 1

                persist_message(
                    f"{LOG_DIR}/{date.today().isoformat()}-messages.txt",
                    f"[{timestamp}] {sender}: [IMG] {url}"
                )

                await broadcast(f"IMG {line}")
                continue



            if not raw.startswith("MSG "):
                await websocket.send("ERR Expected: MSG <text>")
                log_safe(log_file("errors"), f"BAD_MSG {nickname} {raw!r}")
                continue
            


            text = raw[4:].strip()
            
            if contains_forbidden(text):
                await websocket.send("ERR Message contains forbidden content")
                continue
            timestamp = datetime.now().isoformat(timespec="seconds")
            sender = clients.get(websocket, "unknown")

            line = f"[{timestamp}] {sender}: {text}"
            stats['messages_session'] += 1
            today = date.today().isoformat()
            persist_message(
                f"{LOG_DIR}/{today}-messages.txt",
                line
            )  

            await broadcast(f"MSG {line}")

    except ConnectionClosed:
        # normal disconnect (quit, kick, network drop)
        pass

    except Exception as e:
        log_safe(log_file("errors"), f"CLIENT_ERROR {nickname} {e}")

    finally:
        admins.discard(websocket)
        left = clients.pop(websocket, None)

        if left:
            log_safe(log_file("connections"), f"DISCONNECT {left}")

            if websocket in kicked:
                kicked.discard(websocket)
            else:
                await broadcast(f"SYS {left} left the chat!")

# ---------- main ----------

async def main():
    log_safe(log_file("server"), "SERVER_START")
    print("WS server listening...")
    try:
        os.remove(RESTART_FLAG)
    except FileNotFoundError:
        pass

    # --- register graceful shutdown signals ---
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, request_shutdown)
        except NotImplementedError:
            signal.signal(sig, lambda *_: request_shutdown())

    # --- start websocket server ---
    server = await websockets.serve(
        handle_client,
        HOST,
        PORT,
        ping_interval=30,
        ping_timeout=10
    )

    # --- wait for shutdown signal ---
    await stop_event.wait()

    # --- notify + close clients first ---
    await shutdown_server()

    # --- stop accepting new connections ---
    server.close()
    await server.wait_closed()

    log_safe(log_file("server"), "SERVER_STOP")


asyncio.run(main())
