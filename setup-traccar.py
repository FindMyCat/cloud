#!/usr/bin/env python3
"""Make sure Traccar has its admin account, the collar registered, and an API
token for FindMyCat-Web saved in .env.

    FMC_TRACCAR_PASSWORD=secret ./setup-traccar.py --email you@example.com \
        --device-id fmc-collar-01

On a fresh Traccar the account is created, and becomes the administrator.
"""

import argparse
import os
import sys
import urllib.error

from utils import TRACCAR, bad, dim, head, ok, read_env, remember, request, value, wait_for


def is_new_server():
    """Traccar reports newServer until its first account exists."""
    return request(f"{TRACCAR}/api/server").get("newServer", False)


def create_admin(email, password):
    """Traccar accepts this without a login only while it has no users."""
    request(
        f"{TRACCAR}/api/users",
        method="POST",
        body={"name": "Admin", "email": email, "password": password},
    )
    print(f"  {'account':<9} {ok('created')} {dim(email)}")


def check_login(email, password):
    try:
        request(
            f"{TRACCAR}/api/session",
            method="POST",
            form=True,
            body=f"email={email}&password={password}",
        )
    except urllib.error.HTTPError:
        print(f"  {'signed in':<9} {bad('failed')} for {email}")
        sys.exit("\nTraccar already has an account; FMC_TRACCAR_EMAIL and "
                 "FMC_TRACCAR_PASSWORD in .env must match it.")
    print(f"  {'signed in':<9} {ok(email)}")


def ensure_device(email, password, device_id, name, emoji):
    devices = request(f"{TRACCAR}/api/devices", auth=(email, password))
    existing = next((d for d in devices if d["uniqueId"] == device_id), None)
    if existing:
        if (existing.get("attributes") or {}).get("emoji"):
            print(f"  {'device':<9} {value(device_id)} {dim('already registered')}")
            return
        attributes = dict(existing.get("attributes") or {}, emoji=emoji)
        request(
            f"{TRACCAR}/api/devices/{existing['id']}",
            method="PUT",
            body=dict(existing, attributes=attributes),
            auth=(email, password),
        )
        print(f"  {'device':<9} {value(device_id)} {ok('emoji added')} {value(emoji)}")
        return
    request(
        f"{TRACCAR}/api/devices",
        method="POST",
        body={
            "name": name,
            "uniqueId": device_id,
            "attributes": {"emoji": emoji},
        },
        auth=(email, password),
    )
    print(f"  {'device':<9} {value(device_id)} {ok('registered')} {value(emoji)}")


def ensure_api_token(email, password):
    """FindMyCat-Web reads Traccar with this token. Made once and kept in .env;
    with no expiration given, Traccar issues one that does not expire."""
    if read_env().get("FMC_TRACCAR_TOKEN"):
        print(f"  {'token':<9} {dim('already in .env')}")
        return
    token = request(f"{TRACCAR}/api/session/token", method="POST", form=True, body="",
                    auth=(email, password))
    remember({"FMC_TRACCAR_TOKEN": token.strip()})
    print(f"  {'token':<9} {ok('created')} {dim('saved to .env')}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="Traccar admin login")
    parser.add_argument(
        "--device-id",
        required=True,
        help="Traccar uniqueId; must equal the collar's MQTT client id, "
        "since the rule passes clientid through as the device id",
    )
    parser.add_argument("--device-name", default="FindMyCat")
    parser.add_argument(
        "--device-emoji",
        default="\U0001F408",
        help="emoji shown for this device in the iOS app; stored as the "
        "Traccar device attribute 'emoji', which the app requires",
    )
    args = parser.parse_args()

    # From the environment, so it never shows up in the process list.
    password = os.environ.get("FMC_TRACCAR_PASSWORD")
    if not password:
        sys.exit("set FMC_TRACCAR_PASSWORD")

    print(head("traccar"))
    if not wait_for("api", f"{TRACCAR}/api/server"):
        sys.exit("Traccar is not responding, run ./start.py first")

    if is_new_server():
        create_admin(args.email, password)
    check_login(args.email, password)
    ensure_device(args.email, password, args.device_id, args.device_name, args.device_emoji)
    ensure_api_token(args.email, password)


if __name__ == "__main__":
    main()
