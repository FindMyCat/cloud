#!/usr/bin/env python3
"""Point the EMQX rule engine at Traccar, wifi-locator and device-status.

    ./setup-emqx.py --location-topic '/your-topic'
    ./setup-emqx.py --location-topic '/your-topic' --dashboard-password 'something-long'

Re-running replaces the FindMyCat rules rather than duplicating them.
"""

import argparse
import subprocess
import sys

from utils import EMQX, EMQX_AUTH, EMQX_CONTAINER, TAG, dim, emqx_status, head, ok, request


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


def set_dashboard_password(password):
    """Replaces the dashboard's default admin/public login."""
    subprocess.run(
        ["docker", "exec", EMQX_CONTAINER, "./bin/emqx_ctl", "admins", "passwd", "admin", password],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"  {'dashboard':<9} {ok('password set')}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--location-topic", required=True,
                        help="MQTT topic the collar publishes positions to")
    parser.add_argument("--status-topic", default="/status",
                        help="MQTT topic the collar publishes status reports to")
    parser.add_argument("--wifi-scan-topic", default="/wifi-scan",
                        help="MQTT topic the collar publishes raw WiFi scans to over LTE")
    parser.add_argument("--traccar-url", default="http://traccar.instance:5055",
                        help="where the rule engine POSTs positions")
    parser.add_argument("--wifi-locator-url", default="http://wifi-locator.instance:8090",
                        help="where the rule engine POSTs WiFi scans to be resolved")
    parser.add_argument("--device-status-url", default="http://device-status.instance:8092",
                        help="where the rule engine POSTs status reports to be stored")
    parser.add_argument("--dashboard-password",
                        help="replace the default admin/public dashboard login")
    parser.add_argument("--emqx-app-id", default=EMQX_AUTH[0],
                        help="EMQX management application id")
    parser.add_argument("--emqx-app-secret", default=EMQX_AUTH[1],
                        help="EMQX management application secret")
    args = parser.parse_args()

    auth = (args.emqx_app_id, args.emqx_app_secret)

    print(head("emqx rule engine"))
    if emqx_status(auth) != "ok":
        sys.exit("EMQX is not responding or rejected the management API secret")

    emqx_rules(args.location_topic, args.traccar_url, auth)
    emqx_wifi_scan_rule(args.wifi_scan_topic, args.wifi_locator_url, auth)
    emqx_device_status_rule(args.status_topic, args.device_status_url, auth)

    if args.dashboard_password:
        set_dashboard_password(args.dashboard_password)


if __name__ == "__main__":
    main()
