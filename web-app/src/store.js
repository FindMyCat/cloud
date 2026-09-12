// Minimal reactive store
// State shape:
//   devices:        Device[]   — { id, name, uniqueId, status, attributes?: { emoji? }, lastUpdate? }
//   positions:      Position[] — { id, deviceId, latitude, longitude, fixTime, attributes: { batteryLevel, sat, motion } }
//   geofences:      Geofence[] — { id, name, area } — area is Traccar WKT e.g. "CIRCLE (lat lon, radius)"
//   geofenceDevices: { [geofenceId]: deviceId[] }

const state = {
  devices: [],
  positions: [],
  geofences: [],
  geofenceDevices: {},
};

const listeners = new Set();

/**
 * Subscribe to state changes.
 * The listener is called immediately with the current state, then on every setState.
 * @param {(state: object) => void} listener
 * @returns {() => void} unsubscribe function
 */
export function subscribe(listener) {
  listeners.add(listener);
  listener(state);
  return () => listeners.delete(listener);
}

/**
 * Return the current state object.
 * @returns {{ devices: Device[], positions: Position[], geofences: Geofence[], geofenceDevices: Object<number, number[]> }}
 */
export function getState() {
  return state;
}

/**
 * Merge patch into state and notify all listeners.
 * @param {Partial<{ devices: Device[], positions: Position[], geofences: Geofence[], geofenceDevices: Object<number, number[]> }>} patch
 */
export function setState(patch) {
  Object.assign(state, patch);
  for (const listener of listeners) {
    listener(state);
  }
}
