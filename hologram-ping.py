#!/usr/bin/env python3
"""Send a command to a collar using the Hologram API.

./hologram-ping.py --list
./hologram-ping.py --device-id 2373541                      # spoof-ping
./hologram-ping.py --device-id 2373541 --data lost
./hologram-ping.py --device-id 2373541 --at 300,900,1800,3600

Commands go out through Hologram's REST API, which pushes them to the SIM as a
UDP datagram on port 12345.

"""

import argparse
import os
import sys
import time
from datetime import datetime, timedelta

from utils import bad, dim, head, ok, request, value, warn

HOLOGRAM_API = "https://dashboard.hologram.io/api/1"
COLLAR_PORT = 12345
COLLAR_PROTOCOL = "UDP"
# Worst-case wait before the collar hears a command, since it only listens
# during its eDRX paging window. Mirrors CONFIG_LTE_EDRX_REQ_VALUE_LTE_M in the
# firmware, so it drifts if that changes: the collar should report the value the
# network actually granted instead. Override with COLLAR_EDRX_SECONDS.
DEFAULT_EDRX_SECONDS = 163.84
ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def load_env_file():
    """Read .env beside this script, without overriding the real environment."""
    if not os.path.exists(ENV_FILE):
        return

    with open(ENV_FILE) as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, val = line.partition("=")
            os.environ.setdefault(name.strip(), val.strip())


def hologram_credentials():
    """Basic auth pair for the Hologram REST API."""
    api_key = os.environ.get("HOLOGRAM_API_KEY")
    if not api_key:
        sys.exit(
            f"{bad('HOLOGRAM_API_KEY is not set')}\n"
            f"Copy {dim('.env.example')} to {dim('.env')} and fill it in."
        )
    return ("apikey", api_key)


def hologram_request(path, method="GET", body=None, query=None):
    """Call the Hologram API, exiting with a readable message on failure."""
    url = f"{HOLOGRAM_API}{path}"
    if query:
        supplied = "&".join(
            f"{name}={val}" for name, val in query.items() if val is not None
        )
        if supplied:
            url = f"{url}?{supplied}"

    try:
        return request(url, method=method, body=body, auth=hologram_credentials())
    except Exception as failure:
        sys.exit(f"{bad('Hologram API call failed')} {path}: {failure}")


def list_devices():
    """Print the devices this API key can see."""
    response = hologram_request(
        "/devices", query={"orgid": os.environ.get("HOLOGRAM_ORG_ID")}
    )
    devices = response.get("data") or []

    if not devices:
        print(warn("no devices returned"))
        return

    print(head(f"{'id':>10}  name"))
    for device in devices:
        print(f"{value(str(device.get('id'))):>10}  {device.get('name', '')}")


def send_cloud_message(device_id, payload):
    """Post one cloud message, returning Hologram's message id.

    The id means Hologram queued the command, not that the collar received it.
    Delivery cannot be confirmed from here: the collar only listens during its
    eDRX paging window, which can be minutes away, and no API call stays open
    that long. Read the collar's own log to see what arrived.
    """
    response = hologram_request(
        "/devices/messages",
        method="POST",
        body={
            "deviceids": [int(device_id)],
            "protocol": COLLAR_PROTOCOL,
            "port": COLLAR_PORT,
            "data": payload,
        },
    )

    queued = response.get("data") or []
    if queued and isinstance(queued[0], dict):
        return queued[0].get("messageid")
    return None


def collar_edrx_seconds():
    """How long the collar can sleep before it hears a command."""
    configured = os.environ.get("COLLAR_EDRX_SECONDS")
    try:
        return float(configured) if configured else DEFAULT_EDRX_SECONDS
    except ValueError:
        return DEFAULT_EDRX_SECONDS


PROGRESS_WIDTH = 30


def show_paging_progress(budget, window):
    """Count down the worst case wait until the collar opens its next window.

    The collar often reads sooner, since the command can land anywhere inside
    the eDRX cycle. This is the upper bound, not a prediction.
    """
    if budget <= 0 or not sys.stdout.isatty():
        return

    started = time.monotonic()

    while True:
        elapsed = time.monotonic() - started
        if elapsed >= budget:
            break

        filled = int(PROGRESS_WIDTH * elapsed / window)
        bar = "#" * min(filled, PROGRESS_WIDTH)
        bar = bar.ljust(PROGRESS_WIDTH, ".")
        print(f"\r  [{bar}] {window - elapsed:5.0f}s", end="", flush=True)
        time.sleep(0.1)

    print(f"\r\033[K  {dim('window elapsed, collar should have read it')}")


def run_send_schedule(device_id, payload, at):
    """Send on the requested offsets, one timed line per attempt."""
    offsets = sorted(float(o) for o in at.split(",") if o.strip()) if at else [0.0]
    edrx_seconds = collar_edrx_seconds()

    print(
        head(
            f"\n{payload!r} to device {device_id} "
            f"on {COLLAR_PROTOCOL} port {COLLAR_PORT}"
        )
    )
    print(dim(f"offsets: {[int(offset) for offset in offsets]}s\n"))

    started_at = time.monotonic()

    for index, offset in enumerate(offsets):
        seconds_to_wait = started_at + offset - time.monotonic()
        if seconds_to_wait > 0:
            time.sleep(seconds_to_wait)

        wall_clock = datetime.now().strftime("%H:%M:%S")
        elapsed = time.monotonic() - started_at
        message_id = send_cloud_message(device_id, payload)

        read_by = (datetime.now() + timedelta(seconds=edrx_seconds)
                   ).strftime("%H:%M:%S")
        attempt = (f"  {wall_clock}  T+{elapsed:7.1f}s  {ok('queued')}"
                   f"  collar reads by {read_by}")
        print(f"{attempt}  {dim(message_id)}" if message_id else attempt)

        # the next scheduled send takes priority over finishing the bar
        budget = edrx_seconds
        if index + 1 < len(offsets):
            until_next = started_at + offsets[index + 1] - time.monotonic()
            budget = min(budget, max(until_next, 0))

        show_paging_progress(budget, edrx_seconds)


def main():
    load_env_file()

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true", help="list devices and exit")
    parser.add_argument(
        "--device-id", type=int, help="device-id in hologram account to send to"
    )
    parser.add_argument("--data", default="spoof-ping",
                        help="command: spoof-ping, ping, lost, active, idle")
    parser.add_argument("--at", help="offsets in seconds, e.g. 300,900,1800")

    args = parser.parse_args()

    if args.list:
        list_devices()
        return

    if not args.device_id:
        parser.print_help()
        sys.exit(f"\n{bad('need --device-id')}, or {dim('--list')} to see them")

    run_send_schedule(args.device_id, args.data, args.at)


if __name__ == "__main__":
    main()
