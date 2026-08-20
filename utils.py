"""Shared helpers for start.py, setup.py and destroy.py.

Stdlib only, no pip install needed.
"""

import base64
import json
import os
import subprocess
import sys
import time
import urllib.request

TRACCAR = "http://localhost:8082"
EMQX = "http://localhost:8081/api/v4"
EMQX_AUTH = ("admin", "public")
EMQX_CONTAINER = "cloud-emqx1-1"
TAG = "FindMyCat"

COMPOSE_FILES = [
    "docker-compose.traccar.yml",
    "docker-compose.emqx.yml",
]
PROXY_COMPOSE_FILE = "docker-compose.ngnix-proxy.yml"

COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def paint(text, code):
    return f"\033[{code}m{text}\033[0m" if COLOR else str(text)


def head(text):
    return paint(text, "1;36")


def value(text):
    """Something the reader will copy out, e.g. a URL or an id."""
    return paint(text, "1;37")


def ok(text):
    return paint(text, "32")


def warn(text):
    return paint(text, "33")


def bad(text):
    return paint(text, "31")


def dim(text):
    return paint(text, "2")


def request(url, method="GET", body=None, auth=None, form=False, timeout=20):
    """Call a JSON API. Returns parsed JSON, or raw text if not JSON."""
    data = None
    headers = {}
    if body is not None:
        if form:
            data = body.encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
    if auth:
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode()
    return json.loads(text) if text.strip().startswith(("{", "[")) else text


def wait_for(label, url, auth=None, seconds=180, poll=3.0):
    """Poll until the service answers, spinning between attempts on a tty."""
    tty = sys.stdout.isatty()
    started = time.time()
    deadline = started + seconds
    next_poll = 0.0
    frame = 0

    if not tty:
        print(f"  {label:<9} ", end="", flush=True)

    while time.time() < deadline:
        if time.time() >= next_poll:
            try:
                request(url, auth=auth)
                took = dim(f"({time.time() - started:.0f}s)")
                line = f"  {label:<9} {ok('up')} {took}"
                print(f"\r\033[K{line}" if tty else f"{ok('up')} {took}")
                return True
            except Exception:
                next_poll = time.time() + poll

        if tty:
            print(f"\r  {label:<9} {SPINNER[frame % len(SPINNER)]}",
                  end="", flush=True)
            frame += 1
            time.sleep(0.08)
        else:
            time.sleep(poll)

    line = f"  {label:<9} {bad('TIMED OUT')}"
    print(f"\r\033[K{line}" if tty else bad("TIMED OUT"))
    return False


def compose(files, *args, check=True, quiet=False):
    """Run one docker compose command across every file.

    The files share a Compose project, so acting on them separately makes each
    report the other's container as an orphan. Never resolve that with
    --remove-orphans: the "orphan" is the other half of the stack.
    """
    flags = []
    for path in files:
        if os.path.exists(path):
            flags += ["-f", path]
    if not flags:
        return None
    cmd = ["docker", "compose"] + flags + list(args)
    sink = subprocess.DEVNULL if quiet else None
    return subprocess.run(cmd, check=check, stdout=sink, stderr=sink)


def containers(project="cloud"):
    result = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"label=com.docker.compose.project={project}",
         "--format", "{{.Names}}\t{{.Status}}"],
        capture_output=True, text=True, check=False,
    )
    return [line.split("\t") for line in result.stdout.strip().splitlines() if line]


def default_host():
    result = subprocess.run(["hostname", "-I"], capture_output=True, text=True,
                            check=False)
    return (result.stdout.split() or ["localhost"])[0]
