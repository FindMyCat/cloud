# FindMyCat Web App — Deployment Guide

## Where does the web app live?

**Bundled inside the cloud repo** (`github.com/FindMyCat/cloud`) as a `web-app/` subdirectory.

Why: the deployment step *is* a cloud repo operation — one volume line in `docker-compose.traccar.yml` and a copy command on the server. Keeping both in the same repo means one clone, one place to make changes, and a single deploy script. There's no build step, so the source files are the artifact.

If you ever intend to open-source just the web app (not the infra config), extract it to its own repo at that point.

---

## Two ways to run it

| Mode | What serves the app | Use for |
|---|---|---|
| **Production** | Traccar's Jetty (volume mount) behind Nginx Proxy Manager | The real deployment |
| **Local** | `docker-compose.webapp.yml` (nginx:alpine container) | Testing against a locally running Traccar stack |

`dev.sh` also exists for pure UI work (static file server, no `/api` or `/hologram` proxy — login and commands will not work).

---

# Production deployment

## Prerequisites

- The cloud stack is already running (Traccar reachable at `https://your-domain.com`)
- SSH access to the server
- NPM admin UI accessible at `http://your-server:81`
- Traccar is behind NPM with HTTPS and a Let's Encrypt cert

## Step 1 — Volume mount (already in the repo)

`docker-compose.traccar.yml` already mounts the host directory into Traccar's Jetty web root, so the app is served at `/cat/` by the same server that handles `/api/` — same-origin, no CORS config needed:

```yaml
- "/var/docker/traccar/web/cat:/opt/traccar/web/cat:ro"
```

If your running stack predates this line, apply it: `docker compose -f docker-compose.traccar.yml up -d`

## Step 2 — Deploy the files

From the repo root:

```bash
./deploy-webapp.sh user@your-server
```

This rsyncs `web-app/` to `/var/docker/traccar/web/cat/` (excluding `config.js`, docs, and local-dev files) and creates `config.js` from the template if it's missing.

## Step 3 — Configure config.js on the server

`config.js` is gitignored and lives only on the server. It is the only file that differs between environments.

```javascript
window.FINDMYCAT_CONFIG = {
  traccarHost: "",           // leave BLANK — served same-origin, no host needed
  hologramApiKey: "",        // leave blank if NPM injects the auth header (recommended, see Step 5)
  hologramOrgId: 12345,      // your Hologram organisation ID
  hologramPort: 12345,       // UDP port the tracker listens on for cloud messages
  tileUrl: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  tileAttribution: "&copy; <a href='https://openstreetmap.org'>OpenStreetMap</a> contributors",
};
```

`traccarHost` must be blank (empty string) when the web app is served from the same domain as Traccar. All `/api/` calls become relative — same-origin, cookie sent automatically.

## Step 4 — Enable WebSocket support in NPM

The real-time position stream uses WebSocket (`wss://`). NPM must forward the `Upgrade` header or the connection silently fails (devices load once but never update).

1. Open NPM admin: `http://your-server:81`
2. Find the Proxy Host for your Traccar domain
3. Edit → **Websockets Support: ON**
4. Save

## Step 5 — Hologram proxy (REQUIRED for Sound / Lost mode)

The web app calls Hologram via relative `/hologram/` paths (the browser cannot call `dashboard.hologram.io` directly — CORS). Without this proxy the Sound and Lost-mode buttons return 404.

On the Traccar proxy host in NPM, add custom Nginx config in the **Advanced** tab:

```nginx
location /hologram/ {
    rewrite ^/hologram/(.*)$ /api/1/$1 break;
    proxy_pass https://dashboard.hologram.io;
    proxy_ssl_server_name on;
    proxy_set_header Host dashboard.hologram.io;
    # Recommended: inject the key server-side so it never ships to browsers.
    # base64 of "apikey:YOUR_HOLOGRAM_API_KEY":
    proxy_set_header Authorization "Basic YOUR_BASE64_VALUE_HERE";
}
```

With the `Authorization` line present, leave `hologramApiKey` blank in `config.js` — the key stays off the client entirely. Without it, the browser sends the header itself using `hologramApiKey` from `config.js` (works, but anyone who can reach `/cat/config.js` can read the key).

## Step 6 — Verify

Open `https://your-domain.com/cat/` in a browser.

- Login screen appears; after login the map loads and devices appear as emoji markers
- Positions update in real time (DevTools → Network → WS tab shows an open `/api/socket` connection)
- Sound / Lost-mode buttons return success toasts (DevTools → Network: `/hologram/devices/...` returns 200)
- On mobile: "Add to Home Screen" installs the PWA

## Updating the web app

```bash
./deploy-webapp.sh user@your-server
```

No container restart needed — Jetty serves static files directly from disk. The service worker cache name (`findmycat-vN` in `service-worker.js`) is bumped on app changes so clients pick up new assets.

---

# Local deployment (docker compose)

Runs the app in an `nginx:alpine` container that serves `/cat/` and proxies `/api/` + `/api/socket` to the `traccar` container and `/hologram/` to Hologram (config in `web-app/nginx-local.conf`).

```bash
cp web-app/config.example.js web-app/config.js   # then fill in Hologram values
docker compose -f docker-compose.webapp.yml up -d
```

Open `http://localhost:8080/cat/`.

Assumptions:

- The Traccar stack is running and was started **from this repo directory** (the compose file joins the external network `cloud_emqx-bridge`; Docker Compose prefixes network names with the project name, which defaults to the directory name — clone the repo as anything other than `cloud` and you must adjust the `name:` under `networks:` in `docker-compose.webapp.yml`).
- Service workers require HTTPS **or localhost** — the PWA/offline features work at `http://localhost:8080` but not over plain HTTP from another machine.
- For Hologram commands, either set `hologramApiKey` in `config.js` (browser sends the auth header through the proxy) or hardcode the `Authorization` header in `nginx-local.conf` as the comment there shows.

---

# Operational notes

## Traccar session timeout

The repo's `traccar.xml` already sets a 7-day session (`server.sessionTimeout` = 604800) so an emergency login from a phone browser isn't lost when the tab closes. Note this applies to **all** Traccar clients, including the iOS app.

## Tile source

The map uses the public OSM tile CDN by default (`tileUrl` in `config.js`). For offline/rural use, point `tileUrl` at a self-hosted tile server.

---

# Feature status vs the native iOS app

Implemented and at parity: login with session restore, live map with emoji markers, real-time WebSocket updates, device drawer with battery % and relative last-seen (refreshed every 20 s like iOS), ping/lost mode via Hologram, logout (web-only — iOS has none), offline banner, loading/error states, installable PWA.

| Not implemented | Notes |
|---|---|
| Add / edit / delete device | iOS has full CRUD with an emoji picker. Web calls would be `POST/PUT/DELETE /api/devices`. |
| Reverse-geocoded address per device | iOS uses Apple CLGeocoder client-side. Web equivalent would need Nominatim or Traccar's `address` field. |
| BLE pairing / UWB Precise Find | Not possible in browsers (Web Bluetooth is Chromium-desktop only; no NearbyInteraction). |
| Push notifications | Requires a VAPID push server. |
| Satellite map toggle | Add a second raster source + toggle. |

The app fully covers the primary use case: **open URL → log in → see your cat's location on a map in real time, and trigger lost mode**.
