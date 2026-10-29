#!/usr/bin/env python3
"""Bring the whole FindMyCat cloud up: containers, Traccar, EMQX rules, the
MQTT certificate and the proxy. Safe to re-run; answers are saved in .env.

./start.py
./start.py --emqx-password 'something-long'   # also replaces admin/public

"""

import argparse
import getpass
import os
import re
import sys

from utils import (
    BROKER_CERT,
    COMPOSE_FILES,
    EMQX,
    EMQX_AUTH,
    EMQX_CONTAINER,
    ENV_FILE,
    TAG,
    TRACCAR,
    bad,
    compose,
    containers,
    default_host,
    dim,
    emqx_dashboard_password_is_default,
    emqx_status,
    head,
    ok,
    read_env,
    request,
    run_script,
    value,
    wait_for,
    warn,
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

    remember(answers)
    return answers


def totals(metrics, *keys):
    """Sum a metric across EMQX nodes."""
    return {key: sum(m.get(key, 0) for m in metrics or []) for key in keys}


def rule_engine_report(auth, indent="      "):
    try:
        rules = request(f"{EMQX}/rules", auth=auth)["data"]
    except Exception as exc:
        print(f"{indent}{bad('unreachable')} ({exc})")
        return

    ours = [r for r in rules if TAG in (r.get("description") or "")]
    if not ours:
        print(f"{indent}{warn('not configured')}")
        return

    for rule in ours:
        topics = ", ".join(t.strip('<>"') for t in rule.get("for", []))
        state = ok("enabled") if rule.get("enabled") else bad("DISABLED")
        print(f"{indent}{rule['id']}  {state}")
        print(f"{indent}  topic     {value(topics)}")

        counts = totals(rule.get("metrics"), "matched", "passed", "exception")
        exceptions = counts["exception"]
        print(
            f"{indent}  messages  matched {counts['matched'] or dim('0')}"
            f"  passed {counts['passed']}"
            f"  exception {bad(exceptions) if exceptions else '0'}"
        )

        for action in rule.get("actions", []):
            resource_id = action.get("params", {}).get("$resource", "")
            target = resource_id
            if resource_id:
                try:
                    resource = request(f"{EMQX}/resources/{resource_id}", auth=auth)
                    target = resource["data"]["config"].get("url", resource_id)
                except Exception:
                    pass
            hits = totals(action.get("metrics"), "success", "failed")
            failed = hits["failed"]
            print(f"{indent}  action    {action.get('name')} -> {target}")
            print(
                f"{indent}            success {ok(hits['success']) if hits['success'] else '0'}"
                f"  failed {bad(failed) if failed else '0'}"
            )


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

    print(f"\n{head('containers')}")
    for name, status in containers():
        print(f"  {name:<16}{ok(status) if status.startswith('Up') else bad(status)}")

    steps = []

    setup_ok = traccar_ok and emqx_ok and set_up(env, args.emqx_password)
    if not setup_ok:
        steps.append("Fix the error above, then re-run ./findmycat.py start")

    print(f"\n{head('traccar')}   ", end="")
    if setup_ok:
        print(value(f"https://{env['FMC_DOMAIN']}"))
    elif traccar_ok:
        print(dim("not published"))
    else:
        print(bad("not responding"))

    print(f"\n{head('emqx')}      {value(f'http://{args.host}:18083')}")
    print(f"    mqtt-sn   {value(f'udp://{args.host}:1885')}")
    print(f"    mqtt      {dim(f'tcp://{args.host}:1883')}")
    if os.path.exists(BROKER_CERT):
        print(f"    mqtt+tls  {value(f'ssl://{args.host}:8883')}")
    else:
        print(f"    mqtt+tls  {warn('no certificate')}")
    if emqx_ok:
        default = emqx_dashboard_password_is_default()
        if default is None:
            print(f"    dashboard {warn('unknown')} {dim('(18083 did not answer)')}")
        elif default:
            print(f"    dashboard {warn('default admin/public')}")
            steps.append(
                "Replace the default EMQX dashboard login:\n"
                "       ./findmycat.py start --emqx-password 'something-long'"
            )
        print("    rule engine")
        rule_engine_report(EMQX_AUTH)
    elif emqx_up:
        print(f"    api       {bad('credentials rejected')}")
        steps.append(
            "EMQX rejected the management API secret on 8081. Check it with\n"
            "       docker exec %s ./bin/emqx_ctl mgmt list\n"
            "       then export EMQX_APP_SECRET=..." % EMQX_CONTAINER
        )
    else:
        print(f"    {bad('not responding')}")

    if setup_ok:
        print(f"\n{head('test the pipeline')}")
        print(f"  ./findmycat.py verify --location-topic '{env['FMC_LOCATION_TOPIC']}' "
              f"--device-id {env['FMC_DEVICE_ID']}")

    if steps:
        print(f"\n{head('next steps')}")
        for number, step in enumerate(steps, 1):
            print(f"  {number}. {step}")

    sys.exit(0 if setup_ok else 1)


if __name__ == "__main__":
    main()
