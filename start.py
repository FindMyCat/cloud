#!/usr/bin/env python3
"""Bring the whole FindMyCat cloud up: containers, Traccar, EMQX rules, the
MQTT certificate and the proxy. Safe to re-run; answers are saved in .env.

./start.py
./start.py --emqx-password 'something-long'   # also replaces admin/public

"""

import argparse
import base64
import getpass
import os
import re
import secrets
import sys

from utils import (
    BROKER_CERT,
    COMPOSE_FILES,
    EMQX_AUTH,
    TRACCAR,
    bad,
    compose,
    default_host,
    emqx_status,
    head,
    read_env,
    remember,
    run_script,
    wait_for,
)

TOPIC = re.compile(r"^/[^+#]+$")

# Asked one at a time: (question, .env key that remembers the answer,
# first-run default, secret). Topic defaults match the collar's
# CONFIG_MQTT_SN_*_TOPIC, location as set in its local.conf.
QUESTIONS = [
    ("Location topic", "FMC_LOCATION_TOPIC", "/secret-topic", False),
    ("Status topic", "FMC_STATUS_TOPIC", "/status", False),
    ("WiFi scan topic", "FMC_WIFI_SCAN_TOPIC", "/wifi-scan", False),
    ("Traccar email", "FMC_TRACCAR_EMAIL", None, False),
    ("Traccar password", "FMC_TRACCAR_PASSWORD", None, True),
    ("Device id (the collar's MQTT client id)", "FMC_DEVICE_ID", None, False),
    ("Device name", "FMC_DEVICE_NAME", "FindMyCat", False),
    ("Device emoji", "FMC_DEVICE_EMOJI", "\U0001F408", False),
    ("Public domain for the app's API", "FMC_DOMAIN", None, False),
]


def ask(question, default, secret):
    shown = "saved" if secret else default
    prompt = f"{question} [{shown}]: " if default else f"{question}: "
    while True:
        answer = (getpass.getpass if secret else input)(prompt).strip() or default
        if answer:
            return answer


def ask_questions():
    """Every answer, keyed by its .env name. Prompts on a terminal, with the
    saved answer as the default; otherwise takes .env as it is."""
    saved = read_env()
    answers = {}

    for question, key, default, secret in QUESTIONS:
        default = saved.get(key, default)
        answer = ask(question, default, secret) if sys.stdin.isatty() else default
        while key.endswith("_TOPIC") and answer and not TOPIC.match(answer):
            if not sys.stdin.isatty():
                sys.exit(f"{key} must start with / and contain no MQTT wildcards")
            print("  must start with / and contain no MQTT wildcards")
            answer = ask(question, default, secret)
        if not answer:
            sys.exit(f"{key} is not set in .env")
        answers[key] = answer

    # Not a question: FindMyCat-Web encrypts stored credentials with it, and a
    # new one makes them unreadable, so it is made once and then kept.
    answers["FINDMYCAT_ENCRYPTION_KEY"] = (
        saved.get("FINDMYCAT_ENCRYPTION_KEY") or base64.b64encode(secrets.token_bytes(32)).decode()
    )

    remember(answers)
    return answers


def set_up(env, emqx_password):
    """Runs each setup script in order, stopping at the first that fails."""
    traccar = ["--email", env["FMC_TRACCAR_EMAIL"], "--device-id", env["FMC_DEVICE_ID"],
               "--device-name", env["FMC_DEVICE_NAME"], "--device-emoji", env["FMC_DEVICE_EMOJI"]]
    emqx = ["--location-topic", env["FMC_LOCATION_TOPIC"], "--status-topic", env["FMC_STATUS_TOPIC"],
            "--wifi-scan-topic", env["FMC_WIFI_SCAN_TOPIC"]]
    if emqx_password:
        emqx += ["--dashboard-password", emqx_password]

    print()
    if not run_script("setup-traccar.py", *traccar,
                      env={**os.environ, "FMC_TRACCAR_PASSWORD": env["FMC_TRACCAR_PASSWORD"]}):
        return False
    # Picks up the Traccar token setup-traccar.py may have just written to .env;
    # does nothing when it was already there.
    compose(["docker-compose.findmycat-web.yml"], "up", "-d", quiet=True)
    print()
    if not run_script("setup-emqx.py", *emqx):
        return False
    # Only the first time: devices pin this certificate, so replacing it is a
    # deliberate ./findmycat.py setup-mqtt-tls --force.
    if not os.path.exists(BROKER_CERT):
        print()
        if not run_script("setup-mqtt-tls.py", "--domain", env["FMC_DOMAIN"]):
            return False
    print()
    return run_script("setup-proxy.py", "--domain", env["FMC_DOMAIN"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--emqx-password", help="replace the default admin/public dashboard login"
    )
    parser.add_argument(
        "--host",
        default=default_host(),
        help="address to print in URLs, e.g. a DNS name",
    )
    args = parser.parse_args()

    env = ask_questions()

    compose(COMPOSE_FILES, "up", "-d")

    print(head("Starting Services"))
    traccar_ok = wait_for("traccar", f"{TRACCAR}/api/server")

    state = {}

    def emqx_check():
        """Up means EMQX answered, even if it rejected our credentials."""
        state["value"] = emqx_status(EMQX_AUTH)
        if state["value"] == "down":
            raise RuntimeError("no response")

    emqx_up = wait_for("emqx", check=emqx_check)
    emqx_ok = emqx_up and state.get("value") == "ok"

    setup_ok = traccar_ok and emqx_ok and set_up(env, args.emqx_password)

    print()
    run_script("status.py", "--host", args.host)

    if setup_ok:
        print(f"\n{head('test the pipeline')}")
        print(f"  ./findmycat.py verify --location-topic '{env['FMC_LOCATION_TOPIC']}' "
              f"--device-id {env['FMC_DEVICE_ID']}")
    else:
        print(f"\n{bad('Fix the error above, then re-run ./findmycat.py start')}")

    sys.exit(0 if setup_ok else 1)


if __name__ == "__main__":
    main()
