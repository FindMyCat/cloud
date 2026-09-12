import {
  fetchDevices, fetchPositions, fetchGeofences, fetchGeofencesByDevice,
  createDevice, updateDevice, deleteDevice,
  createGeofence, updateGeofence, deleteGeofence,
  addPermission, removePermission,
  fetchHistory,
  openSocket, logout,
} from "../api/traccar.js"
import { sendCommand } from "../api/hologram.js"
import { getState, setState, subscribe } from "../store.js"
import { initMap, destroyMap } from "../components/map.js"
import { initDrawer, updateDevices, updateZones, destroy as destroyDrawer } from "../components/drawer.js"
import { openDeviceModal } from "../components/device-modal.js"
import { openGeofenceModal } from "../components/geofence-modal.js"

let mapCtrl, socket, unsubscribe, onlineHandler, offlineHandler
let historyDevice = null

// ── Render ────────────────────────────────────────────────────────────────────

export async function render(container) {
  destroy()

  container.innerHTML = `
    <div class="screen screen-home is-active">
      <div id="map"></div>
      <div class="drawer" id="drawer"><div id="di"></div></div>
      <div class="offline-bar" id="ob">You are offline — showing last known positions</div>
      <div class="loading-overlay" id="lo"><span class="spinner spinner-lg"></span></div>
      <div class="history-bar" id="hbar" hidden>
        <div class="history-device-name" id="hdev"></div>
        <div class="history-presets">
          <button class="preset is-active" data-hours="1">1h</button>
          <button class="preset" data-hours="6">6h</button>
          <button class="preset" data-hours="24">24h</button>
          <button class="preset" data-hours="168">7d</button>
        </div>
        <button class="history-close" id="hclose">✕ Live</button>
      </div>
      <div class="placement-banner" id="pb" hidden>
        <span>Tap map to place zone centre</span>
        <button class="placement-cancel" id="pbc">Cancel</button>
      </div>
      <button class="map-style-btn" id="msb" title="Switch to satellite view">🛰️</button>
    </div>
  `

  try {
    mapCtrl = await initMap("map")
  } catch {
    setOverlayError("Map failed to load. Please refresh.", container)
    return
  }

  const drawerCallbacks = buildCallbacks()
  initDrawer("di", drawerCallbacks)

  let devices, positions, geofences
  try {
    ;[devices, positions, geofences] = await Promise.all([fetchDevices(), fetchPositions(), fetchGeofences()])
  } catch {
    setOverlayError("Could not load devices. Check your connection.", container)
    return
  }

  // Build geofence→devices map (N+1 is fine for small device counts)
  const geofenceDevices = {}
  await Promise.all(devices.map(async d => {
    try {
      const gfs = await fetchGeofencesByDevice(d.id)
      for (const gf of gfs) {
        if (!geofenceDevices[gf.id]) geofenceDevices[gf.id] = []
        geofenceDevices[gf.id].push(d.id)
      }
    } catch { /* non-fatal */ }
  }))

  document.getElementById("lo")?.remove()

  setState({ devices, positions, geofences, geofenceDevices })

  unsubscribe = subscribe(state => {
    mapCtrl.updateMarkers(state.devices, state.positions)
    mapCtrl.updateGeofences(state.geofences)
    updateDevices(state.devices, state.positions, drawerCallbacks)
    updateZones(state.geofences, state.geofenceDevices, state.devices, drawerCallbacks)
  })

  socket = openSocket(msg => {
    const cur = getState()

    if (msg.devices) {
      const m = [...cur.devices]
      for (const d of msg.devices) {
        const i = m.findIndex(x => x.id === d.id)
        // Preserve local state (attributes etc.) and merge server update
        if (i >= 0) m[i] = { ...m[i], ...d }
        else m.push(d)
      }
      setState({ devices: m })
    }

    if (msg.positions) {
      const m = [...cur.positions]
      for (const p of msg.positions) {
        const i = m.findIndex(x => x.deviceId === p.deviceId)
        if (i >= 0) m[i] = p; else m.push(p)
      }
      setState({ positions: m })
    }

    if (msg.events) {
      for (const event of msg.events) {
        if (event.type === 'geofenceEnter' || event.type === 'geofenceExit') {
          const device = cur.devices.find(d => d.id === event.deviceId)
          const geofence = cur.geofences.find(g => g.id === event.geofenceId)
          if (device && geofence) {
            const icon = event.type === 'geofenceEnter' ? '📍' : '✅'
            const verb = event.type === 'geofenceEnter' ? 'entered' : 'left'
            showToast(`${icon} ${device.attributes?.emoji || ''} ${device.name} ${verb} ${geofence.name}`, 'info')
          }
        }
      }
    }
  })

  mapCtrl.showUserLocation()

  // Satellite toggle
  const msb = document.getElementById('msb')
  msb.addEventListener('click', () => {
    const sat = mapCtrl.toggleMapStyle()
    msb.textContent = sat ? '🗺️' : '🛰️'
    msb.title = sat ? 'Switch to street map' : 'Switch to satellite view'
  })

  // History bar controls
  document.getElementById('hbar').addEventListener('click', e => {
    const preset = e.target.closest('.preset')
    if (preset && historyDevice) {
      document.querySelectorAll('.preset').forEach(b => b.classList.remove('is-active'))
      preset.classList.add('is-active')
      loadHistory(historyDevice, Number(preset.dataset.hours))
    }
  })
  document.getElementById('hclose').addEventListener('click', closeHistory)

  // Placement cancel
  document.getElementById('pbc').addEventListener('click', () => {
    mapCtrl.exitPlacementMode()
    document.getElementById('pb').hidden = true
  })

  // Offline banner
  const ob = document.getElementById("ob")
  onlineHandler = () => ob?.classList.remove("is-visible")
  offlineHandler = () => ob?.classList.add("is-visible")
  window.addEventListener("online", onlineHandler)
  window.addEventListener("offline", offlineHandler)
}

// ── Destroy ───────────────────────────────────────────────────────────────────

export function destroy() {
  historyDevice = null
  unsubscribe?.()
  socket?.close()
  destroyDrawer()
  destroyMap()
  if (onlineHandler) { window.removeEventListener("online", onlineHandler); onlineHandler = null }
  if (offlineHandler) { window.removeEventListener("offline", offlineHandler); offlineHandler = null }
  unsubscribe = null
  socket = null
  mapCtrl = null
}

// ── Drawer callbacks ──────────────────────────────────────────────────────────

function buildCallbacks() {
  return {
    onCenterMap: (dev, pos) => pos && mapCtrl.centerOn(pos.latitude, pos.longitude),

    onSound: dev =>
      sendCommand(dev, "ping").catch(err =>
        showToast("Sound command failed: " + (err?.message || "unknown error"))
      ),

    onLostMode: (dev, isLost) =>
      sendCommand(dev, isLost ? "lost" : "ping").catch(err =>
        showToast("Lost mode command failed: " + (err?.message || "unknown error"))
      ),

    onHistory: dev => openHistory(dev),

    onAddDevice: () =>
      openDeviceModal({
        onSave: async data => {
          const created = await createDevice(data)
          setState({ devices: [...getState().devices, created] })
        },
      }),

    onEditDevice: dev =>
      openDeviceModal({
        device: dev,
        onSave: async data => {
          const updated = await updateDevice(dev.id, data)
          setState({ devices: getState().devices.map(d => d.id === dev.id ? updated : d) })
        },
        onDelete: async () => {
          await deleteDevice(dev.id)
          setState({
            devices: getState().devices.filter(d => d.id !== dev.id),
            positions: getState().positions.filter(p => p.deviceId !== dev.id),
          })
        },
      }),

    onAddZone: () => {
      document.getElementById('pb').hidden = false
      document.getElementById('drawer').classList.remove('is-expanded')
      mapCtrl.enterPlacementMode(({ lat, lng }) => {
        document.getElementById('pb').hidden = true
        openZoneModal(null, lat, lng)
      })
    },

    onEditZone: gf => openZoneModal(gf, null, null),

    onLogout: async () => {
      try { await logout() } catch { /* best-effort */ }
      location.hash = "#login"
    },
  }
}

// ── Zone modal ────────────────────────────────────────────────────────────────

function openZoneModal(geofence, pendingLat, pendingLng) {
  const cur = getState()
  const linkedDeviceIds = geofence ? (cur.geofenceDevices[geofence.id] || []) : []

  openGeofenceModal({
    geofence,
    devices: cur.devices,
    linkedDeviceIds,
    pendingLat,
    pendingLng,
    onSave: async ({ name, area, selectedDeviceIds }) => {
      const state = getState()
      let saved
      if (geofence) {
        saved = await updateGeofence(geofence.id, { ...geofence, name, area })
      } else {
        saved = await createGeofence({ name, description: '', area, attributes: {} })
      }

      const currentIds = state.geofenceDevices[saved.id] || []
      // Update permissions in parallel, ignoring individual failures
      await Promise.all([
        ...selectedDeviceIds.filter(id => !currentIds.includes(id))
          .map(id => addPermission({ deviceId: id, geofenceId: saved.id }).catch(() => {})),
        ...currentIds.filter(id => !selectedDeviceIds.includes(id))
          .map(id => removePermission({ deviceId: id, geofenceId: saved.id }).catch(() => {})),
      ])

      setState({
        geofences: geofence
          ? state.geofences.map(g => g.id === saved.id ? saved : g)
          : [...state.geofences, saved],
        geofenceDevices: { ...state.geofenceDevices, [saved.id]: selectedDeviceIds },
      })
    },
    onDelete: async () => {
      const state = getState()
      await deleteGeofence(geofence.id)
      const linkedIds = state.geofenceDevices[geofence.id] || []
      await Promise.all(
        linkedIds.map(id => removePermission({ deviceId: id, geofenceId: geofence.id }).catch(() => {}))
      )
      const newGfd = { ...state.geofenceDevices }
      delete newGfd[geofence.id]
      setState({
        geofences: state.geofences.filter(g => g.id !== geofence.id),
        geofenceDevices: newGfd,
      })
    },
  })
}

// ── History ───────────────────────────────────────────────────────────────────

function openHistory(device) {
  historyDevice = device
  document.getElementById('hbar').hidden = false
  document.getElementById('hdev').textContent = (device.attributes?.emoji || '🐱') + ' ' + device.name + ' — History'
  document.querySelectorAll('.preset').forEach((b, i) => b.classList.toggle('is-active', i === 2)) // default 24h
  loadHistory(device, 24)
}

async function loadHistory(device, hours) {
  const to = new Date()
  const from = new Date(+to - hours * 3600 * 1000)
  try {
    const positions = await fetchHistory(device.id, from, to)
    mapCtrl.showTrack(positions)
    if (!positions.length) showToast('No history for this period')
  } catch (err) {
    showToast('Could not load history: ' + (err?.message || 'unknown error'))
  }
}

function closeHistory() {
  historyDevice = null
  document.getElementById('hbar').hidden = true
  mapCtrl.clearTrack()
  document.querySelectorAll('.preset').forEach((b, i) => b.classList.toggle('is-active', i === 2))
}

// ── Error / toast helpers ─────────────────────────────────────────────────────

function setOverlayError(message, container) {
  const lo = document.getElementById("lo")
  if (!lo) return
  lo.classList.add("is-error")
  lo.innerHTML =
    '<span class="error-icon">⚠️</span>' +
    '<p class="error-message">' + message + '</p>' +
    '<button class="btn-primary btn-retry">Try Again</button>'
  lo.querySelector(".btn-retry").addEventListener("click", () => render(container))
}

function showToast(message, type = 'error') {
  const screen = document.querySelector(".screen-home")
  if (!screen) return
  const toast = document.createElement("div")
  toast.className = `toast toast-${type}`
  toast.textContent = message
  screen.appendChild(toast)
  requestAnimationFrame(() => toast.classList.add("is-visible"))
  setTimeout(() => {
    toast.classList.remove("is-visible")
    setTimeout(() => toast.remove(), 300)
  }, 3500)
}
