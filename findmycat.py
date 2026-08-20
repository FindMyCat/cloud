#!/usr/bin/env python3
"""FindMyCat cloud control.

    ./findmycat.py start [--emqx-password ...]
    ./findmycat.py setup --mqtt-topic ... --traccar-email ... --traccar-password ...
    ./findmycat.py destroy [--yes]

Each command is also runnable directly as start.py, setup.py or destroy.py;
this is just a single entry point. Arguments after the command are passed
through untouched, so `./findmycat.py setup --help` works as expected.
"""

import os
import subprocess
import sys

from utils import dim, head

VERSION = "3.0"

BANNER = f"""
⡆⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣰
⣿⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢠⣿
⣌⣿⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢠⣿⣫
⢮⣻⣷⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣾⣟⡵
⣦⣙⣿⣷⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣾⣿⣏⣴                               ▄       ▄▄
⣿⣿⣿⣿⣷⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣾⣿⣿⣿⣿      █████▀ █              ██ ██     ▄█         ▄▄████▄          ▄
⣿⣿⠏⢿⣿⣷⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣾⣿⡟⢸⣿⣿      █      ▄  ▄ ▄▄▄   ▄▄▄▄██ ███   ▄███ ▄   ▄▄▄█▀    ▀█  ▄▄▄  ▄██▄
⣿⣿⠀⠈⢿⣿⣷⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣾⣿⡟⠀⠸⣿⣿      ██▄▄▄  █  █▀▀▀██ █▀▀▀▀██ ████  █▀██ █▄  █▀██        █▀▀▀█▄ ██▀
⣿⣿⠀⠀⠈⢿⣿⣧⠀⠀⠀⠀⠀⠀⠀⢀⣾⣿⡟⠀⠀⠀⣿⣿      █      █  █   ██ █    ██ ██ ███▀ ██ ▀█ █▀ ██     ▄▄ ▄█▀▀██ ██
⣿⣿⠀⠀⠀⠈⢿⣿⣧⠀⠀⠀⠀⠀⢀⣾⣿⡟⠀⠀⠀⠀⣿⣿      █      █  █   ██ ▀█▄▄███ ██  ▀▀  ██  ███   ▀█▄▄▄██▀ █▄▄▄██ ██
⣿⣿⠀⠀⠀⠀⠈⢿⣿⣧⠀⠀⠀⢀⣾⣿⡟⠀⠀⠀⠀⠀⣿⣿                         ▀▀                ▄█       ▀       ▀
⣿⡇⠀⠀⠀⠀⠀⠈⢿⣿⣧⠀⠀⣾⣿⡟⠀⠀⠀⠀⠀⠀⣿⣿                                          ▀▀
⣿⡇⠀⠀⠀⠀⠀⠀⠈⢿⣿⣧⣼⣿⡟⠀⠀⠀⠀⠀⠀⠀⣿⣿                                    
⣿⣧⠀⠀⠀⠀⠀⠀⠀⠘⣿⣿⣿⡟⠀⠀⠀⠀⠀⠀⠀⠀⣿⣿
⣿⣿⠀⠀⠀⠀⠀⠀⠀⠀⠈⠉⠉⠀⠀⠀⠀⠀⠀⠀⠀⢠⣿⣿
⣟⣛⡇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢸⣛⣻
⠈⠉⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠉⠁

Welcome to FindMyCat Cloud Setup! v{VERSION}
"""

COMMANDS = {
    "start": ("start.py", "Starts the FindMyCat Cloud Stack"),
    "setup": ("setup.py", "Setup the pre-requisities for FindMyCat Cloud."),
    "verify": ("verify.py", "Publish a test position and check the pipeline."),
    "destroy": (
        "destroy.py",
        "Tear down the FindMyCat Cloud Stack. This is non-reversible.",
    ),
}

HERE = os.path.dirname(os.path.abspath(__file__))


def banner():
    print(BANNER)


def usage(exit_code):
    print(f"\n{head('commands')}")
    for name, (_, description) in COMMANDS.items():
        print(f"  {name:<9} {description}")
    print(f"\n{dim('Run a command with --help for its own options.')}")
    sys.exit(exit_code)


def main():
    banner()

    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        usage(0 if len(sys.argv) > 1 else 1)

    command = sys.argv[1]
    if command not in COMMANDS:
        print(f"unknown command: {command}")
        usage(1)

    script = os.path.join(HERE, COMMANDS[command][0])
    # The child writes straight to the fd, so anything still sitting in our
    # buffer would surface after its output when stdout is not a tty.
    sys.stdout.flush()
    sys.exit(subprocess.run([sys.executable, script] + sys.argv[2:]).returncode)


if __name__ == "__main__":
    main()
