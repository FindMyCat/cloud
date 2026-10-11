#!/usr/bin/env python3
"""Store the collar's telemetry in Postgres and serve it to the app.

Every report on the status topic is an event of one kind: "command" (the
result of a ping or mode change), "network" (the eDRX grant) or "radio"
(which radio reaches the home station: BLE, LoRa or LTE). The EMQX rule engine POSTs each one to the ingest port as
{"id": "<clientid>", "payload": <the collar's JSON>}.

The app reads them through the proxy from the API port, signed in with its
Traccar session; Traccar decides which devices that session may see.
  GET /devices/<id>/state                    latest event of each kind
  GET /devices/<id>/events?after=&kind=      history, newest first

The ingest port stays on the docker network: only the API port is proxied.

Needs DATABASE_URL.
"""

import json
import os
import re
import sys
import threading
import time
from datetime import timezone
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer

import psycopg
from psycopg.types.json import Jsonb

DATABASE_URL = os.environ.get("DATABASE_URL")
TRACCAR_URL = os.environ.get("TRACCAR_URL", "http://traccar.instance:8082")
INGEST_PORT = int(os.environ.get("DEVICE_STATUS_INGEST_PORT", "8092"))
API_PORT = int(os.environ.get("DEVICE_STATUS_API_PORT", "8091"))

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

SCHEMA = """
CREATE TABLE IF NOT EXISTS device_event (
    id          bigserial   PRIMARY KEY,
    unique_id   text        NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    kind        text        NOT NULL,
    payload     jsonb       NOT NULL
);
CREATE INDEX IF NOT EXISTS device_event_unique_id_kind_id
    ON device_event (unique_id, kind, id DESC);
"""

# The proxy may or may not strip its location prefix, so accept both.
DEVICE_PATH = re.compile(r"^(?:/api/device-status)?/devices/(\d+)/(state|events)$")


def event_kind(payload):
    """Collars from before "kind" send the eDRX grant as command "NET"."""
    kind = payload.get("kind")
    if kind:
        return str(kind)
    if "command" not in payload:
        raise KeyError("kind")
    return "network" if payload["command"] == "NET" else "command"


def timestamp(value):
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_schema():
    """Postgres can start after this container, so wait for it."""
    for _ in range(30):
        try:
            with psycopg.connect(DATABASE_URL) as conn:
                conn.execute(SCHEMA)
            return
        except psycopg.OperationalError as exc:
            print(f"waiting for postgres: {exc}", flush=True)
            time.sleep(2)
    sys.exit("postgres never came up")


def traccar_unique_id(device_id, headers):
    """The device's uniqueId if this session may see it, else None.

    The app's own Cookie (or Basic auth) is replayed against Traccar, so the
    answer follows Traccar's permissions exactly.
    """
    forward = {name: headers[name] for name in ("Cookie", "Authorization") if headers.get(name)}
    if not forward:
        return None

    req = urllib.request.Request(
        f"{TRACCAR_URL}/api/devices?{urllib.parse.urlencode({'id': device_id})}",
        headers=forward,
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            devices = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code in (400, 401, 403, 404):
            return None
        raise

    return devices[0]["uniqueId"] if devices else None


class IngestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))

        try:
            body = json.loads(self.rfile.read(length))
            unique_id = str(body["id"])
            payload = body["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            kind = event_kind(payload)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            print(f"event dropped: {exc}", flush=True)
            self.send_response(422)
            self.end_headers()
            return

        try:
            with psycopg.connect(DATABASE_URL) as conn:
                conn.execute(
                    "INSERT INTO device_event (unique_id, kind, payload) VALUES (%s, %s, %s)",
                    (unique_id, kind, Jsonb(payload)),
                )
        except psycopg.Error as exc:
            print(f"{unique_id}: {kind} event not stored: {exc}", flush=True)
            self.send_response(503)
            self.end_headers()
            return

        print(f"{unique_id}: {kind} {json.dumps(payload)}", flush=True)
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


class ApiHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        match = DEVICE_PATH.match(url.path)
        if not match:
            self.reply(404, {"error": "not found"})
            return

        device_id = int(match.group(1))
        query = urllib.parse.parse_qs(url.query)

        try:
            unique_id = traccar_unique_id(device_id, self.headers)
        except (urllib.error.URLError, ValueError) as exc:
            print(f"traccar check failed: {exc}", flush=True)
            self.reply(502, {"error": "could not reach traccar"})
            return

        if unique_id is None:
            self.reply(401, {"error": "not signed in or no access to this device"})
            return

        try:
            if match.group(2) == "state":
                self.reply(200, self.state(unique_id))
            else:
                self.reply(200, self.events(unique_id, query))
        except ValueError:
            self.reply(400, {"error": "after and limit must be integers"})
        except psycopg.Error as exc:
            print(f"event query failed: {exc}", flush=True)
            self.reply(503, {"error": "database unavailable"})

    @staticmethod
    def state(unique_id):
        """Latest event of each kind, its fields flattened beside id and time."""
        with psycopg.connect(DATABASE_URL) as conn:
            rows = conn.execute(
                "SELECT DISTINCT ON (kind) kind, id, received_at, payload FROM device_event "
                "WHERE unique_id = %s ORDER BY kind, id DESC",
                (unique_id,),
            ).fetchall()

        return {
            kind: {**payload, "id": event_id, "receivedAt": timestamp(received_at)}
            for kind, event_id, received_at, payload in rows
        }

    @staticmethod
    def events(unique_id, query):
        after = int(query.get("after", ["0"])[0])
        limit = min(int(query.get("limit", [str(DEFAULT_LIMIT)])[0]), MAX_LIMIT)
        kind = query.get("kind", [None])[0]

        with psycopg.connect(DATABASE_URL) as conn:
            rows = conn.execute(
                "SELECT id, received_at, kind, payload FROM device_event "
                "WHERE unique_id = %s AND id > %s AND (%s::text IS NULL OR kind = %s) "
                "ORDER BY id DESC LIMIT %s",
                (unique_id, after, kind, kind, limit),
            ).fetchall()

        return [
            {"id": event_id, "receivedAt": timestamp(received_at), "kind": kind, "payload": payload}
            for event_id, received_at, kind, payload in rows
        ]

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
    if not DATABASE_URL:
        sys.exit("DATABASE_URL is not set")

    create_schema()

    ingest = HTTPServer(("", INGEST_PORT), IngestHandler)
    threading.Thread(target=ingest.serve_forever, daemon=True).start()

    print(f"device-status ingest on :{INGEST_PORT}, api on :{API_PORT}", flush=True)
    ThreadingHTTPServer(("", API_PORT), ApiHandler).serve_forever()


if __name__ == "__main__":
    main()
