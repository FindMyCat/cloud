#!/usr/bin/env python3
"""Quick health check of the FindMyCat cloud. Changes nothing.

./status.py
"""

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor

from utils import (
    BROKER_CERT,
    EMQX,
    EMQX_AUTH,
    EMQX_CONTAINER,
    TAG,
    bad,
    containers,
    default_host,
    dim,
    emqx_dashboard_password_is_default,
    emqx_status,
    head,
    ok,
    read_env,
    request,
    value,
    warn,
)


def totals(metrics, *keys):
    """Sum a metric across EMQX nodes."""
    return {key: sum(m.get(key, 0) for m in metrics or []) for key in keys}


def check_containers(found):
    print(head("containers"))
    if not found:
        print(f"  {bad('none running')} {dim('run ./findmycat.py start')}")
    for name, status in found:
        print(f"  {name:<16}{ok(status) if status.startswith('Up') else bad(status)}")
    return bool(found) and all(status.startswith("Up") for _, status in found)


def api_error(domain):
    """None if the API answers over HTTPS, else what went wrong."""
    if not domain:
        return "no domain in .env"
    try:
        request(f"https://{domain}/api/server", timeout=5)
        return None
    except Exception as exc:
        return str(exc)


def check_api(domain, error):
    print(f"\n{head('api')}")
    if not domain:
        print(f"  {warn(error)}")
    elif error:
        print(f"  {value('https://' + domain)} {bad('down')} {dim(error)}")
    else:
        print(f"  {value('https://' + domain)} {ok('up')}")
    return error is None


def check_emqx(host, dashboard_is_default, steps):
    print(f"\n{head('emqx')}      {value(f'http://{host}:18083')}")
    print(f"  mqtt-sn   {value(f'udp://{host}:1885')}")
    if os.path.exists(BROKER_CERT):
        print(f"  mqtt+tls  {value(f'ssl://{host}:8883')}")
    else:
        print(f"  mqtt+tls  {warn('no certificate')}")

    state = emqx_status(EMQX_AUTH)
    if state == "down":
        print(f"  {bad('not responding')}")
        return False
    if state == "auth":
        print(f"  api       {bad('credentials rejected')}")
        steps.append(
            "EMQX rejected the management API secret on 8081. Check it with\n"
            "       docker exec %s ./bin/emqx_ctl mgmt list\n"
            "       then export EMQX_APP_SECRET=..." % EMQX_CONTAINER
        )
        return False

    if dashboard_is_default:
        print(f"  dashboard {warn('default admin/public')}")
        steps.append(
            "Replace the default EMQX dashboard login:\n"
            "       ./findmycat.py start --emqx-password 'something-long'"
        )

    rules = [r for r in request(f"{EMQX}/rules", auth=EMQX_AUTH)["data"]
             if TAG in (r.get("description") or "")]
    if not rules:
        print(f"  rules     {warn('not configured')}")
        return False

    healthy = True
    for rule in rules:
        topic = ", ".join(t.strip('<>"') for t in rule.get("for", []))
        matched = totals(rule.get("metrics"), "matched")["matched"]
        failed = sum(totals(a.get("metrics"), "failed")["failed"] for a in rule.get("actions", []))
        enabled = rule.get("enabled")
        healthy = healthy and enabled
        print(f"  {topic:<14}{ok('enabled') if enabled else bad('DISABLED')}"
              f"  matched {matched}  failed {bad(failed) if failed else '0'}")
    return healthy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=default_host(),
                        help="address to print in URLs, e.g. a DNS name")
    args = parser.parse_args()

    domain = read_env().get("FMC_DOMAIN")

    # The slow checks run side by side; the droplet takes seconds for each.
    with ThreadPoolExecutor() as pool:
        found = pool.submit(containers)
        error = pool.submit(api_error, domain)
        dashboard_is_default = pool.submit(emqx_dashboard_password_is_default)

    steps = []
    healthy = check_containers(found.result())
    healthy = check_api(domain, error.result()) and healthy
    healthy = check_emqx(args.host, dashboard_is_default.result(), steps) and healthy

    if steps:
        print(f"\n{head('next steps')}")
        for number, step in enumerate(steps, 1):
            print(f"  {number}. {step}")

    sys.exit(0 if healthy else 1)


if __name__ == "__main__":
    main()
