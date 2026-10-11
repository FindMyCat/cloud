#!/usr/bin/env python3
"""Give EMQX a TLS listener on 8883 that embedded clients can verify.

    ./setup-mqtt-tls.py --domain api.findmycat.io
    ./setup-mqtt-tls.py --domain api.findmycat.io --force   # replace existing

"""

import argparse
import os
import subprocess
import sys

from utils import bad, compose, dim, head, ok, value, warn

CERT_DIR = "emqx_certs"
KEY_FILE = os.path.join(CERT_DIR, "broker-key.pem")
CERT_FILE = os.path.join(CERT_DIR, "broker-cert.pem")

DAYS = 3650


def openssl(*args):
    result = subprocess.run(
        ["openssl", *args], capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  {bad('openssl failed')}")
        print(result.stderr.strip())
        sys.exit(1)
    return result.stdout


def generate(domain):
    os.makedirs(CERT_DIR, exist_ok=True)

    openssl("ecparam", "-name", "prime256v1", "-genkey", "-noout",
            "-out", KEY_FILE)
    openssl(
        "req", "-new", "-x509",
        "-key", KEY_FILE,
        "-out", CERT_FILE,
        "-days", str(DAYS),
        "-subj", f"/CN={domain}",
        "-addext", f"subjectAltName=DNS:{domain}",
    )

    os.chmod(KEY_FILE, 0o600)
    os.chown(KEY_FILE, 1000, 1000)
    os.chown(CERT_FILE, 1000, 1000)


def describe():
    text = openssl("x509", "-in", CERT_FILE, "-noout",
                   "-subject", "-dates", "-ext", "subjectAltName")
    for line in text.strip().splitlines():
        print(f"    {dim(line.strip())}")


def as_c_string():
    """The certificate as a C string literal, for ca_certificate.h."""
    with open(CERT_FILE) as handle:
        lines = handle.read().strip().splitlines()

    return "\n".join(f'\t"{line}\\n"' for line in lines) + ";"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True,
                        help="name the devices connect to, e.g. api.findmycat.io")
    parser.add_argument("--force", action="store_true",
                        help="replace an existing certificate")
    parser.add_argument("--no-restart", action="store_true",
                        help="write the files but leave EMQX alone")
    args = parser.parse_args()

    print(head("MQTT TLS listener"))

    exists = os.path.exists(CERT_FILE)

    if exists and not args.force:
        print(f"  {warn('certificate already exists')} {value(CERT_FILE)}")
        print(f"  {dim('pass --force to replace it')}")
        print(f"\n  {warn('replacing it breaks every device that pinned the old one')}")
        describe()
    else:
        if exists:
            print(f"  {warn('replacing the existing certificate')}")
            print(f"  {warn('every device pinning the old one stops connecting')}")

        generate(args.domain)
        print(f"  {ok('generated')} {value(CERT_FILE)}")
        describe()

    if not args.no_restart:
        print(f"\n  {dim('restarting emqx to pick up the listener')}")
        compose(["docker-compose.emqx.yml"], "up", "-d")

    print(f"\n{head('firmware')}")
    print(f"  Paste into {value('embedded-software/packages/homestation-esp32/'
                               'app/src/modules/mqtt/ca_certificate.h')}:")
    print()
    print("static const unsigned char ca_certificate[] =")
    print(as_c_string())
    print()
    print(f"  {dim('then confirm the listener answers:')}")
    print(f"  {dim(f'openssl s_client -connect {args.domain}:8883 </dev/null')}")


if __name__ == "__main__":
    main()