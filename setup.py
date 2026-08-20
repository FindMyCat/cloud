#!/usr/bin/env python3
"""
    ./setup.py --mqtt-topic '/your-topic' --traccar-email you@example.com \
               --traccar-password secret --device-id fmc-collar-01
"""

import argparse
import os
import re
import subprocess
import sys
import urllib.error

from utils import (
    EMQX,
    EMQX_AUTH,
    TAG,
    TRACCAR,
    bad,
    default_host,
    dim,
    head,
    ok,
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


def ensure_device(email, password, device_id, name):
    devices = request(f"{TRACCAR}/api/devices", auth=(email, password))
    if any(d["uniqueId"] == device_id for d in devices):
        print(f"  {'device':<9} {value(device_id)} {dim('already registered')}")
        return
    request(
        f"{TRACCAR}/api/devices",
        method="POST",
        body={"name": name, "uniqueId": device_id},
        auth=(email, password),
    )
    print(f"  {'device':<9} {value(device_id)} {ok('registered')}")


def emqx_cleanup(kind, auth):
    for item in request(f"{EMQX}/{kind}", auth=auth)["data"]:
        if TAG in (item.get("description") or ""):
            print(f"  {dim('removed ' + item['id'])}")
            request(f"{EMQX}/{kind}/{item['id']}", method="DELETE", auth=auth)


def emqx_rule(topic, traccar_url, auth):
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
        f'clientid FROM "{topic}"'
    )
    # Traccar's OsmAnd protocol reads these as form fields on the POST body.
    template = (
        "id=${clientid}&lat=${latitude}&lon=${longitude}"
        "&accuracy=${accuracy}&batt=${batt_lvl}"
    )

    rule = request(
        f"{EMQX}/rules",
        method="POST",
        auth=auth,
        body={
            "rawsql": sql,
            "description": f"{TAG}: MQTT-SN position -> Traccar",
            "actions": [
                {
                    "name": "data_to_webserver",
                    "params": {
                        "$resource": resource,
                        "body": template,
                        "headers": {
                            "content-type": "application/x-www-form-urlencoded"
                        },
                    },
                }
            ],
        },
    )["data"]["id"]
    print(f"  {'rule':<9} {ok(rule)} {dim('on ' + topic)}")


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mqtt-topic", required=True, help="MQTT topic the collar publishes to"
    )
    parser.add_argument(
        "--traccar-email",
        required=True,
        help="existing Traccar login, used to register the device",
    )
    parser.add_argument("--traccar-password", required=True)
    parser.add_argument(
        "--device-id",
        required=True,
        help="Traccar uniqueId; must equal the collar's MQTT client id, "
        "since the rule passes clientid through as the device id",
    )
    parser.add_argument("--device-name", default="FindMyCat")
    parser.add_argument(
        "--traccar-url",
        default="http://traccar.instance:5055",
        help="where the rule engine POSTs positions",
    )
    parser.add_argument(
        "--emqx-app-id", default=EMQX_AUTH[0], help="EMQX management application id"
    )
    parser.add_argument(
        "--emqx-app-secret",
        default=EMQX_AUTH[1],
        help="EMQX management application secret",
    )
    args = parser.parse_args()

    if not re.match(r"^/[^+#]+$", args.mqtt_topic):
        sys.exit("--mqtt-topic must start with / and contain no MQTT wildcards")

    emqx_auth = (args.emqx_app_id, args.emqx_app_secret)

    print(head("traccar"))
    if not wait_for("api", f"{TRACCAR}/api/server"):
        sys.exit("Traccar is not responding, run ./start.py first")
    check_user(args.traccar_email, args.traccar_password)
    ensure_device(
        args.traccar_email, args.traccar_password, args.device_id, args.device_name
    )

    print(f"\n{head('emqx rule engine')}")
    emqx_rule(args.mqtt_topic, args.traccar_url, emqx_auth)

    print(f"\n{head('mqtt-sn tools')}")
    publisher = ensure_mqtt_sn_tools()

    host = default_host()
    print(f"\n{head('point the collar at')}")
    print(f"  {'broker':<9} {value(f'udp://{host}:1885')}")
    print(f"  {'topic':<9} {value(args.mqtt_topic)}")
    print(
        f"  {'client id':<9} {value(args.device_id)} {dim('must match CONFIG_DEVICE_ID')}"
    )

    print(f"\n{head('test the pipeline')}")
    print(f"  ./findmycat.py verify --mqtt-topic '{args.mqtt_topic}' \\")
    print(f"    --device-id {args.device_id}")


if __name__ == "__main__":
    main()
