#!/usr/bin/env python3
"""Publish a test position and report how far through the pipeline it got.

./verify.py --location-topic '/your-topic' --device-id your-device-id
"""

import argparse
import os
import subprocess
import sys
import time

from utils import EMQX, EMQX_AUTH, TAG, bad, default_host, dim, head, ok, request, warn

MQTT_SN_TOOLS_URL = "https://github.com/njh/mqtt-sn-tools.git"
MQTT_SN_TOOLS_DIR = "/opt/mqtt-sn-tools"
MQTT_SN_PUB = os.path.join(MQTT_SN_TOOLS_DIR, "mqtt-sn-pub")
SAMPLE = '{"msg":"0.0,0.0,8,21,85"}'


def ensure_mqtt_sn_tools():
    """Builds the MQTT-SN client this script publishes with, the first time."""
    if os.path.exists(MQTT_SN_PUB):
        return
    print(f"  {dim('building mqtt-sn-tools, needs git and build-essential')}")
    try:
        if not os.path.isdir(os.path.join(MQTT_SN_TOOLS_DIR, ".git")):
            subprocess.run(["git", "clone", "-q", MQTT_SN_TOOLS_URL, MQTT_SN_TOOLS_DIR], check=True)
        subprocess.run(["make", "-s"], cwd=MQTT_SN_TOOLS_DIR, check=True, stdout=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        sys.exit(f"could not build mqtt-sn-tools: {exc}")


def counters(auth, topic):
    """Rule and action totals for the FindMyCat rule on topic, across nodes."""
    try:
        rules = request(f"{EMQX}/rules", auth=auth)["data"]
    except Exception as exc:
        sys.exit(f"cannot reach the EMQX API: {exc}")

    for rule in rules:
        if TAG not in (rule.get("description") or ""):
            continue
        # Several FindMyCat rules exist, one per topic, so the counters have to
        # come from the one this publish actually feeds.
        if f'"{topic}"' not in (rule.get("rawsql") or ""):
            continue
        totals = {}
        for key in ("matched", "passed"):
            totals[key] = sum(m.get(key, 0) for m in rule.get("metrics") or [])
        for key in ("success", "failed"):
            totals[key] = sum(
                m.get(key, 0)
                for action in rule.get("actions", [])
                for m in action.get("metrics") or []
            )
        return totals

    sys.exit(
        f"no FindMyCat rule found on {topic}, run ./findmycat.py start first"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--location-topic", required=True)
    parser.add_argument(
        "--device-id",
        required=True,
        help="client id to publish as; must be registered in Traccar",
    )
    parser.add_argument("--host", default=default_host())
    parser.add_argument("--port", default="1885")
    parser.add_argument("--emqx-app-id", default=EMQX_AUTH[0])
    parser.add_argument("--emqx-app-secret", default=EMQX_AUTH[1])
    parser.add_argument(
        "--wait",
        type=float,
        default=3.0,
        help="seconds to wait for the webhook to complete",
    )
    args = parser.parse_args()

    ensure_mqtt_sn_tools()

    auth = (args.emqx_app_id, args.emqx_app_secret)
    before = counters(auth, args.location_topic)

    print(head("publish"))
    print(f"  {'broker':<9} udp://{args.host}:{args.port}")
    print(f"  {'topic':<9} {args.location_topic}")
    print(f"  {'client id':<9} {args.device_id}")

    result = subprocess.run(
        [
            MQTT_SN_PUB,
            "-h",
            args.host,
            "-p",
            args.port,
            "-i",
            args.device_id,
            "-t",
            args.location_topic,
            "-m",
            SAMPLE,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  {bad('publish failed')} {dim(result.stderr.strip())}")
        sys.exit(1)
    print(f"  {'sent':<9} {ok(SAMPLE)}")

    time.sleep(args.wait)
    after = counters(auth, args.location_topic)
    delta = {key: after[key] - before[key] for key in before}

    print(f"\n{head('pipeline')}")
    steps = [
        (
            "gateway",
            delta["matched"],
            "message reached the broker and matched the topic",
        ),
        ("rule sql", delta["passed"], "fields were extracted from the payload"),
        ("traccar", delta["success"], "Traccar accepted the position"),
    ]
    for label, count, description in steps:
        mark = ok("ok") if count else bad("--")
        print(f"  {label:<9} {mark}  {dim(description)}")

    if delta["failed"]:
        print(f"  {'':<9} {bad(str(delta['failed']) + ' webhook failure(s)')}")

    print()
    if delta["success"]:
        print(ok("  Position delivered end to end."))
        return
    if delta["matched"] and not delta["passed"]:
        print(warn("  Rule matched but extracted nothing. Check the payload shape."))
    elif delta["passed"] and not delta["success"]:
        print(warn("  Traccar rejected the POST. Is the device id registered?"))
    else:
        print(warn("  Nothing reached the broker. Check the topic, host and firewall."))
    sys.exit(1)


if __name__ == "__main__":
    main()
