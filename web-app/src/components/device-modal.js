// Add / Edit device modal with emoji picker

const EMOJIS = [
  '🐱','🐈','🐈‍⬛','😸','😺','🐾','🐶','🐕','🦊','🐻','🐼','🐨','🦁',
  '🐯','🐺','🐗','🦝','🦔','🐭','🐹','🐰','🦇','🦉','🦅','🐦','🦜',
  '🌟','⭐','💫','✨','❤️','🔥','🌈','🎯','📍','🏠','🌲','🌊','🎪','🎭',
]

function esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

export function openDeviceModal({ device = null, onSave, onDelete, onClose }) {
  const isEdit = !!device
  let emoji = device?.attributes?.emoji || '🐱'

  const overlay = document.createElement('div')
  overlay.className = 'modal-overlay'
  overlay.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true">
      <div class="modal-header">
        <h2>${isEdit ? 'Edit Device' : 'Add Device'}</h2>
        <button class="modal-close" id="mc">✕</button>
      </div>
      <div class="modal-body">
        <div class="emoji-preview-wrap">
          <div class="emoji-preview" id="epv">${emoji}</div>
        </div>
        <div class="emoji-grid" id="egrid">
          ${EMOJIS.map(e => `<button class="emoji-btn${e === emoji ? ' is-selected' : ''}" data-e="${esc(e)}">${e}</button>`).join('')}
        </div>
        <div class="field mt-16">
          <label for="mname">Name</label>
          <input id="mname" type="text" value="${esc(device?.name || '')}" placeholder="e.g. Whiskers" autocomplete="off" maxlength="64">
        </div>
        <div class="field">
          <label for="muid">Device ID${isEdit ? ' <span class="label-hint">(read-only)</span>' : ''}</label>
          <input id="muid" type="text" value="${esc(device?.uniqueId || '')}" placeholder="Traccar unique ID" ${isEdit ? 'readonly' : ''}>
        </div>
      </div>
      <div class="modal-footer">
        <div class="modal-footer-left">
          ${isEdit ? '<button class="btn-danger" id="mdel">Remove</button>' : ''}
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

  const nameInput = overlay.querySelector('#mname')
  const uidInput = overlay.querySelector('#muid')
  const preview = overlay.querySelector('#epv')
  const errEl = overlay.querySelector('#merr')

  function close() {
    overlay.classList.remove('is-visible')
    setTimeout(() => { overlay.remove(); onClose?.() }, 200)
  }

  overlay.querySelector('#mc').addEventListener('click', close)
  overlay.querySelector('#mcan').addEventListener('click', close)
  overlay.addEventListener('click', e => { if (e.target === overlay) close() })

  overlay.querySelector('#egrid').addEventListener('click', e => {
    const btn = e.target.closest('.emoji-btn')
    if (!btn) return
    emoji = btn.dataset.e
    preview.textContent = emoji
    overlay.querySelectorAll('.emoji-btn').forEach(b => b.classList.toggle('is-selected', b.dataset.e === emoji))
  })

  overlay.querySelector('#msave').addEventListener('click', async () => {
    const name = nameInput.value.trim()
    const uniqueId = uidInput.value.trim()
    errEl.textContent = ''
    if (!name) { nameInput.focus(); return }
    if (!uniqueId) { uidInput.focus(); return }

    const btn = overlay.querySelector('#msave')
    btn.disabled = true; btn.textContent = 'Saving…'
    try {
      await onSave({
        ...(isEdit ? { id: device.id } : {}),
        name,
        uniqueId,
        attributes: { ...(device?.attributes || {}), emoji },
      })
      close()
    } catch (err) {
      btn.disabled = false; btn.textContent = 'Save'
      errEl.textContent = err?.message || 'Save failed'
    }
  })

  overlay.querySelector('#mdel')?.addEventListener('click', async () => {
    if (!confirm(`Remove "${device.name}" from your account?\n\nThis cannot be undone.`)) return
    const btn = overlay.querySelector('#mdel')
    btn.disabled = true; btn.textContent = 'Removing…'
    try {
      await onDelete()
      close()
    } catch {
      btn.disabled = false; btn.textContent = 'Remove'
      errEl.textContent = 'Failed to remove device'
    }
  })

  setTimeout(() => nameInput.focus(), 250)
}
