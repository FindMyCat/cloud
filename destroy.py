#!/usr/bin/env python3
"""Tear the FindMyCat cloud stack.

./destroy.py            # show what would be removed
./destroy.py --yes      # actually remove it

"""

import argparse
import os
import shutil

from utils import COMPOSE_FILES, compose, head, warn

PATHS = [
    "/var/docker/traccar/data",
    "/opt/traccar/logs",
    "tmp",
]


def remove(path, dry_run):
    if not os.path.exists(path):
        return
    print(("  would delete " if dry_run else "  deleting ") + path)
    if not dry_run:
        shutil.rmtree(path, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="actually delete")
    args = parser.parse_args()
    dry_run = not args.yes

    if dry_run:
        print(warn("DRY RUN, nothing will be removed. Pass --yes to proceed.\n"))

    print(head("containers and volumes"))
    if dry_run:
        print("  would run docker compose down -v")
    else:
        compose(COMPOSE_FILES, "down", "-v", check=False, quiet=True)
        print("  removed")

    print(f"\n{head('data')}")
    for path in PATHS:
        remove(path, dry_run)


if __name__ == "__main__":
    main()
