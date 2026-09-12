// Traccar REST + WebSocket client
// Config: window.FINDMYCAT_CONFIG = { traccarHost, ... }

import { fetchTimeout } from "../utils.js";

const host = window.FINDMYCAT_CONFIG?.traccarHost;
const API = host ? location.protocol + "//" + host + "/api" : "/api";

// --- REST ---

export async function getSession() {
  const res = await fetchTimeout(API + "/session", { credentials: "include" });
  if (!res.ok) throw new Error("No active session");
  return res.json();
}

export async function login(email, pw) {
  const res = await fetchTimeout(API + "/session", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ email, password: pw }),
  });
  if (!res.ok) throw new Error("Invalid credentials");
  return res.json();
}

export async function logout() {
  await fetchTimeout(API + "/session", { method: "DELETE", credentials: "include" });
}

export async function fetchDevices() {
  const res = await fetchTimeout(API + "/devices", { credentials: "include" });
  if (!res.ok) throw new Error("Failed to fetch devices");
  return res.json();
}

export async function fetchPositions() {
  const res = await fetchTimeout(API + "/positions", { credentials: "include" });
  if (!res.ok) throw new Error("Failed to fetch positions");
  return res.json();
}

// --- Device CRUD ---

export async function createDevice(device) {
  const res = await fetchTimeout(API + "/devices", {
    method: "POST", credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(device),
  })
  if (!res.ok) throw new Error("Failed to create device")
  return res.json()
}

export async function updateDevice(id, device) {
  const res = await fetchTimeout(API + "/devices/" + id, {
    method: "PUT", credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(device),
  })
  if (!res.ok) throw new Error("Failed to update device")
  return res.json()
}

export async function deleteDevice(id) {
  const res = await fetchTimeout(API + "/devices/" + id, { method: "DELETE", credentials: "include" })
  if (!res.ok) throw new Error("Failed to delete device")
}

// --- Geofences ---

export async function fetchGeofences() {
  const res = await fetchTimeout(API + "/geofences", { credentials: "include" })
  if (!res.ok) throw new Error("Failed to fetch geofences")
  return res.json()
}

export async function fetchGeofencesByDevice(deviceId) {
  const res = await fetchTimeout(API + "/geofences?deviceId=" + deviceId, { credentials: "include" })
  if (!res.ok) throw new Error("Failed to fetch device geofences")
  return res.json()
}

export async function createGeofence(geofence) {
  const res = await fetchTimeout(API + "/geofences", {
    method: "POST", credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(geofence),
  })
  if (!res.ok) throw new Error("Failed to create geofence")
  return res.json()
}

export async function updateGeofence(id, geofence) {
  const res = await fetchTimeout(API + "/geofences/" + id, {
    method: "PUT", credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(geofence),
  })
  if (!res.ok) throw new Error("Failed to update geofence")
  return res.json()
}

export async function deleteGeofence(id) {
  const res = await fetchTimeout(API + "/geofences/" + id, { method: "DELETE", credentials: "include" })
  if (!res.ok) throw new Error("Failed to delete geofence")
}

export async function addPermission(permission) {
  const res = await fetchTimeout(API + "/permissions", {
    method: "POST", credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(permission),
  })
  if (!res.ok) throw new Error("Failed to add permission")
}

export async function removePermission(permission) {
  const res = await fetchTimeout(API + "/permissions", {
    method: "DELETE", credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(permission),
  })
  if (!res.ok) throw new Error("Failed to remove permission")
}

// --- Position history ---

export async function fetchHistory(deviceId, from, to) {
  const params = new URLSearchParams({ deviceId: String(deviceId), from: from.toISOString(), to: to.toISOString() })
  const res = await fetchTimeout(API + "/positions?" + params, { credentials: "include" }, 30000)
  if (!res.ok) throw new Error("Failed to fetch history")
  return res.json()
}

// --- WebSocket ---

let unloading = false;
window.addEventListener("beforeunload", () => { unloading = true; });

/**
 * Open a WebSocket connection to the Traccar event stream.
 * Reconnects automatically after 3 s on close/error until close() is called.
 *
 * @param {(data: object) => void} onMessage — called with the parsed JSON payload
 * @returns {{ close: () => void }}
 */
export function openSocket(onMessage) {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const hostPart = window.FINDMYCAT_CONFIG?.traccarHost || location.host;
  const url = protocol + "//" + hostPart + "/api/socket";

  let ws = null;
  let timer = null;
  let closed = false;

  function connect() {
    ws = new WebSocket(url);

    ws.onmessage = (event) => {
      try {
        onMessage(JSON.parse(event.data));
      } catch {
        // ignore malformed frames
      }
    };

    // onclose always fires after onerror, so it is the single reconnect point —
    // scheduling in both would stack timers and open duplicate sockets.
    ws.onclose = () => {
      if (!closed && !unloading) {
        timer = setTimeout(connect, 3000);
      }
    };
    ws.onerror = () => ws.close();
  }

  connect();

  return {
    close() {
      closed = true;
      clearTimeout(timer);
      ws?.close();
    },
  };
}
