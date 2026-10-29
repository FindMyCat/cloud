#!/usr/bin/env python3
"""Bring the whole FindMyCat cloud up: containers, Traccar, EMQX rules, the
MQTT certificate and the proxy. Safe to re-run; asks only for what .env lacks.

./start.py
./start.py --emqx-password 'something-long'   # also replaces admin/public

"""

import argparse
import os
import subprocess
import sys

from utils import (
    BROKER_CERT,
    COMPOSE_FILES,
    EMQX,
    EMQX_AUTH,
    EMQX_CONTAINER,
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


def set_emqx_password(password):
    subprocess.run(
        [
            "docker",
            "exec",
            EMQX_CONTAINER,
            "./bin/emqx_ctl",
            "admins",
            "passwd",
            "admin",
            password,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def totals(metrics, *keys):
    """Sum a metric across EMQX nodes."""
    return {key: sum(m.get(key, 0) for m in metrics or []) for key in keys}


def rule_engine_report(steps, auth, indent="      "):
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

    if emqx_up and args.emqx_password:
        set_emqx_password(args.emqx_password)

    print(f"\n{head('containers')}")
    for name, status in containers():
        print(f"  {name:<16}{ok(status) if status.startswith('Up') else bad(status)}")

    steps = []

    # Asks for anything .env doesn't have yet, then configures Traccar and EMQX.
    print()
    setup_ok = traccar_ok and emqx_ok and run_script("setup.py")
    if not setup_ok:
        steps.append("Fix the error above, then re-run ./findmycat.py start")

    print()
    domain = read_env().get("FMC_DOMAIN")
    proxy_ok = setup_ok and run_script("setup-proxy.py", "--domain", domain)

    print(f"\n{head('traccar')}   ", end="")
    if proxy_ok:
        print(value(f"https://{domain}"))
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
                "       ./start.py --emqx-password 'something-long'"
            )
        else:
            pass
        print("    rule engine")
        rule_engine_report(steps, EMQX_AUTH)
    elif emqx_up:
        print(f"    api       {bad('credentials rejected')}")
        steps.append(
            "EMQX rejected the management API secret on 8081. Check it with\n"
            "       docker exec %s ./bin/emqx_ctl mgmt list\n"
            "       then export EMQX_APP_SECRET=..." % EMQX_CONTAINER
        )
    else:
        print(f"    {bad('not responding')}")

    if steps:
        print(f"\n{head('next steps')}")
        for number, step in enumerate(steps, 1):
            print(f"  {number}. {step}")

    sys.exit(0 if (traccar_ok and emqx_ok) else 1)


if __name__ == "__main__":
    main()
