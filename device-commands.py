#!/usr/bin/env python3
"""Send the app's commands to a collar.

  POST /devices/<id> {"command": "ping"}

The app calls this through the proxy, signed in with its Traccar session;
Traccar decides which devices that session may act on. The command goes out
through the Hologram API, whose key stays here rather than in the app, to the
collar's UDP listener. Each one is logged with device-status as a "command"
event: status "sent" with Hologram's message id, or "fail" if it never left.

Needs HOLOGRAM_API_KEY and HOLOGRAM_ORG_ID.
"""

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from traccar_access import traccar_unique_id

API_PORT = int(os.environ.get("DEVICE_COMMANDS_PORT", "8093"))
DEVICE_STATUS_INGEST_URL = os.environ.get(
    "DEVICE_STATUS_INGEST_URL", "http://device-status.instance:8092"
)

HOLOGRAM_API = "https://dashboard.hologram.io/api/1"
HOLOGRAM_API_KEY = os.environ.get("HOLOGRAM_API_KEY")
HOLOGRAM_ORG_ID = os.environ.get("HOLOGRAM_ORG_ID")

# The collar's UDP listener (UdpListener.c) and what dispatchCommand() accepts.
COLLAR_UDP_PORT = "12345"
COMMANDS = {"ping", "ping-wifi", "ping-gps", "spoof-ping", "lost", "active", "idle"}

# The proxy may or may not strip its location prefix, so accept both.
DEVICE_PATH = re.compile(r"^(?:/api/device-commands)?/devices/(\d+)$")


def hologram(path, body=None, query=None):
    url = f"{HOLOGRAM_API}{path}"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    credentials = base64.b64encode(f"apikey:{HOLOGRAM_API_KEY}".encode()).decode()
    headers = {"Authorization": f"Basic {credentials}"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def send_to_collar(unique_id, command):
    """Queues the command with Hologram and returns its message id.

    Hologram names each collar's SIM after the collar's uniqueId.
    """
    devices = hologram("/devices", query={"name": unique_id, "orgid": HOLOGRAM_ORG_ID}).get("data") or []
    if not devices:
        raise LookupError(f"no Hologram device named {unique_id}")

    queued = hologram("/devices/messages", body={
        "deviceids": [devices[0]["id"]],
        "protocol": "UDP",
        "port": COLLAR_UDP_PORT,
        "data": command,
    }).get("data") or []

    return queued[0].get("messageid") if queued and isinstance(queued[0], dict) else None


def log_command(unique_id, payload):
    """Recorded by device-status beside the collar's own reports."""
    req = urllib.request.Request(
        DEVICE_STATUS_INGEST_URL,
        data=json.dumps({"id": unique_id, "payload": {"kind": "command", **payload}}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5):
            pass
    except urllib.error.URLError as exc:
        print(f"{unique_id}: command not logged: {exc}", flush=True)


class CommandHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        match = DEVICE_PATH.match(urllib.parse.urlparse(self.path).path)
        if not match:
            self.reply(404, {"error": "not found"})
            return

        try:
            unique_id = traccar_unique_id(int(match.group(1)), self.headers)
        except (urllib.error.URLError, ValueError) as exc:
            print(f"traccar check failed: {exc}", flush=True)
            self.reply(502, {"error": "could not reach traccar"})
            return

        if unique_id is None:
            self.reply(401, {"error": "not signed in or no access to this device"})
            return

        try:
            command = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))["command"]
        except (ValueError, KeyError, TypeError):
            self.reply(400, {"error": 'expected {"command": "..."}'})
            return

        if command not in COMMANDS:
            self.reply(400, {"error": f"unknown command, expected one of {sorted(COMMANDS)}"})
            return

        try:
            message_id = send_to_collar(unique_id, command)
        except (urllib.error.URLError, LookupError, ValueError) as exc:
            print(f"{unique_id}: {command} not sent: {exc}", flush=True)
            log_command(unique_id, {"command": command, "status": "fail",
                                    "reason": "could not reach hologram"})
            self.reply(502, {"error": "could not send the command"})
            return

        log_command(unique_id, {"command": command, "status": "sent", "messageId": message_id})
        print(f"{unique_id}: {command} sent, hologram message {message_id}", flush=True)
        self.reply(202, {"messageId": message_id})

    def reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def main():
    for name in ("HOLOGRAM_API_KEY", "HOLOGRAM_ORG_ID"):
        if not os.environ.get(name):
            sys.exit(f"{name} is not set")

    print(f"device-commands listening on :{API_PORT}", flush=True)
    ThreadingHTTPServer(("", API_PORT), CommandHandler).serve_forever()


if __name__ == "__main__":
    main()
