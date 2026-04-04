import { useCallback, useEffect, useId, useRef, useState } from 'react'
import type { CurrentUser } from '../auth/session'
import { patchCurrentUser } from '../auth/session'

function initialsFromUser(user: CurrentUser): string {
  const n = (user.display_name || user.email || '?').trim()
  const parts = n.split(/\s+/).filter(Boolean)
  if (parts.length >= 2) {
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
  }
  return n.slice(0, 2).toUpperCase() || '?'
}

/** Resize to max edge `maxPx`, output jpeg data URL (within server size limits). */
function resizeImageFileToJpegDataUrl(file: File, maxPx: number): Promise<string> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    const objectUrl = URL.createObjectURL(file)
    img.onload = () => {
      URL.revokeObjectURL(objectUrl)
      let w = img.naturalWidth
      let h = img.naturalHeight
      const scale = Math.min(1, maxPx / Math.max(w, h, 1))
      w = Math.max(1, Math.round(w * scale))
      h = Math.max(1, Math.round(h * scale))
      const canvas = document.createElement('canvas')
      canvas.width = w
      canvas.height = h
      const ctx = canvas.getContext('2d')
      if (!ctx) {
        reject(new Error('Could not prepare image'))
        return
      }
      ctx.drawImage(img, 0, 0, w, h)
      resolve(canvas.toDataURL('image/jpeg', 0.88))
    }
    img.onerror = () => {
      URL.revokeObjectURL(objectUrl)
      reject(new Error('Could not read image'))
    }
    img.src = objectUrl
  })
}

type Props = {
  user: CurrentUser
  onUserUpdated: (u: CurrentUser) => void
}

export function ProfileAvatarControl({ user, onUserUpdated }: Props) {
  const menuId = useId()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [imgBroken, setImgBroken] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setImgBroken(false)
  }, [user.avatar_data_url])

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  const onPickFile = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const f = e.target.files?.[0]
      e.target.value = ''
      if (!f || !f.type.startsWith('image/')) {
        setErr('Choose an image file.')
        return
      }
      setErr(null)
      setBusy(true)
      try {
        const dataUrl = await resizeImageFileToJpegDataUrl(f, 256)
        const u = await patchCurrentUser({ avatar_data_url: dataUrl })
        onUserUpdated(u)
        setOpen(false)
      } catch (x) {
        setErr(x instanceof Error ? x.message : 'Upload failed')
      } finally {
        setBusy(false)
      }
    },
    [onUserUpdated],
  )

  const onRemove = useCallback(async () => {
    setErr(null)
    setBusy(true)
    try {
      const u = await patchCurrentUser({ avatar_data_url: '' })
      onUserUpdated(u)
      setOpen(false)
    } catch (x) {
      setErr(x instanceof Error ? x.message : 'Remove failed')
    } finally {
      setBusy(false)
    }
  }, [onUserUpdated])

  const showUrl = user.avatar_data_url && !imgBroken
  const initials = initialsFromUser(user)

  return (
    <div className="relative shrink-0" ref={wrapRef}>
      <button
        type="button"
        id={menuId}
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        title="Profile photo — click to change"
        className="relative w-10 h-10 rounded-full overflow-hidden ring-2 ring-stone-600 hover:ring-amber-600/70 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-500 transition-shadow bg-stone-800 flex items-center justify-center"
      >
        {showUrl ? (
          <img
            src={user.avatar_data_url!}
            alt=""
            className="w-full h-full object-cover"
            onError={() => setImgBroken(true)}
          />
        ) : (
          <span className="text-sm font-semibold text-stone-200 tracking-tight">{initials}</span>
        )}
      </button>

      {open && (
        <div
          role="menu"
          aria-labelledby={menuId}
          className="absolute left-0 top-full mt-2 z-50 w-56 rounded-lg border border-stone-600 bg-stone-800 shadow-xl py-2 px-2 text-sm"
        >
          <p className="text-stone-400 text-xs px-1 pb-2">Profile picture</p>
          <input
            ref={fileRef}
            type="file"
            accept="image/jpeg,image/png,image/webp,image/gif"
            className="hidden"
            onChange={onPickFile}
          />
          <button
            type="button"
            disabled={busy}
            onClick={() => fileRef.current?.click()}
            className="w-full text-left px-2 py-1.5 rounded-md text-stone-100 hover:bg-stone-700 disabled:opacity-50"
          >
            {busy ? 'Saving…' : 'Upload photo…'}
          </button>
          {user.avatar_data_url ? (
            <button
              type="button"
              disabled={busy}
              onClick={onRemove}
              className="w-full text-left px-2 py-1.5 rounded-md text-stone-400 hover:bg-stone-700 hover:text-stone-200 disabled:opacity-50"
            >
              Remove photo
            </button>
          ) : null}
          {err && <p className="text-red-400 text-xs px-1 pt-2">{err}</p>}
        </div>
      )}
    </div>
  )
}
