// Hologram cloud commands
// Config: window.FINDMYCAT_CONFIG = { hologramApiKey, hologramOrgId, hologramPort, ... }

import { fetchTimeout } from "../utils.js";

function authHeaders() {
  const { hologramApiKey } = window.FINDMYCAT_CONFIG ?? {};
  // Key may be blank when the /hologram/ proxy injects the Authorization header server-side
  return hologramApiKey
    ? { Authorization: "Basic " + btoa("apikey:" + hologramApiKey) }
    : {};
}

/**
 * Send a command to a device via Hologram.
 *
 * @param {Device} device — must have a .uniqueId property; Hologram device names
 *   are the Traccar uniqueId (same convention as the iOS app)
 * @param {string} command — raw command string to send
 */
export async function sendCommand(device, command) {
  const { hologramOrgId, hologramPort } = window.FINDMYCAT_CONFIG;
  const port = String(hologramPort ?? 12345);

  // 1. Look up the Hologram device id by name (= Traccar uniqueId)
  // Proxied through /hologram/ to avoid browser CORS block on dashboard.hologram.io
  const lookupUrl =
    "/hologram/devices/?name=" +
    encodeURIComponent(device.uniqueId) +
    "&orgid=" +
    hologramOrgId;

  const lookupRes = await fetchTimeout(lookupUrl, {
    headers: authHeaders(),
  }, 15000);

  if (!lookupRes.ok) {
    throw new Error("Hologram device lookup failed: " + lookupRes.status + " " + lookupRes.statusText);
  }

  const lookupJson = await lookupRes.json();

  if (!lookupJson.data || lookupJson.data.length === 0) {
    throw new Error("Hologram device not found for uniqueId: " + device.uniqueId);
  }

  const deviceHologramId = lookupJson.data[0].id;

  // 2. Send the command
  const sendRes = await fetchTimeout("/hologram/devices/messages", {
    method: "POST",
    headers: {
      ...authHeaders(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      deviceids: [deviceHologramId],
      data: command,
      port,
      protocol: "UDP",
    }),
  }, 15000);

  if (!sendRes.ok) {
    throw new Error("Hologram send command failed: " + sendRes.status + " " + sendRes.statusText);
  }

  return sendRes.json();
}
