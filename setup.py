#!/usr/bin/env python3
"""
    ./setup.py --location-topic '/your-topic' --traccar-email you@example.com \
               --traccar-password secret --device-id fmc-collar-01
"""

import argparse
import getpass
import os
import re
import subprocess
import sys
import urllib.error

from utils import (
    EMQX,
    EMQX_AUTH,
    ENV_FILE,
    TAG,
    TRACCAR,
    bad,
    default_host,
    dim,
    head,
    ok,
    read_env,
    request,
    value,
    wait_for,
    warn,
)

MQTT_SN_TOOLS_URL = "https://github.com/njh/mqtt-sn-tools.git"
MQTT_SN_TOOLS_DIR = "/opt/mqtt-sn-tools"


def check_user(email, password):
    """Confirm the Traccar account exists"""
    try:
        request(
            f"{TRACCAR}/api/session",
            method="POST",
            form=True,
            body=f"email={email}&password={password}",
        )
        print(f"  {'signed in':<9} {ok(email)}")
        return
    except urllib.error.HTTPError:
        print(f"  {'signed in':<9} {bad('failed')} for {email}")
        sys.exit(
            "\nIf this is a new install, open the Traccar UI and register the "
            "account first, then re-run:\n"
            "  ssh -L 8082:localhost:8082 root@<droplet>\n"
            "  open http://localhost:8082\n"
            "The first account you create becomes the administrator."
        )


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


def emqx_cleanup(kind, auth):
    for item in request(f"{EMQX}/{kind}", auth=auth)["data"]:
        if TAG in (item.get("description") or ""):
            print(f"  {dim('removed ' + item['id'])}")
            request(f"{EMQX}/{kind}/{item['id']}", method="DELETE", auth=auth)


def emqx_add_rule(sql, description, template, resource, auth, topic,
                  content_type="application/x-www-form-urlencoded"):
    rule = request(
        f"{EMQX}/rules",
        method="POST",
        auth=auth,
        body={
            "rawsql": sql,
            "description": description,
            "actions": [
                {
                    "name": "data_to_webserver",
                    "params": {
                        "$resource": resource,
                        "body": template,
                        "headers": {"content-type": content_type},
                    },
                }
            ],
        },
    )["data"]["id"]
    print(f"  {'rule':<9} {ok(rule)} {dim('on ' + topic)}")


def emqx_wifi_scan_rule(wifi_scan_topic, wifi_locator_url, auth):
    """Over LTE the collar publishes its raw WiFi scan; wifi-locator resolves it."""
    resource = request(
        f"{EMQX}/resources",
        method="POST",
        auth=auth,
        body={
            "type": "web_hook",
            "description": f"{TAG} wifi-locator",
            "config": {
                "url": wifi_locator_url,
                "method": "POST",
                "headers": {"content-type": "application/x-www-form-urlencoded"},
                "connect_timeout": "5s",
                "request_timeout": "15s",
                "pool_size": 2,
            },
        },
    )["data"]["id"]
    print(f"  {'resource':<9} {ok(resource)} {dim('-> ' + wifi_locator_url)}")

    emqx_add_rule(
        f'SELECT payload as scan, clientid FROM "{wifi_scan_topic}"',
        f"{TAG}: WiFi scan -> wifi-locator",
        "id=${clientid}&scan=${scan}",
        resource,
        auth,
        wifi_scan_topic,
    )


def emqx_rules(location_topic, traccar_url, auth):
    emqx_cleanup("rules", auth)
    emqx_cleanup("resources", auth)

    resource = request(
        f"{EMQX}/resources",
        method="POST",
        auth=auth,
        body={
            "type": "web_hook",
            "description": f"{TAG} Traccar OsmAnd endpoint",
            "config": {
                "url": traccar_url,
                "method": "POST",
                "headers": {"content-type": "application/x-www-form-urlencoded"},
                "connect_timeout": "5s",
                "request_timeout": "5s",
                "pool_size": 4,
            },
        },
    )["data"]["id"]
    print(f"  {'resource':<9} {ok(resource)} {dim('-> ' + traccar_url)}")

    sql = (
        "SELECT nth(1, split(payload.msg, ',')) as latitude, "
        "nth(2, split(payload.msg, ',')) as longitude, "
        "nth(3, split(payload.msg, ',')) as satellites, "
        "nth(4, split(payload.msg, ',')) as accuracy, "
        "nth(5, split(payload.msg, ',')) as batt_lvl, "
        f'clientid FROM "{location_topic}"'
    )
    # Traccar's OsmAnd protocol reads these as form fields on the POST body.
    template = (
        "id=${clientid}&lat=${latitude}&lon=${longitude}"
        "&accuracy=${accuracy}&batt=${batt_lvl}"
    )

    emqx_add_rule(
        sql,
        f"{TAG}: MQTT-SN position -> Traccar",
        template,
        resource,
        auth,
        location_topic,
    )


def emqx_device_status_rule(status_topic, device_status_url, auth):
    """Every status report goes to device-status, which keeps it in Postgres.

    The collar's JSON is passed through whole, so a new field needs no rule
    change; device-status only reads command and status from it.
    """
    resource = request(
        f"{EMQX}/resources",
        method="POST",
        auth=auth,
        body={
            "type": "web_hook",
            "description": f"{TAG} device-status",
            "config": {
                "url": device_status_url,
                "method": "POST",
                "headers": {"content-type": "application/json"},
                "connect_timeout": "5s",
                "request_timeout": "5s",
                "pool_size": 2,
            },
        },
    )["data"]["id"]
    print(f"  {'resource':<9} {ok(resource)} {dim('-> ' + device_status_url)}")

    emqx_add_rule(
        f'SELECT payload, clientid FROM "{status_topic}"',
        f"{TAG}: device status -> device-status",
        '{"id": "${clientid}", "payload": ${payload}}',
        resource,
        auth,
        status_topic,
        content_type="application/json",
    )


def ensure_mqtt_sn_tools():
    publisher = os.path.join(MQTT_SN_TOOLS_DIR, "mqtt-sn-pub")
    if os.path.exists(publisher):
        print(f"  {'client':<9} {dim(publisher)}")
        return publisher

    try:
        if os.path.isdir(os.path.join(MQTT_SN_TOOLS_DIR, ".git")):
            subprocess.run(["git", "pull", "-q"], cwd=MQTT_SN_TOOLS_DIR, check=True)
        else:
            subprocess.run(
                ["git", "clone", "-q", MQTT_SN_TOOLS_URL, MQTT_SN_TOOLS_DIR], check=True
            )
        subprocess.run(
            ["make", "-s"], cwd=MQTT_SN_TOOLS_DIR, check=True, stdout=subprocess.DEVNULL
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"  {'client':<9} {warn('unavailable')} {dim(str(exc))}")
        print(f"  {'':<9} {dim('needs git and build-essential')}")
        return None

    print(f"  {'client':<9} {ok('built')} {dim(publisher)}")
    return publisher


TOPIC = re.compile(r"^/[^+#]+$")

# Asked one at a time for whatever wasn't passed as a flag: (attribute,
# question, .env key that remembers the answer, first-run default, secret).
# Topic defaults match the collar's CONFIG_MQTT_SN_*_TOPIC, location as set in
# its local.conf.
QUESTIONS = [
    ("location_topic", "Location topic", "FMC_LOCATION_TOPIC", "/secret-topic", False),
    ("status_topic", "Status topic", "FMC_STATUS_TOPIC", "/status", False),
    ("wifi_scan_topic", "WiFi scan topic", "FMC_WIFI_SCAN_TOPIC", "/wifi-scan", False),
    ("traccar_email", "Traccar email", "FMC_TRACCAR_EMAIL", None, False),
    ("traccar_password", "Traccar password", "FMC_TRACCAR_PASSWORD", None, True),
    ("device_id", "Device id (the collar's MQTT client id)", "FMC_DEVICE_ID", None, False),
    ("device_name", "Device name", "FMC_DEVICE_NAME", "FindMyCat", False),
    ("device_emoji", "Device emoji", "FMC_DEVICE_EMOJI", "\U0001F408", False),
    ("domain", "Public domain for the app's API", "FMC_DOMAIN", None, False),
]


def remember(answers):
    """Writes answers into .env, replacing earlier ones and keeping other keys."""
    lines = []
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE) as handle:
            lines = [l for l in handle.read().splitlines() if l.split("=", 1)[0] not in answers]
    lines += [f"{key}={value}" for key, value in answers.items()]
    with open(ENV_FILE, "w") as handle:
        handle.write("\n".join(lines) + "\n")
    os.chmod(ENV_FILE, 0o600)


def ask(question, default, secret):
    shown = "saved" if secret else default
    prompt = f"{question} [{shown}]: " if default else f"{question}: "
    while True:
        answer = (getpass.getpass if secret else input)(prompt).strip() or default
        if answer:
            return answer


def ask_missing(args):
    saved = read_env()
    answers = {}

    for attr, question, key, default, secret in QUESTIONS:
        value = getattr(args, attr)
        default = saved.get(key, default)

        if value is None and sys.stdin.isatty():
            value = ask(question, default, secret)
            while attr.endswith("_topic") and not TOPIC.match(value):
                print("  must start with / and contain no MQTT wildcards")
                value = ask(question, default, secret)
        elif value is None:
            value = default

        if value is None:
            sys.exit(f"missing --{attr.replace('_', '-')}")
        if attr.endswith("_topic") and not TOPIC.match(value):
            sys.exit(f"--{attr.replace('_', '-')} must start with / and contain no MQTT wildcards")

        setattr(args, attr, value)
        answers[key] = value

    remember(answers)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--location-topic",
        help="MQTT topic the collar publishes positions to",
    )
    parser.add_argument(
        "--status-topic",
        help="MQTT topic the collar reports failed commands on",
    )
    parser.add_argument(
        "--traccar-email",
        help="existing Traccar login, used to register the device",
    )
    parser.add_argument("--traccar-password")
    parser.add_argument(
        "--device-id",
        help="Traccar uniqueId; must equal the collar's MQTT client id, "
        "since the rule passes clientid through as the device id",
    )
    parser.add_argument("--device-name")
    parser.add_argument(
        "--device-emoji",
        help="emoji shown for this device in the iOS app; stored as the "
        "Traccar device attribute 'emoji', which the app requires",
    )
    parser.add_argument(
        "--traccar-url",
        default="http://traccar.instance:5055",
        help="where the rule engine POSTs positions",
    )
    parser.add_argument(
        "--wifi-scan-topic",
        help="MQTT topic the collar publishes raw WiFi scans to over LTE",
    )
    parser.add_argument(
        "--device-status-url",
        default="http://device-status.instance:8092",
        help="where the rule engine POSTs status reports to be stored",
    )
    parser.add_argument(
        "--wifi-locator-url",
        default="http://wifi-locator.instance:8090",
        help="where the rule engine POSTs WiFi scans to be resolved",
    )
    parser.add_argument("--domain", help="the name the app reaches the API on, e.g. api.example.com")
    parser.add_argument(
        "--emqx-app-id", default=EMQX_AUTH[0], help="EMQX management application id"
    )
    parser.add_argument(
        "--emqx-app-secret",
        default=EMQX_AUTH[1],
        help="EMQX management application secret",
    )
    args = parser.parse_args()
    ask_missing(args)

    emqx_auth = (args.emqx_app_id, args.emqx_app_secret)

    print(head("traccar"))
    if not wait_for("api", f"{TRACCAR}/api/server"):
        sys.exit("Traccar is not responding, run ./start.py first")
    check_user(args.traccar_email, args.traccar_password)
    ensure_device(
        args.traccar_email,
        args.traccar_password,
        args.device_id,
        args.device_name,
        args.device_emoji,
    )

    print(f"\n{head('emqx rule engine')}")
    emqx_rules(args.location_topic, args.traccar_url, emqx_auth)
    emqx_wifi_scan_rule(args.wifi_scan_topic, args.wifi_locator_url, emqx_auth)
    emqx_device_status_rule(args.status_topic, args.device_status_url, emqx_auth)

    # Its own script so the certificate can be replaced on its own; without
    # --force it keeps an existing one, which devices have pinned.
    print()
    here = os.path.dirname(os.path.abspath(__file__))
    subprocess.run(
        [sys.executable, os.path.join(here, "setup-mqtt-tls.py"), "--domain", args.domain],
        cwd=here,
        check=True,
    )

    print(f"\n{head('mqtt-sn tools')}")
    publisher = ensure_mqtt_sn_tools()

    host = default_host()
    print(f"\n{head('point the collar at')}")
    print(f"  {'broker':<9} {value(f'udp://{host}:1885')}")
    print(f"  {'location':<9} {value(args.location_topic)}")
    print(f"  {'status':<9} {value(args.status_topic)}")
    print(
        f"  {'client id':<9} {value(args.device_id)} {dim('must match CONFIG_DEVICE_ID')}"
    )

    print(f"\n{head('test the pipeline')}")
    print(f"  curl -i https://{args.domain}/api/server")
    print(f"  curl -i https://{args.domain}/api/device-status/devices/1/state  "
          f"{dim('401 without a login')}")
    print(f"  ./findmycat.py verify --location-topic '{args.location_topic}' \\")
    print(f"    --device-id {args.device_id}")


if __name__ == "__main__":
    main()
