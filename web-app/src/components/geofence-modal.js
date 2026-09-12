// Add / Edit geofence (zone) modal

function esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

function parseCircle(area) {
  const m = area?.match(/CIRCLE\s*\(\s*([-\d.]+)\s+([-\d.]+)\s*,\s*([\d.]+)\s*\)/i)
  return m ? { lat: +m[1], lng: +m[2], radius: +m[3] } : null
}

/**
 * @param {object} opts
 * @param {object|null}  opts.geofence      — existing geofence for edit, null for new
 * @param {object[]}     opts.devices       — all devices (for assignment checkboxes)
 * @param {number[]}     opts.linkedDeviceIds — device IDs currently linked to this geofence
 * @param {number|null}  opts.pendingLat    — lat from map tap (new zones only)
 * @param {number|null}  opts.pendingLng
 * @param {Function}     opts.onSave        — async ({ name, area, selectedDeviceIds }) => void
 * @param {Function}     opts.onDelete      — async () => void (edit only)
 * @param {Function}     opts.onClose
 */
export function openGeofenceModal({ geofence = null, devices = [], linkedDeviceIds = [], pendingLat, pendingLng, onSave, onDelete, onClose }) {
  const isEdit = !!geofence
  const existing = isEdit ? parseCircle(geofence.area) : null
  const lat = existing?.lat ?? pendingLat
  const lng = existing?.lng ?? pendingLng
  const radius = existing?.radius ?? 200

  const hasLocation = lat != null && lng != null

  const overlay = document.createElement('div')
  overlay.className = 'modal-overlay'
  overlay.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true">
      <div class="modal-header">
        <h2>${isEdit ? 'Edit Zone' : 'Add Zone'}</h2>
        <button class="modal-close" id="mc">✕</button>
      </div>
      <div class="modal-body">
        ${!hasLocation ? `<p class="modal-hint modal-hint-warn">⚠️ No location set — tap Cancel and use the map to place the zone.</p>` : `<p class="modal-hint">Centre: ${Number(lat).toFixed(5)}, ${Number(lng).toFixed(5)}</p>`}
        <div class="field mt-16">
          <label for="gname">Zone name</label>
          <input id="gname" type="text" value="${esc(geofence?.name || '')}" placeholder="e.g. Home" autocomplete="off" maxlength="64">
        </div>
        <div class="field">
          <label for="gradius">Radius (metres)</label>
          <input id="gradius" type="number" value="${radius}" min="50" max="100000" step="50">
        </div>
        <div class="field">
          <label>Assign to devices</label>
          <div class="check-list" id="gcl">
            ${devices.length ? devices.map(d => `
              <label class="check-row">
                <input type="checkbox" data-id="${d.id}" ${linkedDeviceIds.includes(d.id) ? 'checked' : ''}>
                <span>${esc(d.attributes?.emoji || '📍')} ${esc(d.name)}</span>
              </label>
            `).join('') : '<p class="empty-hint">No devices yet.</p>'}
          </div>
        </div>
      </div>
      <div class="modal-footer">
        <div class="modal-footer-left">
          ${isEdit ? '<button class="btn-danger" id="gdel">Delete</button>' : ''}
        </div>
        <div class="modal-footer-right">
          <button class="btn-secondary" id="mcan">Cancel</button>
          <button class="btn-primary modal-save-btn" id="msave">Save</button>
        </div>
      </div>
      <p class="modal-error" id="merr"></p>
    </div>
  `

  document.body.appendChild(overlay)
  requestAnimationFrame(() => overlay.classList.add('is-visible'))

  const errEl = overlay.querySelector('#merr')

  function close() {
    overlay.classList.remove('is-visible')
    setTimeout(() => { overlay.remove(); onClose?.() }, 200)
  }

  function showError(msg) { errEl.textContent = msg }

  overlay.querySelector('#mc').addEventListener('click', close)
  overlay.querySelector('#mcan').addEventListener('click', close)
  overlay.addEventListener('click', e => { if (e.target === overlay) close() })

  overlay.querySelector('#msave').addEventListener('click', async () => {
    const name = overlay.querySelector('#gname').value.trim()
    const r = Number(overlay.querySelector('#gradius').value)
    errEl.textContent = ''
    if (!name) { overlay.querySelector('#gname').focus(); return }
    if (!hasLocation) { showError('No location set. Cancel and tap the map to place the zone.'); return }
    if (!r || r < 50) { showError('Radius must be at least 50m'); return }

    const selectedDeviceIds = [...overlay.querySelectorAll('#gcl input:checked')].map(el => Number(el.dataset.id))
    const area = `CIRCLE (${lat} ${lng}, ${r})`

    const btn = overlay.querySelector('#msave')
    btn.disabled = true; btn.textContent = 'Saving…'
    try {
      await onSave({ name, area, selectedDeviceIds })
      close()
    } catch (err) {
      btn.disabled = false; btn.textContent = 'Save'
      showError(err?.message || 'Save failed')
    }
  })

  overlay.querySelector('#gdel')?.addEventListener('click', async () => {
    if (!confirm(`Delete zone "${geofence.name}"?\n\nThis cannot be undone.`)) return
    const btn = overlay.querySelector('#gdel')
    btn.disabled = true; btn.textContent = 'Deleting…'
    try {
      await onDelete()
      close()
    } catch {
      btn.disabled = false; btn.textContent = 'Delete'
      showError('Failed to delete zone')
    }
  })

  setTimeout(() => overlay.querySelector('#gname').focus(), 250)
}
