// Nominatim reverse geocoding — in-memory cache, 1 req/s rate limit
const cache = new Map()
let lastRequest = 0

function round(v) { return Math.round(v * 1000) / 1000 }

export async function reverseGeocode(lat, lng) {
  const key = round(lat) + ',' + round(lng)
  if (cache.has(key)) return cache.get(key)

  const wait = Math.max(0, 1100 - (Date.now() - lastRequest))
  if (wait > 0) await new Promise(r => setTimeout(r, wait))
  lastRequest = Date.now()

  try {
    const res = await fetch(
      `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lng}&format=json&zoom=14`,
      { headers: { 'Accept-Language': 'en' } }
    )
    if (!res.ok) { cache.set(key, null); return null }
    const d = await res.json()
    const a = d.address || {}
    const city = a.city || a.town || a.village || a.hamlet || a.county || ''
    const country = a.country_code?.toUpperCase() || ''
    const label = city ? (country ? city + ', ' + country : city) : null
    cache.set(key, label)
    return label
  } catch {
    cache.set(key, null)
    return null
  }
}
