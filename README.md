# FindMyCat Cloud

Docker-based cloud stack for [FindMyCat](https://www.findmycat.io) — runs the MQTT broker, GPS tracking server, reverse proxy, and web app on a single VPS.

## Stack

| Service | Compose file | Purpose |
|---|---|---|
| EMQX | `docker-compose.emqx.yml` | MQTT / MQTT-SN broker for device communication |
| Traccar | `docker-compose.traccar.yml` | GPS tracking server and REST + WebSocket API |
| Nginx Proxy Manager | `docker-compose.ngnix-proxy.yml` | TLS termination, Let's Encrypt certificates, reverse proxy |
| Web app | `docker-compose.webapp.yml` | Browser-based tracker UI (local dev only; production is served by Traccar) |

All services share the `cloud_emqx-bridge` Docker network.

---

## Prerequisites

- A Linux VPS (tested on Ubuntu 22.04+)
- Docker and Docker Compose installed
- A domain name pointing at the server
- An EMQX Enterprise licence (`tmp/emqx.lic`)
- A Hologram account with an API key and organisation ID (for device commands)

---

## Deployment

### 1. Clone and configure

```bash
git clone https://github.com/FindMyCat/cloud
cd cloud
```

Place your EMQX licence at `tmp/emqx.lic`.

### 2. Start Nginx Proxy Manager

```bash
docker compose -f docker-compose.ngnix-proxy.yml up -d
```

Open `http://your-server:81` and create a Proxy Host for your domain pointing at `traccar:8082`. Enable **Websockets Support** — required for real-time GPS updates.

### 3. Start EMQX

```bash
docker compose -f docker-compose.emqx.yml up -d
```

Dashboard: `http://your-server:18083` (default credentials: `admin` / `public` — change immediately).

Ports used by devices:
- `1883` — MQTT TCP
- `1885/udp` — MQTT-SN (UDP, used by FindMyCat trackers)

### 4. Start Traccar

```bash
docker compose -f docker-compose.traccar.yml up -d
```

Traccar reads `traccar.xml` from the repo root. The default config uses an embedded H2 database stored in `/var/docker/traccar/data`. Key settings already in place:

- `server.sessionTimeout` = 604800 (7-day session, keeps the web app and iOS app logged in)

Traccar's web UI is reachable at `https://your-domain.com` once NPM is configured.

### 5. Deploy the web app

See [web-app/DEPLOY.md](web-app/DEPLOY.md) for the full guide. Summary:

```bash
./deploy-webapp.sh user@your-server
```

This rsyncs the web app files to `/var/docker/traccar/web/cat/` — Traccar serves them at `https://your-domain.com/cat/`. Create `config.js` on the server from the example and fill in your Hologram credentials.

You also need a `/hologram/` custom location in NPM to proxy the Hologram API for Sound / Lost-mode — details in [web-app/DEPLOY.md](web-app/DEPLOY.md).

---

## Configuration files

| File | Purpose | Committed |
|---|---|---|
| `traccar.xml` | Traccar server config | Yes |
| `emqx_conf/emqx_sn.conf` | MQTT-SN plugin config | Yes |
| `tmp/emqx.lic` | EMQX Enterprise licence | **No** — add manually |
| `web-app/config.js` | Web app runtime config (API keys, tile URL) | **No** — create from `config.example.js` |

---

## Updating

Each service can be updated independently:

```bash
# Traccar
docker compose -f docker-compose.traccar.yml pull && docker compose -f docker-compose.traccar.yml up -d

# EMQX (pinned to 4.4.16 — do not upgrade without checking MQTT-SN compatibility)
docker compose -f docker-compose.emqx.yml up -d

# Web app (no container restart needed — Traccar serves files from disk)
./deploy-webapp.sh user@your-server
```

---

## Local development

```bash
cp web-app/config.example.js web-app/config.js  # fill in Hologram values
docker compose -f docker-compose.webapp.yml up -d
```

Open `http://localhost:8080/cat/`. This uses an nginx container that proxies `/api/` to the `traccar` container and `/hologram/` to `dashboard.hologram.io`. Requires the Traccar stack to be running locally.

For UI-only work (no login needed): `./web-app/dev.sh`
