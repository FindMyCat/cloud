#!/usr/bin/env python3
"""Show a container's logs.

./logs.py                      # list the containers
./logs.py web                  # last 100 lines of findmycat-web
./logs.py emqx -f              # follow cloud-emqx1-1
./logs.py traccar --since 10m  # extra arguments go to docker logs
"""

import os
import sys

from utils import bad, containers, head, ok


def main():
    names = [name for name, _ in containers()]
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        print(head("containers"))
        for name, status in containers():
            print(f"  {name:<16}{ok(status) if status.startswith('Up') else bad(status)}")
        return

    wanted, extra = sys.argv[1], sys.argv[2:]
    matches = [name for name in names if wanted in name]
    if len(matches) != 1:
        sys.exit(f"'{wanted}' matches {matches or 'no container'}; pick one of {names}")

    if not any(arg.startswith("--tail") or arg.startswith("--since") for arg in extra):
        extra = ["--tail", "100", *extra]
    os.execvp("docker", ["docker", "logs", *extra, matches[0]])


if __name__ == "__main__":
    main()