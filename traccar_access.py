"""Which collar a request from the app may act on, decided by Traccar.

Shared by the services behind the API host (device-status, device-commands),
which mount this file beside their own script.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

TRACCAR_URL = os.environ.get("TRACCAR_URL", "http://traccar.instance:8082")


def traccar_unique_id(device_id, headers):
    """The device's uniqueId if this session may see it, else None.

    The app's own Cookie (or Basic auth) is replayed against Traccar, so the
    answer follows Traccar's permissions exactly. Raises URLError when Traccar
    cannot be reached.
    """
    forward = {name: headers[name] for name in ("Cookie", "Authorization") if headers.get(name)}
    if not forward:
        return None

    req = urllib.request.Request(
        f"{TRACCAR_URL}/api/devices?{urllib.parse.urlencode({'id': device_id})}",
        headers=forward,
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            devices = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code in (400, 401, 403, 404):
            return None
        raise

    return devices[0]["uniqueId"] if devices else None
