import asyncio
import websockets
import sys

VERSION = "1.2.1"  #* Major.Minor.Patch

COLOURS = True
if not sys.stdout.isatty():
    COLOURS = False

LOCALUNSECURE = False

# ---------- colours ----------

RESET  = "\033[0m"
RED    = "\033[31m"
GREEN  = "\033[32m"
CYAN   = "\033[36m"
YELLOW = "\033[33m"
DIM    = "\033[90m"

# ---------- helpers ----------

def str_to_bool(s):
    if isinstance(s, bool):
        return s
    if not isinstance(s, str):
        raise TypeError("Expected string or boolean")

    s = s.strip().lower()

    if s in ('yes', 'true', 't', 'y', '1', 'on'):
        return True
    if s in ('no', 'false', 'f', 'n', '0', 'off'):
        return False

    raise ValueError(f"Boolean expected, got '{s}'")


if len(sys.argv) > 1:
    COLOURS = str_to_bool(sys.argv[1])
if len(sys.argv) > 2:
    LOCALUNSECURE = str_to_bool(sys.argv[2])


def local_valid_nickname(nick):
    return (
        1 <= len(nick) <= 20
        and nick.isprintable()
        and " " not in nick
    )


def colourise(message):
    if not COLOURS:
        return message

    if message.startswith("SYS") or message.startswith("LOCALSYS"):
        return f"{CYAN}{message}{RESET}"

    if message.startswith("ERR"):
        return f"{RED}{message}{RESET}"

    if message.startswith("MSG "):
        try:
            prefix, rest = message.split(" ", 1)
            ts, rest = rest.split("] ", 1)
            name, text = rest.split(": ", 1)

            return (
                f"{DIM}[{prefix}]{RESET} "
                f"{DIM}[{ts.lstrip('[')}]{RESET} "
                f"{GREEN}{name}{RESET}: {text}"
            )
        except ValueError:
            return f"{GREEN}{message}{RESET}"

    return message


# ---------- connection info ----------

host = input(f"{YELLOW}Host (default: chat.sneezless.com): {RESET}").strip() or "chat.sneezless.com"

port_input = input(f"{YELLOW}Port (default: 443): {RESET}").strip()
port = int(port_input) if port_input else 443

nickname = None


# ---------- websocket handlers ----------

from websockets.exceptions import (
    ConnectionClosedOK,
    ConnectionClosedError,
    ConnectionClosed
)


async def receive(ws):
    try:
        async for msg in ws:
            print(colourise(msg))

    except ConnectionClosedOK:
        pass

    except ConnectionClosedError:
        print(colourise("SYS Disconnected."))

    except asyncio.CancelledError:
        pass


async def send(ws):
    while True:
        try:
            msg = await asyncio.to_thread(input, "")
            msg = msg.strip()

            if not msg:
                continue

            if msg.lower() in {"/quit", "/exit"}:
                await ws.send("QUIT")
                await ws.close()
                break

            if msg.lower() == "/who":
                await ws.send("WHO")
                continue

            if msg.lower() == "/version":
                print(colourise(f"LOCALSYS Wirechat client v{VERSION}"))
                await ws.send("VERSION")
                continue

            if msg.lower() in {"/cmds", "/help"}:
                await ws.send("CMDS")
                continue

            if msg.lower() == "/ping":
                await ws.send("PING")
                continue

            if msg.lower() == "/uptime":
                await ws.send("UPTIME")
                continue

            if msg.lower() == "/stats":
                await ws.send("STATS")
                continue

            await ws.send(f"MSG {msg}")

        except ConnectionClosed:
            print(colourise("SYS Connection closed by server."))
            break

        except (EOFError, KeyboardInterrupt):
            return


# ---------- main connection ----------

async def main():
    uri = f"wss://{host}:{port}"
    if LOCALUNSECURE:
        uri = f"ws://{host}:{port}"

    async with websockets.connect(uri) as ws:
        receiver = asyncio.create_task(receive(ws))

        try:
            # ---- handshake ----
            await ws.send(f"NICK {nickname}")

            # wait for server response (ERR or normal SYS flow)
            resp = await ws.recv()

            if resp.startswith("ERR"):
                print(colourise(resp))
                return

            # print first SYS message if it's not an error
            print(colourise(resp))

            sender = asyncio.create_task(send(ws))

            await asyncio.wait(
                {sender, receiver},
                return_when=asyncio.FIRST_COMPLETED,
            )

        finally:
            try:
                await ws.send("QUIT")
            except Exception:
                pass

            for task in (receiver, sender):
                task.cancel()

            await ws.close()


# ---------- reconnect loop ----------

async def run_client():
    global nickname

    while True:

        # ---- nickname prompt + validation ----
        while True:
            nickname = input(f"{YELLOW}Choose a nickname: {RESET}").strip()

            if local_valid_nickname(nickname):
                break

            print(f"{RED}Invalid nickname (1–20 chars, no spaces).{RESET}")

        try:
            await main()

        except (OSError, websockets.InvalidURI, websockets.InvalidHandshake) as e:
            print(f"{RED}Connection error: {e}{RESET}")

        except Exception as e:
            print(f"{RED}Client error: {e}{RESET}")
            raise

        choice = input("Reconnect? [y/N]: ").strip().lower()

        try:
            if not str_to_bool(choice):
                break
        except ValueError:
            break


# ---------- entry ----------

try:
    asyncio.run(run_client())
except KeyboardInterrupt:
    print(f"{YELLOW}\nDisconnected.{RESET}")
