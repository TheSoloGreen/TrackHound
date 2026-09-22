import { useEffect, useRef, useState } from 'react'
import { useAuth } from '../hooks/useAuth'
import { authApi } from '../api/client'
import { apiError } from '../api/errors'
import { isAxiosError } from 'axios'

export default function AccountPage() {
  const { user, login, authRequired } = useAuth()
  const [username, setUsername] = useState(user?.username || '')
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const cancelled = useRef(false)
  useEffect(() => { cancelled.current = false; return () => { cancelled.current = true; if (timer.current) clearTimeout(timer.current) } }, [])

  async function save(event: React.FormEvent) {
    event.preventDefault()
    setError(''); setMessage('')
    if (newPassword !== confirmation) { setError('New passwords do not match.'); return }
    setBusy(true)
    try {
      const response = await authApi.updateAccount({ username, current_password: currentPassword, new_password: newPassword || undefined })
      await login(response.data.access_token)
      setCurrentPassword(''); setNewPassword(''); setConfirmation('')
      setMessage('Account updated. Other sessions have been signed out.')
    } catch (err) { setError(apiError(err, 'Could not update your account.')) }
    finally { setBusy(false) }
  }

  async function connectPlex() {
    setBusy(true); setError(''); setMessage('')
    // Open synchronously so popup blockers do not lose the user gesture.
    const popup = window.open('about:blank', 'plex-link', 'width=600,height=700')
    try {
      if (!popup) throw new Error('popup blocked')
      const { data } = await authApi.initiateLogin()
      if (cancelled.current) { popup.close(); return }
      popup.location.href = data.auth_url
      setMessage('Complete Plex authorization in the popup window.')
      let attempts = 0
      const poll = async () => {
        if (cancelled.current) return
        try {
          const response = await authApi.linkPlex(data.pin_id)
          if (cancelled.current) return
          await login(response.data.access_token)
          popup.close(); setMessage('Plex connected to this account.'); setBusy(false)
        } catch (err) {
          if (cancelled.current) return
          const pending = isAxiosError(err) && err.response?.status === 400 && String(err.response.data?.detail).startsWith('PIN not yet authorized')
          if (pending && ++attempts < 60) timer.current = setTimeout(poll, 5000)
          else { setError(apiError(err, 'Plex connection timed out. Please try again.')); setMessage(''); setBusy(false); popup.close() }
        }
      }
      await poll()
    } catch { popup?.close(); setError('Could not open Plex authorization. Allow popups and try again.'); setBusy(false) }
  }

  const required = user?.must_change_password || !user?.has_local_password
  const inputClass = 'block w-full mt-1 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2'
  return <section className="max-w-xl space-y-5">
<h1 className="text-2xl font-bold">Account</h1>
    {authRequired === false && <p>Login is currently disabled. Saving credentials here does not enable it; choose Require login in Settings when you want it.</p>}
    {authRequired !== false && user?.must_change_password && <p role="alert">Change your initial password before using TrackHound. You can also rename the admin account.</p>}
    {error && <p role="alert" className="text-red-600 dark:text-red-400">{error}</p>}
    {message && <p role="status">{message}</p>}
    <form onSubmit={save} className="space-y-4">
      <label className="block">Username<input className={inputClass} autoComplete="username" required minLength={3} maxLength={64} pattern="[a-zA-Z0-9_.\-]+" value={username} onChange={e => setUsername(e.target.value)} disabled={busy} /></label>
      <p className="text-sm text-gray-500">3–64 letters, numbers, dots, underscores, or hyphens. Sign-in is case-insensitive.</p>
      {authRequired !== false && user?.has_local_password && <label className="block">Current password<input className={inputClass} type="password" autoComplete="current-password" required maxLength={128} value={currentPassword} onChange={e => setCurrentPassword(e.target.value)} disabled={busy} /></label>}
      <label className="block">New password<input className={inputClass} type="password" autoComplete="new-password" required={required} minLength={12} maxLength={128} value={newPassword} onChange={e => setNewPassword(e.target.value)} disabled={busy} /></label>
      <label className="block">Confirm new password<input className={inputClass} type="password" autoComplete="new-password" required={required || !!newPassword} value={confirmation} onChange={e => setConfirmation(e.target.value)} disabled={busy} /></label>
      <p className="text-sm text-gray-500">Use at least 12 characters. {required ? '' : 'Leave the new password blank to keep your current password.'}</p>
      <button disabled={busy} className="rounded bg-orange-600 px-4 py-2 text-white disabled:opacity-50">{busy ? 'Please wait…' : 'Save account'}</button>
    </form>
    {(authRequired === false || !user?.must_change_password) && <div className="border-t pt-4 space-y-2">
      <h2 className="font-semibold">Optional Plex connection</h2>
      <p>{user?.plex_connected ? 'Plex is connected. You can sign in with either method.' : 'Connect Plex to use its metadata and sign in to this same library with Plex.'}</p>
      <button disabled={busy} onClick={connectPlex} className="rounded border px-4 py-2 disabled:opacity-50">{user?.plex_connected ? 'Reconnect Plex' : 'Connect Plex'}</button>
    </div>}
  </section>
}
