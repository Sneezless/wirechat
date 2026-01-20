import asyncio
import websockets
import sys

colours = True
if not sys.stdout.isatty():
    colours = False
# ---------- colours ----------

RESET  = "\033[0m"
RED    = "\033[31m"
GREEN  = "\033[32m"
CYAN   = "\033[36m"
YELLOW = "\033[33m"
DIM = "\033[90m"

def str_to_bool(s):
    """
    Converts a string to a boolean, handling various case-insensitive truthy/falsy values.

    Truthy values: 'y', 'yes', 't', 'true', 'on', '1', True (if passed directly)
    Falsy values:  'n', 'no', 'f', 'false', 'off', '0', False (if passed directly)
    """
    if isinstance(s, bool):
        return s
    if not isinstance(s, str):
        # Handle types like int, float, etc. if needed, but strings are common
        raise TypeError("Expected string or boolean value")

    s = s.strip().lower() # Standardize the input

    if s in ('yes', 'true', 't', 'y', '1', 'on'):
        return True
    elif s in ('no', 'false', 'f', 'n', '0', 'off'):
        return False
    else:
        raise ValueError(f"Boolean value expected, got: '{s}'")
if len(sys.argv[] > 0):
    COLOURS = sys.argv[1]
if len(sys.argv[] > 1):
    LOCALUNSECURE = str_to_bool(sys.argv[2])

def colourise(message):
    if not colours:
        return message

    if message.startswith("SYS"):
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

# ---------- input prompts ----------

host = input(f"{YELLOW}Host (default: chat.sneezless.com): {RESET}").strip() or "chat.sneezless.com"
port_input = input(f"{YELLOW}Port (default: 443): {RESET}").strip()
port = int(port_input) if port_input else 443

nickname = input(f"{YELLOW}Choose a nickname: {RESET}").strip()

# ---------- websocket handlers ----------

async def receive(ws):
    async for message in ws:
        print(colourise(message))

async def send(ws):
    while True:
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

        await ws.send(f"MSG {msg}")

# ---------- main ----------

async def main():
    uri = f"wss://{host}:{port}"
    if LOCALUNSECURE == True:
        uri = f"ws://{host}:{port}"
    try:
        async with websockets.connect(uri) as ws:
            # handshake
            greeting = await ws.recv()
            print(colourise(greeting))

            await ws.send(f"NICK {nickname}")

            await asyncio.gather(
                receive(ws),
                send(ws)
            )

    except (OSError, websockets.InvalidURI, websockets.InvalidHandshake) as e:
        print(f"{RED}Connection error: {e}{RESET}")

    except KeyboardInterrupt:
        print(f"{YELLOW}\nDisconnected.{RESET}")

    except Exception as e:
        print(f"{RED}Client error: {e}{RESET}")
        raise
    
try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("\rDisconnected.")
