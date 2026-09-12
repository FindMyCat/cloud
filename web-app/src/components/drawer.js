import { reverseGeocode } from '../api/geocode.js'

// ── Module state ──────────────────────────────────────────────────────────────

let lastDevices = [], lastPositions = [], lastGeofences = [], lastGeofenceDevices = {}, lastCallbacks = {}
let lostModeSet = new Set()
let refreshTimer = null
// geocode cache: Map<deviceId, address string | null>
const addressCache = new Map()
// geocode in-flight tracking: Map<deviceId, 'lat,lng key'>
const geocodedKey = new Map()

// ── Helpers ───────────────────────────────────────────────────────────────────

function esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

function relTime(iso) {
  if (!iso) return 'Never'
  const ms = new Date(iso).getTime()
  if (isNaN(ms)) return 'Never'
  const elapsed = (Date.now() - ms) / 1000
  if (elapsed < 60) return 'Just now'
  if (elapsed < 3600) return Math.floor(elapsed / 60) + 'm ago'
  if (elapsed < 86400) return Math.floor(elapsed / 3600) + 'h ago'
  return Math.floor(elapsed / 86400) + 'd ago'
}

function round(v) { return Math.round(v * 1000) / 1000 }

function scheduleGeocode(device, pos) {
  if (!pos) return
  const key = round(pos.latitude) + ',' + round(pos.longitude)
  if (geocodedKey.get(device.id) === key) return
  geocodedKey.set(device.id, key)

  reverseGeocode(pos.latitude, pos.longitude).then(addr => {
    addressCache.set(device.id, addr)
    if (!addr) return
    const el = document.querySelector(`.device-item[data-id="${device.id}"] .device-address`)
    if (el) { el.textContent = addr; el.hidden = false }
  })
}

// ── Init ──────────────────────────────────────────────────────────────────────

export function initDrawer(containerId, callbacks) {
  destroy()
  lostModeSet = new Set()

  const container = document.getElementById(containerId)
  container.innerHTML = `
    <div class="drawer-handle" id="dh"></div>
    <div class="drawer-tabs" id="dtabs">
      <button class="drawer-tab is-active" data-tab="devices">Devices</button>
      <button class="drawer-tab" data-tab="zones">Zones</button>
    </div>
    <div class="drawer-panel" data-panel="devices">
      <div class="panel-header" id="dph">
        <span class="drawer-count" id="dc">0 devices</span>
        <div class="panel-actions">
          <button class="btn-icon-sm btn-add-device" id="badd" title="Add device">＋</button>
          <button class="btn-logout" id="blo">Sign out</button>
        </div>
      </div>
      <div class="device-list" id="dl"></div>
    </div>
    <div class="drawer-panel" data-panel="zones" hidden>
      <div class="panel-header">
        <span class="drawer-count" id="zc">0 zones</span>
        <button class="btn-icon-sm btn-add-zone" id="baddz" title="Add zone">＋</button>
      </div>
      <div class="zone-list" id="zl"></div>
    </div>
  `

  lastCallbacks = callbacks || {}

  const drawer = document.getElementById('drawer')

  function toggleExpanded() { drawer.classList.toggle('is-expanded') }

  document.getElementById('dh').addEventListener('click', toggleExpanded)

  // Tabs — expand drawer and switch panel
  document.getElementById('dtabs').addEventListener('click', e => {
    const tab = e.target.closest('.drawer-tab')
    if (!tab) return
    drawer.classList.add('is-expanded')
    const target = tab.dataset.tab
    document.querySelectorAll('.drawer-tab').forEach(t => t.classList.toggle('is-active', t.dataset.tab === target))
    document.querySelectorAll('.drawer-panel').forEach(p => { p.hidden = p.dataset.panel !== target })
  })

  // Panel header tap also expands
  document.getElementById('dph').addEventListener('click', toggleExpanded)

  // Logout
  document.getElementById('blo').addEventListener('click', e => {
    e.stopPropagation()
    lastCallbacks.onLogout?.()
  })

  // Add device button
  document.getElementById('badd').addEventListener('click', e => {
    e.stopPropagation()
    lastCallbacks.onAddDevice?.()
  })

  // Add zone button
  document.getElementById('baddz').addEventListener('click', e => {
    e.stopPropagation()
    lastCallbacks.onAddZone?.()
  })

  // Device list — click delegation
  document.getElementById('dl').addEventListener('click', e => {
    const item = e.target.closest('.device-item')
    if (!item) return
    const id = Number(item.dataset.id)
    const device = lastDevices.find(d => d.id === id)
    const pos = lastPositions.find(p => p.deviceId === id)
    if (!device) return

    if (e.target.closest('.btn-sound')) {
      lastCallbacks.onSound?.(device)
    } else if (e.target.closest('.btn-lost')) {
      if (lostModeSet.has(id)) lostModeSet.delete(id); else lostModeSet.add(id)
      lastCallbacks.onLostMode?.(device, lostModeSet.has(id))
      updateDevices()
    } else if (e.target.closest('.btn-history')) {
      lastCallbacks.onHistory?.(device)
    } else if (e.target.closest('.btn-edit')) {
      lastCallbacks.onEditDevice?.(device)
    } else {
      lastCallbacks.onCenterMap?.(device, pos)
    }
  })

  // Zone list — click delegation
  document.getElementById('zl').addEventListener('click', e => {
    const item = e.target.closest('.zone-item')
    if (!item) return
    const id = Number(item.dataset.id)
    const geofence = lastGeofences.find(g => g.id === id)
    if (!geofence) return
    if (e.target.closest('.btn-edit-zone')) {
      lastCallbacks.onEditZone?.(geofence)
    }
  })

  refreshTimer = setInterval(() => updateDevices(), 20000)
}

export function destroy() {
  clearInterval(refreshTimer)
  refreshTimer = null
}

// ── Update devices panel ──────────────────────────────────────────────────────

export function updateDevices(devices, positions, callbacks) {
  if (devices !== undefined) lastDevices = devices
  if (positions !== undefined) lastPositions = positions
  if (callbacks !== undefined) lastCallbacks = callbacks

  const dc = document.getElementById('dc')
  const dl = document.getElementById('dl')
  if (!dc || !dl) return

  const N = lastDevices?.length ?? 0
  dc.textContent = N === 1 ? '1 device' : N + ' devices'

  if (!N) {
    dl.innerHTML = `
      <div class="empty-state">
        <span class="empty-icon">🐱</span>
        <p>No devices found.</p>
        <p class="empty-sub">Tap ＋ to add your first device.</p>
      </div>`
    return
  }

  const posByDeviceId = new Map(lastPositions.map(p => [p.deviceId, p]))
  const parts = []

  for (const device of lastDevices) {
    const pos = posByDeviceId.get(device.id)
    const emoji = esc(device.attributes?.emoji || '📍')
    const bat = pos?.attributes?.batteryLevel != null ? Math.round(pos.attributes.batteryLevel) + '%' : '–'
    const time = relTime(pos?.fixTime || device?.lastUpdate)
    const lostCls = lostModeSet.has(device.id) ? ' is-active' : ''
    const status = device.status === 'online' ? 'online' : 'offline'
    const addr = addressCache.get(device.id)
    const addrHtml = addr ? `<div class="device-address">${esc(addr)}</div>` : `<div class="device-address" hidden></div>`

    parts.push(`
      <div class="device-item" data-id="${device.id}">
        <div class="device-emoji-wrap">
          <div class="device-emoji">${emoji}</div>
          <div class="status-dot status-${status}"></div>
        </div>
        <div class="device-info">
          <div class="device-name">${esc(device.name)}</div>
          ${addrHtml}
          <div class="device-meta">
            <span class="badge-battery">${bat}</span>
            <span class="meta-dot">·</span>
            <span class="badge-time">${time}</span>
          </div>
        </div>
        <div class="device-actions">
          <button class="btn-icon btn-center" title="Centre map">📍</button>
          <button class="btn-icon btn-history" title="History">🕐</button>
          <button class="btn-icon btn-sound" title="Sound">🔊</button>
          <button class="btn-icon btn-lost${lostCls}" title="Lost mode">🚨</button>
          <button class="btn-icon btn-edit" title="Edit device">✏️</button>
        </div>
      </div>`)

    scheduleGeocode(device, pos)
  }

  dl.innerHTML = parts.join('')
}

// ── Update zones panel ────────────────────────────────────────────────────────

export function updateZones(geofences, geofenceDevices, devices, callbacks) {
  if (geofences !== undefined) lastGeofences = geofences
  if (geofenceDevices !== undefined) lastGeofenceDevices = geofenceDevices
  if (devices !== undefined) lastDevices = devices
  if (callbacks !== undefined) lastCallbacks = callbacks

  const zc = document.getElementById('zc')
  const zl = document.getElementById('zl')
  if (!zc || !zl) return

  const N = lastGeofences?.length ?? 0
  zc.textContent = N === 1 ? '1 zone' : N + ' zones'

  if (!N) {
    zl.innerHTML = `
      <div class="empty-state">
        <span class="empty-icon">📍</span>
        <p>No zones yet.</p>
        <p class="empty-sub">Tap ＋ to add a zone on the map.</p>
      </div>`
    return
  }

  const deviceById = new Map(lastDevices.map(d => [d.id, d]))

  const parts = lastGeofences.map(gf => {
    const linkedIds = lastGeofenceDevices[gf.id] || []
    const linkedNames = linkedIds
      .map(id => deviceById.get(id))
      .filter(Boolean)
      .map(d => (d.attributes?.emoji || '📍') + ' ' + d.name)
      .join(', ')

    const radiusM = gf.area?.match(/CIRCLE\s*\([^,]+,\s*([\d.]+)/i)?.[1]
    const radiusLabel = radiusM ? (Number(radiusM) >= 1000 ? (Number(radiusM) / 1000).toFixed(1) + 'km' : radiusM + 'm') : ''

    const meta = [radiusLabel, linkedNames].filter(Boolean).join(' · ')

    return `
      <div class="zone-item" data-id="${gf.id}">
        <div class="zone-icon">📍</div>
        <div class="zone-info">
          <div class="zone-name">${esc(gf.name)}</div>
          ${meta ? `<div class="zone-meta">${esc(meta)}</div>` : ''}
        </div>
        <button class="btn-icon btn-edit-zone" title="Edit zone">✏️</button>
      </div>`
  })

  zl.innerHTML = parts.join('')
}
