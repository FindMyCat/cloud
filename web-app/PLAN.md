# FindMyCat — Web App Port Plan

**Purpose:** A browser-based Progressive Web App (PWA) that surfaces GPS tracking from the same Traccar backend, accessible from any device with a browser and internet connection. Primary use case: your phone is gone, you borrow any device and open a URL.

**Scope:** GPS map view + real-time updates + lost mode. No BLE, no UWB — those require OS-level native APIs that browsers cannot provide.

---

## 1. Why a Web App Fits This Use Case

| Property | Native iOS | Native Android | Web App |
|---|---|---|---|
| Requires installation | App Store | Play Store | None — open URL |
| Works on borrowed device | No | No | Yes |
| Works on desktop/laptop | No | No | Yes |
| GPS tracking | ✓ | ✓ | ✓ (via Traccar) |
| Real-time updates | ✓ | ✓ | ✓ (WebSocket) |
| BLE Precise Find | ✓ | ✓ (RSSI) | ✗ |
| Installable to home screen | N/A | N/A | ✓ (PWA) |
| Single codebase for iOS+Android | No | No | Yes |
| Works offline (cached) | Partial | Partial | Partial |

The web app is not a replacement for the native apps — it is the **emergency fallback** and a **zero-install companion**. For the primary use case (find your cat from a borrowed laptop or unfamiliar Android phone), it is strictly superior to native apps.

---

## 2. Tech Stack

### Recommendation: Vanilla ES Modules + MapLibre GL JS + OpenStreetMap tiles

No build tooling. No framework. No API keys required for the map. Zero dependencies to install. Served as static files directly from your Traccar server.

**Why:**
- Opening a URL on a borrowed device should not require anything other than a modern browser.
- Static HTML/CSS/JS hosted on the same server as Traccar means same-origin requests — zero CORS configuration needed.
- MapLibre GL JS is the open-source MIT-licensed fork of Mapbox GL JS. Identical API, no token required for raster tile maps.
- OpenStreetMap raster tiles are free for personal/low-traffic use and require no account or API key.
- ES module `import` is supported in every browser released since 2018.
- There is no compilation step that could break in an unfamiliar environment.

**Dependencies (all via CDN `<script>` tags — no installation):**

| Library | Version | Purpose |
|---|---|---|
| MapLibre GL JS | 4.x | Interactive map (open-source, no key needed) |
| (nothing else) | | REST + WebSocket are native browser APIs |

**MapLibre vs Mapbox:**

| | Mapbox GL JS | MapLibre GL JS |
|---|---|---|
| License | Proprietary (v2+) | MIT |
| API key required | Yes (token) | No (for OSM raster tiles) |
| API compatibility | Reference | Drop-in replacement |
| Self-hostable | No | Yes |
| Tile sources | Mapbox CDN | OSM, self-hosted, any |

MapLibre was forked from Mapbox GL JS v1.15 by the open-source community specifically to remain free and self-hostable. It is the map library used in OpenMapTiles, Protomaps, and the Traccar web UI itself.

**What this rules out (and why):**
- React/Vue/Svelte: require a build step and Node.js. Unsuitable for the emergency scenario.
- Web Bluetooth: only works in Chromium-based desktop browsers, unsupported in Safari and all iOS browsers. Cannot replicate BLE Precise Find reliably.
- Web Push Notifications: require a notification server and service worker pairing. Out of scope for MVP.

---

## 3. Feature Parity Matrix

| Feature | iOS | Android | Web MVP | Web future |
|---|---|---|---|---|
| Login with email/password | ✓ | ✓ | ✓ | ✓ |
| Restore session (auto-login) | ✓ | ✓ | ✓ (cookie) | ✓ |
| Show devices on map | ✓ | ✓ | ✓ | ✓ |
| Real-time position via WebSocket | ✓ | ✓ | ✓ | ✓ |
| Device list (name, battery, last seen) | ✓ | ✓ | ✓ | ✓ |
| Emoji avatar | ✓ | ✓ | ✓ | ✓ |
| Center map on device | ✓ | ✓ | ✓ | ✓ |
| Lost mode toggle | ✓ | ✓ | ✓ * | ✓ |
| Play sound | ✓ | ✓ | ✓ * | ✓ |
| User's own location on map | ✓ | ✓ | ✓ (Geolocation API) | ✓ |
| Add device | ✓ | ✓ | — | ✓ |
| Edit device (name/emoji) | ✓ | ✓ | — | ✓ |
| Delete device | ✓ | ✓ | — | ✓ |
| BLE Precise Find | ✓ | ✓ | ✗ (no browser BLE) | ✗ |
| UWB Precise Find | ✓ | stub | ✗ | ✗ |
| PWA install to home screen | N/A | N/A | ✓ | ✓ |
| Offline cached view | — | — | ✓ (service worker) | ✓ |

\* Lost mode and sound require the Hologram API key. See section 6 (Security) for how to handle this.

---

## 4. Architecture

```
Browser
  │
  ├── index.html        ← single page, all screens rendered in JS
  ├── manifest.json     ← PWA install metadata
  ├── service-worker.js ← offline cache
  │
  └── src/
      ├── app.js        ← entry: routing, state, init
      ├── api/
      │   ├── traccar.js   ← REST calls + WebSocket (native fetch + WebSocket)
      │   └── hologram.js  ← cloud message API (or proxied)
      ├── screens/
      │   ├── login.js     ← login form, session check
      │   └── home.js      ← map + device drawer
      └── components/
          ├── map.js       ← Mapbox GL JS wrapper
          └── drawer.js    ← device list panel
```

### State management

No framework state management. A minimal hand-rolled observable store:

```javascript
// src/store.js
const state = {
  devices: [],
  positions: [],
  user: null,
};
const listeners = new Set();
export const subscribe = fn => listeners.add(fn);
export const getState = () => state;
export const setState = patch => {
  Object.assign(state, patch);
  listeners.forEach(fn => fn(state));
};
```

This is ~15 lines, no dependencies, and sufficient for the app's reactive needs.

### Routing

Hash-based: `#login` → `#home`. No server-side routing needed (works on any static file host).

```javascript
window.addEventListener('hashchange', () => render(location.hash));
```

---

## 5. API Layer

All three client apps share the same backend. The web app calls identical endpoints.

### Traccar REST

Base: `https://{TRACCAR_HOST}/api`

| Method | Endpoint | Body | Purpose |
|---|---|---|---|
| GET | `/session` | — | Check existing session (200 = logged in) |
| POST | `/session` | `email=...&password=...` (form-urlencoded) | Login → sets JSESSIONID cookie |
| DELETE | `/session` | — | Logout |
| GET | `/devices` | — | List all registered devices |
| GET | `/positions` | — | Current positions for all devices |

The browser manages the JSESSIONID cookie automatically once it is set. `fetch()` with `credentials: 'include'` sends it on every request.

```javascript
// src/api/traccar.js
const base = () => `https://${config.traccarHost}/api`;

export async function getSession() {
  const r = await fetch(`${base()}/session`, { credentials: 'include' });
  if (!r.ok) throw new Error('no session');
  return r.json();
}

export async function login(email, password) {
  const body = new URLSearchParams({ email, password });
  const r = await fetch(`${base()}/session`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  });
  if (!r.ok) throw new Error('login failed');
}

export async function fetchDevices() {
  const r = await fetch(`${base()}/devices`, { credentials: 'include' });
  return r.json();
}

export async function fetchPositions() {
  const r = await fetch(`${base()}/positions`, { credentials: 'include' });
  return r.json();
}
```

### MapLibre GL JS map initialisation

```javascript
// src/components/map.js
import maplibregl from 'https://cdn.jsdelivr.net/npm/maplibre-gl@4/dist/maplibre-gl.esm.min.js';

const cfg = window.FINDMYCAT_CONFIG;

export function initMap(containerId) {
  return new maplibregl.Map({
    container: containerId,
    style: {
      version: 8,
      sources: {
        osm: {
          type: 'raster',
          tiles: [cfg.tileUrl ?? 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
          tileSize: 256,
          attribution: cfg.tileAttribution ?? '© OpenStreetMap contributors',
        },
      },
      layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
    },
    center: [0, 20],
    zoom: 2,
  });
}
```

No API key. No account. `tileUrl` can be overridden in `config.js` to point to a self-hosted tile server for fully offline use.

### Traccar WebSocket

```javascript
// src/api/traccar.js (continued)
export function openSocket(onMessage) {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = cfg.traccarHost ?? location.host; // same-origin by default
  const ws = new WebSocket(`${protocol}//${host}/api/socket`);
  ws.onmessage = e => onMessage(JSON.parse(e.data));
  ws.onclose = () => setTimeout(() => openSocket(onMessage), 3000); // auto-reconnect
  return ws;
}
```

Payload shape (from iOS WebsocketPayloadWrapper):
```json
{ "devices": [...] }   // OR
{ "positions": [...] }
```
Same merge logic as iOS SharedData and Android DeviceRepository.

### Hologram API

```javascript
// src/api/hologram.js
export async function sendCommand(deviceName, command) {
  // Step 1: resolve Hologram device ID by tracker name
  const searchRes = await fetch(
    `https://dashboard.hologram.io/api/1/devices/?name=${encodeURIComponent(deviceName)}&orgid=${config.hologramOrgId}`,
    { headers: { Authorization: 'Basic ' + btoa(`apikey:${config.hologramApiKey}`) } }
  );
  const { data } = await searchRes.json();
  const deviceId = data[0].id;

  // Step 2: send the cloud message
  await fetch('https://dashboard.hologram.io/api/1/devices/messages', {
    method: 'POST',
    headers: {
      Authorization: 'Basic ' + btoa(`apikey:${config.hologramApiKey}`),
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ deviceids: [deviceId], data: command, port: '12345', protocol: 'UDP' }),
  });
}
```

**Note:** Hologram's API sets `Access-Control-Allow-Origin: *` on its endpoints, so browser cross-origin calls work without a proxy. Verified against their public docs.

---

## 6. Configuration and Security

### Configuration file (not committed)

With self-hosting on the Traccar server and MapLibre + OSM tiles, only the Hologram credentials are secrets. `traccarHost` can be omitted entirely when the web app is served same-origin — all `/api/` paths are relative.

```javascript
// config.js  ← listed in .gitignore, not committed
window.FINDMYCAT_CONFIG = {
  // traccarHost: omit when hosted on the same server as Traccar.
  // Set to 'traccar.example.com' only if hosted on a separate domain.
  traccarHost: '',

  // Required only for Lost Mode / Sound commands (Phase 2).
  hologramApiKey: 'your-key',
  hologramOrgId: 12345,

  // Map tile source. Default uses free OpenStreetMap tiles (no key needed).
  // Override with a self-hosted tile server URL for full offline capability.
  tileUrl: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  tileAttribution: '© <a href="https://openstreetmap.org">OpenStreetMap</a> contributors',
};
```

```javascript
// config.example.js  ← committed, user copies and fills in
window.FINDMYCAT_CONFIG = {
  traccarHost: '',          // leave blank if hosted on Traccar server
  hologramApiKey: '',       // from Hologram dashboard (Phase 2 only)
  hologramOrgId: 0,
  tileUrl: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  tileAttribution: '© <a href="https://openstreetmap.org">OpenStreetMap</a> contributors',
};
```

`index.html` loads `config.js` before `src/app.js`:
```html
<script src="config.js"></script>
<script type="module" src="src/app.js"></script>
```

### API base URL handling

```javascript
// src/api/traccar.js
const base = () => {
  const host = window.FINDMYCAT_CONFIG?.traccarHost;
  return host ? `https://${host}/api` : '/api'; // relative = same-origin
};
```

When `traccarHost` is blank, all requests go to `/api/...` — same server, same origin, no CORS headers needed anywhere.

### Security model

| Secret | Native apps | Web app (self-hosted) |
|---|---|---|
| Traccar host | BuildConfig / plist | Implicit (same server) |
| Hologram API key | BuildConfig / plist | `config.js` (not committed) |
| JSESSIONID | OS keychain/DataStore | HttpOnly cookie, same-origin |
| Map API key | Mapbox token in BuildConfig | None (OSM tiles, no key) |

Self-hosting on the Traccar server reduces the secret surface to just the Hologram API key. The JSESSIONID cookie is HttpOnly when set by Traccar, so JavaScript cannot read it — it is sent automatically by the browser on same-origin requests. This is more secure than the native apps, where the cookie value is read and stored in DataStore/Keychain.

Anyone with access to the web server filesystem can read `config.js`. For a personal tracker on a private server this is acceptable. If you want stricter isolation, move Hologram calls to a small server-side script (PHP, Python one-liner, nginx `proxy_pass`) so the Hologram key never leaves the server.

---

## 7. CORS and Deployment Options

The browser's same-origin policy blocks `fetch()` to a different domain unless the server sends CORS headers. Self-hosting solves this entirely.

---

### Option A — Serve from the Traccar server (recommended, fully self-hosted)

Traccar is a Java web server (Jetty). It serves its own web UI from a configurable directory and exposes `/api/` on the same port. Placing the web app files in a subdirectory makes all API calls same-origin.

**Setup:**

1. Find Traccar's web root. Default location after a standard Linux install:
   ```
   /opt/traccar/web/
   ```
   Or check `traccar.xml` for `web.path`.

2. Create a subdirectory for the web app:
   ```bash
   mkdir /opt/traccar/web/cat
   ```

3. Copy the web app files there:
   ```bash
   cp -r web-app/* /opt/traccar/web/cat/
   ```

4. Edit `config.js`: leave `traccarHost` blank (all `/api/` calls are relative).

5. Access at: `https://your-traccar-domain.com/cat/`

**Result:** Zero CORS headers needed. The JSESSIONID cookie is same-origin so it's sent automatically. The Traccar server restarts are not needed — the web directory is served as static files.

**Nginx alternative (if Traccar sits behind nginx):**

If your setup has nginx proxying to Traccar, add a location block that serves the web app files and lets `/api/` pass through to Traccar:

```nginx
server {
    server_name traccar.example.com;

    # Serve the web app at /cat/
    location /cat/ {
        alias /opt/traccar/web/cat/;
        try_files $uri $uri/ /cat/index.html;
    }

    # Proxy API + WebSocket to Traccar
    location /api/ {
        proxy_pass http://localhost:8082;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

---

### Option B — Separate server, configure Traccar CORS

If the web app must live on a different server (e.g. GitHub Pages, a CDN), configure Traccar to allow that origin.

In `traccar.xml`:
```xml
<entry key="web.origin">https://your-web-app-domain.com</entry>
```

Traccar sends `Access-Control-Allow-Origin` and `Access-Control-Allow-Credentials: true` on all `/api/` responses. Use `credentials: 'include'` in all `fetch()` calls to send the cookie cross-origin. Set `traccarHost` in `config.js`.

---

### Option C — Cloudflare Worker proxy (no server access needed)

A 20-line Cloudflare Worker proxies Traccar requests and appends CORS headers. Free tier handles thousands of requests/day. Useful if you cannot modify the Traccar server config.

---

### Self-hosted tile server (full offline capability)

The default config uses OpenStreetMap's public tile CDN — this still requires internet access. For a fully offline-capable installation on a local network:

1. Download a region's `.mbtiles` file from [OpenMapTiles](https://openmaptiles.org/downloads/) or [BBBike](https://extract.bbbike.org/).
2. Serve it with [tileserver-gl](https://github.com/maptiler/tileserver-gl) on the same machine as Traccar:
   ```bash
   docker run -p 8080:8080 -v /path/to/tiles:/data maptiler/tileserver-gl
   ```
3. Set `tileUrl` in `config.js` to `http://localhost:8080/styles/basic-preview/{z}/{x}/{y}.png`.

The web app, map tiles, and GPS data all serve from your own hardware. The only external call is to Hologram's API for lost mode commands.

---

## 8. PWA Capabilities

### manifest.json

```json
{
  "name": "FindMyCat",
  "short_name": "FindMyCat",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#1A1A1A",
  "theme_color": "#1A1A1A",
  "icons": [
    { "src": "icons/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "icons/icon-512.png", "sizes": "512x512", "type": "image/png" }
  ]
}
```

With this, Chrome and Safari will offer "Add to Home Screen" on mobile. The installed PWA launches full-screen with no browser chrome — indistinguishable from a native app to the user.

### service-worker.js (cache strategy)

```
Cache-first for: index.html, app CSS/JS, Mapbox GL JS, icons
Network-first for: all /api/ requests (real data)
Offline fallback: show cached map tiles + "Last known positions" banner
```

On a borrowed device: the service worker won't be pre-installed, so the first load requires network. Subsequent offline access works after the first visit.

### Geolocation API

Standard `navigator.geolocation.watchPosition()` shows the user's location as a blue dot on the map. Works in all browsers, prompts for permission, useful for "how far am I from my cat."

---

## 9. Screen Designs

### Login screen
```
┌─────────────────────────┐
│                         │
│          🐱             │
│                         │
│   Welcome, please       │
│   log in.               │
│                         │
│  ┌─────────────────┐    │
│  │ Email           │    │
│  └─────────────────┘    │
│  ┌─────────────────┐    │
│  │ Password        │    │
│  └─────────────────┘    │
│                         │
│  [      Log In      ]   │
│                         │
└─────────────────────────┘
```
On load: silently check existing session (`GET /session`). If 200, skip to home. If not, show form. This is the web equivalent of the session-check-on-launch pattern in iOS/Android.

### Home screen (portrait mobile)
```
┌─────────────────────────┐
│  🗺  Mapbox map          │
│     (fills screen)      │
│                         │
│     📍 Whiskers         │
│                         │
│                         │
├─────────────────────────┤ ← drag handle
│ Devices                 │
├─────────────────────────┤
│ 🐱 Whiskers             │
│    3m ago · 87%         │ [📍] [🔊]
├─────────────────────────┤
│ 🐶 Biscuit              │
│    12m ago · 62%        │ [📍] [🔊]
└─────────────────────────┘
```

The bottom panel is a CSS-animated sheet, draggable up to reveal the full device list. Same pattern as iOS FittedSheets and Android BottomSheetScaffold.

`[📍]` centres the map on that device. `[🔊]` sends the sound command via Hologram.

### No Precise Find screen

When the user taps a Precise Find equivalent on web, show a modal:
```
┌──────────────────────────────┐
│  Precise Find not available  │
│                              │
│  Bluetooth-based ranging     │
│  requires the native app.    │
│                              │
│  The map shows Whiskers'     │
│  last GPS position:          │
│  3 minutes ago               │
│                              │
│  [  Open iOS App  ]          │
│  [  Open Android App  ]      │
│  [  Close  ]                 │
└──────────────────────────────┘
```

---

## 10. File Structure

```
web-app/
├── PLAN.md                   ← this file
├── index.html                ← app shell (single page)
├── manifest.json             ← PWA manifest
├── service-worker.js         ← offline cache
├── config.example.js         ← template (committed)
├── config.js                 ← actual config (gitignored)
├── .gitignore
│
├── src/
│   ├── app.js                ← entry: routing, init, startup session check
│   ├── store.js              ← minimal observable state
│   ├── api/
│   │   ├── traccar.js        ← REST + WebSocket client
│   │   └── hologram.js       ← cloud message API
│   ├── screens/
│   │   ├── login.js          ← login form + session check
│   │   └── home.js           ← map + drawer orchestration
│   └── components/
│       ├── map.js            ← Mapbox GL JS map wrapper
│       └── drawer.js         ← device list bottom sheet
│
├── css/
│   └── app.css               ← dark theme, sheet animations
│
└── icons/
    ├── icon-192.png           ← PWA icon (generate from iOS asset)
    └── icon-512.png           ← PWA icon large
```

Total estimated file count: ~15 files. Total JS lines: ~600–800. No package.json. No node_modules.

---

## 11. Implementation Phases

### Phase 1 — Core GPS viewer (everything the emergency use case needs)

1. `index.html` — app shell with CDN imports for Mapbox GL JS
2. `src/api/traccar.js` — `getSession`, `login`, `fetchDevices`, `fetchPositions`, `openSocket`
3. `src/store.js` — 15-line observable state
4. `src/screens/login.js` — login form, session check on load, redirect to home
5. `src/screens/home.js` — orchestrates map + drawer, WebSocket merge logic
6. `src/components/map.js` — Mapbox map, emoji markers at device positions, user location dot
7. `src/components/drawer.js` — device list with battery%, last seen, centre-on-map button
8. `manifest.json` + `service-worker.js` — installable PWA, offline fallback
9. `css/app.css` — dark theme (#1A1A1A background), bottom sheet animation
10. `config.example.js` + `.gitignore`

**Deliverable**: Open URL → log in → see your cat on a map in real time. Works on any device.

### Phase 2 — Commands and device management

11. `src/api/hologram.js` — send cloud message (sound, lost mode)
12. Add Sound and Lost Mode buttons to drawer
13. Add/Edit/Delete device screens (simple modal forms calling Traccar REST)
14. Share location link (Web Share API / clipboard)

### Phase 3 — Polish

15. PWA push notifications (requires a notification server — evaluate separately)
16. Reverse geocoding for last known address (Mapbox Geocoding API)
17. "No precise find" deep-link modal pointing to native apps
18. Configurable map style (satellite vs. streets)
19. Multi-language support

---

## 12. Self-Hosting Dependency Map

What runs where in the recommended self-hosted setup:

```
Your server (e.g. VPS or home server)
├── Traccar (Java)                    ← GPS backend, device registry, REST + WS
│   └── /opt/traccar/web/cat/        ← web app static files served here
│       ├── index.html
│       ├── src/
│       └── config.js                ← gitignored, contains Hologram key only
│
└── tileserver-gl (optional Docker)  ← local map tiles (fully offline)

External (unavoidable)
└── dashboard.hologram.io            ← SIM cellular service + cloud messages
    (only called for Lost Mode / Sound — GPS tracking works without it)
```

In this setup:
- **GPS tracking**: 100% self-hosted. Traccar receives positions from the SIM tracker via cellular, your server stores them, the web app reads them.
- **Maps**: self-hosted (tileserver-gl) or free OSM CDN. No Mapbox.
- **Lost Mode / Sound**: calls Hologram's cloud API. This is the tracker's SIM provider — unavoidable without replacing the hardware.
- **Auth session**: lives in a same-origin HttpOnly cookie. No external identity provider.

---

## 13. Cloud Repo Integration (`github.com/FindMyCat/cloud`)

The existing cloud setup is Docker Compose with three services: Traccar, EMQX, and Nginx Proxy Manager (NPM). No changes are needed to EMQX. Two modifications are needed, plus one optional addition.

### What the cloud repo currently has

| Component | Image | Role | Exposed ports |
|---|---|---|---|
| Traccar | `traccar/traccar:latest` | GPS backend + REST API | 8082 (web), 5000–5150 (device protocols) |
| EMQX | `emqx/emqx` | MQTT broker (for tracker telemetry) | 1883, 1885, 18083 |
| Nginx Proxy Manager | `jc21/nginx-proxy-manager:latest` | TLS termination + reverse proxy | 80, 443, 81 (admin) |

Traccar's data persists at `/var/docker/traccar/data`. Its web UI (and our web app) would live at `/opt/traccar/web/` inside the container.

No CORS headers are configured anywhere. No Hologram proxy exists.

---

### Modification 1 — Serve the web app from Traccar's web root (no new container needed)

Traccar's Jetty web server already serves static files from `/opt/traccar/web/`. Mounting a subdirectory there makes the web app same-origin as the API — zero CORS config.

**Add one volume line to `docker-compose.traccar.yml`:**

```yaml
services:
  traccar:
    image: traccar/traccar:latest
    restart: unless-stopped
    volumes:
      - /var/docker/traccar/data:/opt/traccar/data
      - /var/docker/traccar/web/cat:/opt/traccar/web/cat   # ← add this line
    ports:
      - "8082:8082"
      - "5000-5150:5000-5150"
      - "5000-5150:5000-5150/udp"
```

Then deploy:
```bash
mkdir -p /var/docker/traccar/web/cat
cp -r /path/to/web-app/* /var/docker/traccar/web/cat/
# Edit config.js: leave traccarHost blank (same-origin)
docker compose -f docker-compose.traccar.yml up -d
```

The web app is now accessible at `https://your-traccar-domain.com/cat/`. All `/api/` calls are same-origin — no CORS headers needed anywhere.

---

### Modification 2 — Configure NPM to proxy the Traccar domain

This is done via the NPM admin UI at `http://your-server:81` (not code, since NPM stores routes in its own database volume).

In the NPM admin UI, create a **Proxy Host**:

| Field | Value |
|---|---|
| Domain Name | `traccar.yourdomain.com` (or whatever domain you use) |
| Forward Hostname/IP | `traccar` (Docker service name, resolves on the compose network) |
| Forward Port | `8082` |
| Websockets Support | **ON** (required for the `/api/socket` WebSocket connection) |
| SSL Certificate | Request a new Let's Encrypt cert → enable Force HTTPS |

WebSocket support must be on — the real-time update stream uses `wss://` and NPM must forward the `Upgrade` header.

---

### Modification 3 (optional) — Hologram proxy via NPM custom location

To avoid exposing the Hologram API key in `config.js`, add a custom location in the same NPM proxy host that forwards `/hologram/` to Hologram's API server-side.

In the NPM admin UI, on the Traccar proxy host, add a **Custom Location**:

| Field | Value |
|---|---|
| Location | `/hologram/` |
| Forward Hostname/IP | `dashboard.hologram.io` |
| Forward Port | `443` |

Then add custom Nginx config in the "Advanced" tab:
```nginx
location /hologram/ {
    rewrite ^/hologram/(.*)$ /api/1/$1 break;
    proxy_pass https://dashboard.hologram.io;
    proxy_ssl_server_name on;
    proxy_set_header Authorization "Basic YOUR_BASE64_ENCODED_APIKEY_HERE";
    proxy_set_header Host dashboard.hologram.io;
}
```

This moves the Hologram API key to the server side — `config.js` no longer needs `hologramApiKey`. The web app calls `/hologram/devices/` instead of `https://dashboard.hologram.io/api/1/devices/`, and the server adds the auth header. Entirely optional for Phase 2.

---

### Summary of cloud repo changes

| Change | Required? | Where |
|---|---|---|
| Add volume mount for `/opt/traccar/web/cat` in Traccar compose | Yes | `docker-compose.traccar.yml` |
| Configure NPM proxy host for Traccar domain with WS enabled | Yes | NPM admin UI (port 81) |
| Optional Hologram proxy via NPM custom location | No (Phase 2) | NPM admin UI "Advanced" tab |
| CORS configuration in `traccar.xml` | No (same-origin handles it) | — |
| New Docker service for web app | No (Traccar serves it) | — |

---

## 14. Open Questions Before Implementation

1. **Hologram API browser CORS**: The plan assumes `dashboard.hologram.io` sends `Access-Control-Allow-Origin: *` on its REST API. Verify before implementing Phase 2:
   ```bash
   curl -sI "https://dashboard.hologram.io/api/1/devices/" | grep -i access-control
   ```
   If Hologram blocks browser cross-origin calls, use the NPM custom location approach from Modification 3 in section 13 to proxy through the Traccar server instead.

2. **Traccar session lifetime**: Traccar's default session timeout is browser-session (expires on tab close). For the emergency use case a longer lifetime is better. Configure in `traccar.xml`:
   ```xml
   <entry key="server.sessionTimeout">604800</entry>  <!-- 7 days in seconds -->
   ```

3. **Tile source for offline use**: If the tracker is used in areas with poor internet (mountains, rural areas), consider downloading a regional `.mbtiles` file and running tileserver-gl. The OSM public CDN requires internet.

4. **HTTPS requirement**: Service workers (required for PWA install + offline) only work on HTTPS or localhost. The Traccar server should be behind a TLS terminator. Caddy makes this zero-config:
   ```
   traccar.example.com {
       reverse_proxy localhost:8082
   }
   ```
   Caddy auto-provisions a Let's Encrypt certificate.
