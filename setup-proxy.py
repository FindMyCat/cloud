#!/usr/bin/env python3
"""Publish the app's API on a domain through Traefik, with a Let's Encrypt certificate.

    ./setup-proxy.py --domain api.findmycat.io

"""

import argparse
import json
import os
import socket
import sys

from utils import API_HEALTH_PATH, ROUTES_FILE, bad, default_host, dim, head, ok, request, value, wait_for

# Path prefix on the domain, and the container that serves it. FindMyCat-Web
# takes everything not listed: the web app, its API and live updates. Traccar
# stays private; FindMyCat-Web reaches it over the docker network.
ROUTES = {
    "/api/device-status": "http://device-status.instance:8091",
    "/api/device-commands": "http://device-commands.instance:8093",
}
WEB = "http://findmycat-web.instance:8080"


def dns_points_here(domain):
    """Let's Encrypt validates over HTTP, so a record pointing elsewhere fails
    and counts against its rate limit."""
    try:
        resolved = socket.gethostbyname(domain)
    except socket.gaierror:
        return None
    public_ip = request("https://api.ipify.org?format=json", timeout=10)["ip"]
    return resolved if resolved in (public_ip, default_host()) else None


def router(rule, service):
    return {
        "rule": rule,
        "service": service,
        "entryPoints": ["websecure"],
        "tls": {"certResolver": "letsencrypt"},
    }


def service(url):
    return {"loadBalancer": {"servers": [{"url": url}]}}


def traefik_config(domain):
    host = f"Host(`{domain}`)"

    routers = {"web": router(host, "web")}
    services = {"web": service(WEB)}

    for path, url in ROUTES.items():
        name = path.rsplit("/", 1)[-1]
        routers[name] = router(f"{host} && PathPrefix(`{path}`)", name)
        services[name] = service(url)

    # Plain HTTP on port 80 only redirects to HTTPS.
    routers["redirect"] = {
        "rule": host,
        "service": "web",
        "entryPoints": ["web"],
        "middlewares": ["https"],
    }
    middlewares = {"https": {"redirectScheme": {"scheme": "https", "permanent": True}}}

    return {"http": {"routers": routers, "services": services, "middlewares": middlewares}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True,
                        help="the name the app reaches the API on, e.g. api.findmycat.io")
    args = parser.parse_args()

    print(head("proxy"))

    resolved = dns_points_here(args.domain)
    if not resolved:
        print(f"  {'dns':<9} {bad(args.domain + ' does not point at this host')}")
        sys.exit(1)
    print(f"  {'dns':<9} {ok(resolved)}")

    # Traefik reloads this file on its own. JSON is valid YAML, so no PyYAML.
    os.makedirs(os.path.dirname(ROUTES_FILE), exist_ok=True)
    with open(ROUTES_FILE, "w") as handle:
        json.dump(traefik_config(args.domain), handle, indent=2)
    print(f"  {'routes':<9} {ok('written')} {dim(ROUTES_FILE)}")

    print(f"  {'/':<9} {value(WEB)}")
    for path, url in ROUTES.items():
        print(f"  {path:<9} {value(url)}")

    # The certificate is issued on the first request, which can take a minute.
    if not wait_for("https", f"https://{args.domain}{API_HEALTH_PATH}", seconds=180):
        print(f"  {dim('check docker logs traefik')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
