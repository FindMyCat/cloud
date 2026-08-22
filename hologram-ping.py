#!/usr/bin/env python3
"""Send a command to a collar using the Hologram API.

./hologram-ping.py --list
./hologram-ping.py --device-id 2373541
./hologram-ping.py --device-id 2373541 --data lost
./hologram-ping.py --device-id 2373541 --at 300,900,1800,3600

Commands go out through Hologram's REST API, which pushes them to the SIM as a
UDP datagram on port 12345.

"""

import argparse
import os
import sys
import time
from datetime import datetime

from utils import bad, dim, head, ok, request, value, warn

HOLOGRAM_API = "https://dashboard.hologram.io/api/1"
COLLAR_PORT = 12345
COLLAR_PROTOCOL = "UDP"
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
    """Post one cloud message, returning Hologram's message id."""
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

    accepted = response.get("data") or []
    if accepted and isinstance(accepted[0], dict):
        return accepted[0].get("messageid")
    return None


def run_send_schedule(device_id, payload, at):
    """Send on the requested offsets, one timed line per attempt."""
    offsets = sorted(float(o) for o in at.split(",") if o.strip()) if at else [0.0]

    print(
        head(
            f"\n{payload!r} to device {device_id} "
            f"on {COLLAR_PROTOCOL} port {COLLAR_PORT}"
        )
    )
    print(dim(f"offsets: {[int(offset) for offset in offsets]}s\n"))

    started_at = time.monotonic()

    for offset in offsets:
        seconds_to_wait = started_at + offset - time.monotonic()
        if seconds_to_wait > 0:
            time.sleep(seconds_to_wait)

        wall_clock = datetime.now().strftime("%H:%M:%S")
        elapsed = time.monotonic() - started_at
        message_id = send_cloud_message(device_id, payload)

        attempt = f"  {wall_clock}  T+{elapsed:7.1f}s  {ok('accepted')}"
        print(f"{attempt}  {dim(message_id)}" if message_id else attempt)


def main():
    load_env_file()

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true", help="list devices and exit")
    parser.add_argument(
        "--device-id", type=int, help="device-id in hologram account to send to"
    )
    parser.add_argument("--data", default="test-hello", help="payload")
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
