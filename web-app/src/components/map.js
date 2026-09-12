const DEFAULT_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
const DEFAULT_TILE_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
const SAT_TILE_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
const SAT_TILE_ATTR = "Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics"

// Module-level singletons — survive re-renders, reset on destroyMap()
let _maplibregl = null
let _map = null
const markerMap = new Map()
let hasInitialFit = false
let userLocationMarker = null
let geoWatchId = null
let isSatellite = false      // persists across re-renders
let placementCallback = null

// ── Helpers ──────────────────────────────────────────────────────────────────

function parseCircle(area) {
  const m = area?.match(/CIRCLE\s*\(\s*([-\d.]+)\s+([-\d.]+)\s*,\s*([\d.]+)\s*\)/i)
  return m ? { lat: +m[1], lng: +m[2], radius: +m[3] } : null
}

function circlePolygon(lat, lng, r, steps = 64) {
  const pts = []
  for (let i = 0; i <= steps; i++) {
    const a = (i / steps) * 2 * Math.PI
    const dLat = (r * Math.sin(a)) / 111320
    const dLng = (r * Math.cos(a)) / (111320 * Math.cos(lat * Math.PI / 180))
    pts.push([lng + dLng, lat + dLat])
  }
  return pts
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────

export function destroyMap() {
  placementCallback = null
  if (geoWatchId != null) {
    navigator.geolocation.clearWatch(geoWatchId)
    geoWatchId = null
  }
  if (_map) { _map.remove(); _map = null }
  markerMap.clear()
  hasInitialFit = false
  userLocationMarker = null
}

export async function initMap(containerId) {
  _maplibregl = window.maplibregl
  if (!_maplibregl) throw new Error("maplibregl not loaded — check <script> tag in index.html")
  destroyMap()

  const tileUrl = window.FINDMYCAT_CONFIG?.tileUrl || DEFAULT_TILE_URL
  const tileAttr = window.FINDMYCAT_CONFIG?.tileAttribution || DEFAULT_TILE_ATTR

  _map = new _maplibregl.Map({
    container: containerId,
    style: {
      version: 8,
      sources: {
        "raster-tiles": {
          type: "raster",
          tiles: [isSatellite ? SAT_TILE_URL : tileUrl],
          tileSize: 256,
          attribution: isSatellite ? SAT_TILE_ATTR : tileAttr,
        },
      },
      layers: [{ id: "raster-tiles", type: "raster", source: "raster-tiles", minzoom: 0, maxzoom: 22 }],
    },
    center: [0, 20],
    zoom: 2,
  })

  await new Promise(resolve => _map.on("load", resolve))

  // Geofence overlay (fill + outline + label)
  _map.addSource("geofences", { type: "geojson", data: { type: "FeatureCollection", features: [] } })
  _map.addLayer({ id: "geofence-fill", type: "fill", source: "geofences", paint: { "fill-color": "#6C63FF", "fill-opacity": 0.12 } })
  _map.addLayer({ id: "geofence-line", type: "line", source: "geofences", paint: { "line-color": "#6C63FF", "line-width": 2, "line-opacity": 0.7 } })
  _map.addLayer({
    id: "geofence-label", type: "symbol", source: "geofences",
    layout: { "text-field": ["get", "name"], "text-size": 12, "text-anchor": "center" },
    paint: { "text-color": "#A89FFF", "text-halo-color": "#111118", "text-halo-width": 2 },
  })

  // History track overlay (line + dots)
  _map.addSource("track", { type: "geojson", data: { type: "FeatureCollection", features: [] } })
  _map.addLayer({ id: "track-line", type: "line", source: "track", filter: ["==", "$type", "LineString"], paint: { "line-color": "#FF6B35", "line-width": 3, "line-opacity": 0.9 } })
  _map.addLayer({ id: "track-points", type: "circle", source: "track", filter: ["==", "$type", "Point"], paint: { "circle-radius": 4, "circle-color": "#FF6B35", "circle-stroke-width": 2, "circle-stroke-color": "#fff", "circle-opacity": 0.9 } })

  // Map click for placement mode
  _map.on("click", e => {
    if (!placementCallback) return
    const { lat, lng } = e.lngLat
    const cb = placementCallback
    exitPlacementMode()
    cb({ lat, lng })
  })

  return { updateMarkers, centerOn, showUserLocation, updateGeofences, showTrack, clearTrack, toggleMapStyle, enterPlacementMode, exitPlacementMode }
}

// ── Device markers ────────────────────────────────────────────────────────────

export function updateMarkers(devices, positions) {
  if (!_map || !_maplibregl) return

  const positionByDeviceId = new Map()
  for (const pos of positions) positionByDeviceId.set(pos.deviceId, pos)

  const activeIds = new Set()

  for (const device of devices) {
    const position = positionByDeviceId.get(device.id)
    if (!position) continue
    activeIds.add(device.id)
    const lngLat = [position.longitude, position.latitude]

    if (markerMap.has(device.id)) {
      markerMap.get(device.id).setLngLat(lngLat)
    } else {
      const emoji = device.attributes?.emoji || "📍"
      const div = document.createElement("div")
      div.className = "map-marker"
      const span = document.createElement("span")
      span.textContent = emoji
      span.style.fontSize = "28px"
      div.appendChild(span)
      markerMap.set(device.id, new _maplibregl.Marker({ element: div }).setLngLat(lngLat).addTo(_map))
    }
  }

  for (const [deviceId, marker] of markerMap.entries()) {
    if (!activeIds.has(deviceId)) { marker.remove(); markerMap.delete(deviceId) }
  }

  if (!hasInitialFit && positions.length > 0) {
    hasInitialFit = true
    const lls = positions.map(p => [p.longitude, p.latitude])
    const bounds = lls.reduce(
      (b, [x, y]) => [[Math.min(b[0][0], x), Math.min(b[0][1], y)], [Math.max(b[1][0], x), Math.max(b[1][1], y)]],
      [[lls[0][0], lls[0][1]], [lls[0][0], lls[0][1]]]
    )
    _map.fitBounds(bounds, { padding: 80, maxZoom: 14 })
  }
}

// ── Geofences ─────────────────────────────────────────────────────────────────

export function updateGeofences(geofences) {
  if (!_map) return
  const features = []
  for (const gf of geofences) {
    const c = parseCircle(gf.area)
    if (!c) continue
    features.push({
      type: "Feature",
      properties: { name: gf.name, id: gf.id },
      geometry: { type: "Polygon", coordinates: [circlePolygon(c.lat, c.lng, c.radius)] },
    })
  }
  _map.getSource("geofences")?.setData({ type: "FeatureCollection", features })
}

// ── History track ─────────────────────────────────────────────────────────────

export function showTrack(positions) {
  if (!_map) return
  if (!positions?.length) { clearTrack(); return }
  const sorted = [...positions].sort((a, b) => new Date(a.fixTime) - new Date(b.fixTime))
  const coords = sorted.map(p => [p.longitude, p.latitude])
  const pointFeatures = sorted.map(p => ({
    type: "Feature",
    geometry: { type: "Point", coordinates: [p.longitude, p.latitude] },
    properties: { fixTime: p.fixTime, speed: p.speed || 0 },
  }))
  _map.getSource("track")?.setData({
    type: "FeatureCollection",
    features: [
      { type: "Feature", geometry: { type: "LineString", coordinates: coords }, properties: {} },
      ...pointFeatures,
    ],
  })
  if (coords.length > 1) {
    const bounds = coords.reduce(
      (b, [x, y]) => [[Math.min(b[0][0], x), Math.min(b[0][1], y)], [Math.max(b[1][0], x), Math.max(b[1][1], y)]],
      [[coords[0][0], coords[0][1]], [coords[0][0], coords[0][1]]]
    )
    _map.fitBounds(bounds, { padding: 80, maxZoom: 15 })
  }
}

export function clearTrack() {
  _map?.getSource("track")?.setData({ type: "FeatureCollection", features: [] })
}

// ── Map style toggle ──────────────────────────────────────────────────────────

export function toggleMapStyle() {
  isSatellite = !isSatellite
  if (_map?.getSource("raster-tiles")) {
    // Re-add the source rather than setTiles() — attribution can only be set
    // at source creation, and it must switch along with the tile provider.
    const tileUrl = window.FINDMYCAT_CONFIG?.tileUrl || DEFAULT_TILE_URL
    const tileAttr = window.FINDMYCAT_CONFIG?.tileAttribution || DEFAULT_TILE_ATTR
    const beforeId = _map.getStyle().layers.find(l => l.id !== "raster-tiles")?.id
    _map.removeLayer("raster-tiles")
    _map.removeSource("raster-tiles")
    _map.addSource("raster-tiles", {
      type: "raster",
      tiles: [isSatellite ? SAT_TILE_URL : tileUrl],
      tileSize: 256,
      attribution: isSatellite ? SAT_TILE_ATTR : tileAttr,
    })
    _map.addLayer({ id: "raster-tiles", type: "raster", source: "raster-tiles", minzoom: 0, maxzoom: 22 }, beforeId)
  }
  return isSatellite
}

// ── Geofence placement mode ───────────────────────────────────────────────────

export function enterPlacementMode(callback) {
  if (!_map) return
  placementCallback = callback
  _map.getCanvas().style.cursor = "crosshair"
}

export function exitPlacementMode() {
  placementCallback = null
  if (_map) _map.getCanvas().style.cursor = ""
}

// ── User location ─────────────────────────────────────────────────────────────

export function centerOn(lat, lng) {
  if (!_map) return
  _map.flyTo({ center: [lng, lat], zoom: 15, duration: 800 })
}

export function showUserLocation() {
  if (!navigator.geolocation || !_maplibregl || !_map) return
  if (geoWatchId != null) return

  geoWatchId = navigator.geolocation.watchPosition(position => {
    const { longitude, latitude } = position.coords
    const lngLat = [longitude, latitude]
    if (userLocationMarker) {
      userLocationMarker.setLngLat(lngLat)
    } else {
      const dot = document.createElement("div")
      dot.className = "user-location-dot"
      userLocationMarker = new _maplibregl.Marker({ element: dot }).setLngLat(lngLat).addTo(_map)
    }
  }, () => {})
}
