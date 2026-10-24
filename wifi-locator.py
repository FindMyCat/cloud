#!/usr/bin/env python3
"""Resolve a collar's WiFi scan into a position and hand it to Traccar.

Over LTE the collar publishes the same scan frame it sends the home station
over LoRa, hex encoded, to the WiFi scan topic. The EMQX rule engine POSTs it
here as `id=<clientid>&scan=<hex>`; this looks the access points up with the
Google Geolocation API, the way the home station does, and posts the position
to Traccar's OsmAnd endpoint like the location rule.

Needs GOOGLE_GEOLOCATION_API_KEY, the home station's key.
"""

import json
import os
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

GEOLOCATE_URL = "https://www.googleapis.com/geolocation/v1/geolocate"
TRACCAR_OSMAND_URL = os.environ.get("TRACCAR_OSMAND_URL", "http://traccar.instance:5055")
LISTEN_PORT = int(os.environ.get("WIFI_LOCATOR_PORT", "8090"))
DEVICE_STATUS_INGEST_URL = os.environ.get(
    "DEVICE_STATUS_INGEST_URL", "http://device-status.instance:8092"
)

# Mirrors WiFi/wifi_scan.h on the collar and wifi_scan_frame.h on the station.
MESSAGE_TYPE = 0x01
HEADER_BYTES = 6  # type, count, uptime (u32 LE)
BYTES_PER_ACCESS_POINT = 7  # BSSID, RSSI (i8)
BATTERY_UNKNOWN = 0xFF


def decode_scan(frame):
    """Returns (access points, battery percent or None); raises ValueError."""
    if len(frame) < HEADER_BYTES or frame[0] != MESSAGE_TYPE:
        raise ValueError(f"not a scan frame ({len(frame)} bytes)")

    count = frame[1]
    body = HEADER_BYTES + count * BYTES_PER_ACCESS_POINT

    # The battery byte trails the access points; older collars omit it.
    if len(frame) not in (body, body + 1):
        raise ValueError(f"length mismatch: count {count}, {len(frame)} bytes")

    access_points = []
    for i in range(count):
        entry = frame[HEADER_BYTES + i * BYTES_PER_ACCESS_POINT:][:BYTES_PER_ACCESS_POINT]
        bssid = ":".join(f"{b:02x}" for b in entry[:6])
        (rssi,) = struct.unpack("b", entry[6:7])
        access_points.append({"macAddress": bssid, "signalStrength": rssi})

    battery = frame[body] if len(frame) > body else BATTERY_UNKNOWN
    return access_points, None if battery == BATTERY_UNKNOWN else battery


def geolocate(access_points, api_key):
    """Returns (lat, lon, accuracy in metres)."""
    body = json.dumps({"considerIp": False, "wifiAccessPoints": access_points}).encode()
    req = urllib.request.Request(
        f"{GEOLOCATE_URL}?key={api_key}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read())

    location = result["location"]
    return location["lat"], location["lng"], result["accuracy"]


def post_to_traccar(device_id, lat, lon, accuracy, battery):
    fields = {"id": device_id, "lat": lat, "lon": lon, "accuracy": accuracy}
    if battery is not None:
        fields["batt"] = battery

    req = urllib.request.Request(
        TRACCAR_OSMAND_URL,
        data=urllib.parse.urlencode(fields).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10):
        pass


def failure_reason(exc):
    """Short enough for the app's failed-ping alert."""
    if isinstance(exc, urllib.error.HTTPError) and exc.code == 404:
        return "wifi not known to google"
    if isinstance(exc, urllib.error.URLError):
        return "location service unreachable"
    return str(exc)


def report_ping(device_id, status, **fields):
    """The ping's outcome as a command event: "ok" once placed, else "fail"."""
    body = {
        "id": device_id,
        "payload": {"kind": "command", "command": "ping", "status": status, "method": "wifi", **fields},
    }
    req = urllib.request.Request(
        DEVICE_STATUS_INGEST_URL,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5):
            pass
    except urllib.error.URLError as exc:
        print(f"{device_id}: ping {status} not recorded: {exc}", flush=True)


class ScanHandler(BaseHTTPRequestHandler):
    api_key = None

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        form = urllib.parse.parse_qs(self.rfile.read(length).decode())
        device_id = form.get("id", [""])[0]
        scan_hex = form.get("scan", [""])[0]

        try:
            access_points, battery = decode_scan(bytes.fromhex(scan_hex))
            # Google needs at least two access points to place a scan.
            if len(access_points) < 2:
                raise ValueError(f"only {len(access_points)} access point(s)")

            lat, lon, accuracy = geolocate(access_points, self.api_key)
            post_to_traccar(device_id, lat, lon, accuracy, battery)
        except (ValueError, KeyError, urllib.error.URLError) as exc:
            print(f"{device_id}: scan dropped: {exc}", flush=True)
            report_ping(device_id, "fail", reason=failure_reason(exc))
            self.send_response(422)
            self.end_headers()
            return

        print(
            f"{device_id}: {len(access_points)} APs -> {lat:.6f},{lon:.6f} "
            f"+/-{accuracy:.0f} m, battery {battery}",
            flush=True,
        )
        report_ping(device_id, "ok", access_points=len(access_points), accuracy_m=round(accuracy))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


def main():
    api_key = os.environ.get("GOOGLE_GEOLOCATION_API_KEY")
    if not api_key:
        sys.exit("GOOGLE_GEOLOCATION_API_KEY is not set")

    ScanHandler.api_key = api_key
    print(f"wifi-locator listening on :{LISTEN_PORT}", flush=True)
    HTTPServer(("", LISTEN_PORT), ScanHandler).serve_forever()


if __name__ == "__main__":
    main()
