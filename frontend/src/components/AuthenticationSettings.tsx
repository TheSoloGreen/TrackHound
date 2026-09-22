import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { authApi } from '../api/client'
import { apiError } from '../api/errors'

export default function AuthenticationSettings() {
  const client = useQueryClient()
  const { data, isLoading, isError, refetch } = useQuery({ queryKey: ['authConfig'], queryFn: async () => (await authApi.getConfig()).data })
  const [mode, setMode] = useState<'none' | 'login' | null>(null)
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const selected = mode ?? data?.mode ?? 'none'
  const enabling = selected === 'login' && data?.mode === 'none'

  async function save(event: React.FormEvent) {
    event.preventDefault(); setError('')
    if (enabling && password !== confirmation) { setError('Passwords do not match.'); return }
    setBusy(true)
    try {
      await authApi.setConfig({ mode: selected, ...(enabling ? { username, password } : {}) })
      localStorage.removeItem('token')
      window.dispatchEvent(new StorageEvent('storage', { key: 'token', newValue: null }))
      setPassword(''); setConfirmation(''); setMode(null)
      // Refetch policy and identity together; None always uses the shared owner.
      client.clear()
      window.location.assign(selected === 'login' ? '/login' : '/settings')
    } catch (err) { setError(apiError(err, 'Could not save authentication settings.')) }
    finally { setBusy(false) }
  }

  return <section className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-6 space-y-4">
    <h2 className="text-lg font-semibold">Authentication</h2>
    {isLoading && <p role="status">Loading authentication settings…</p>}
    {isError && <p role="alert">Could not load authentication settings. <button className="underline" onClick={() => refetch()}>Retry</button></p>}
    {data && <form onSubmit={save} className="space-y-4 max-w-xl">
      <label className="block">Login method
        <select value={selected} onChange={e => setMode(e.target.value as 'none' | 'login')} disabled={busy} className="block w-full mt-1 rounded border bg-white dark:bg-gray-900 px-3 py-2">
          <option value="none">None — no login required</option>
          <option value="login">Require login — username/password or Plex</option>
        </select>
      </label>
      <p className="text-sm text-gray-500 dark:text-gray-400">With None, anyone who can reach this instance can use its shared library and settings. Login is required only when you enable it here.</p>
      {enabling && <>
        <p>Choose the local credentials you will use to sign in. Plex remains available if connected.</p>
        <label className="block">Login username<input required minLength={3} maxLength={64} pattern="[a-zA-Z0-9_.\-]+" autoComplete="username" value={username} onChange={e => setUsername(e.target.value)} disabled={busy} className="block w-full rounded border bg-white dark:bg-gray-900 p-2" /></label>
        <label className="block">Login password<input required minLength={12} maxLength={128} type="password" autoComplete="new-password" value={password} onChange={e => setPassword(e.target.value)} disabled={busy} className="block w-full rounded border bg-white dark:bg-gray-900 p-2" /></label>
        <label className="block">Confirm login password<input required type="password" autoComplete="new-password" value={confirmation} onChange={e => setConfirmation(e.target.value)} disabled={busy} className="block w-full rounded border bg-white dark:bg-gray-900 p-2" /></label>
        <p className="text-sm text-gray-500">Use at least 12 characters. Saving will take you to the login page.</p>
      </>}
      {error && <p role="alert" className="text-red-600 dark:text-red-400">{error}</p>}
      <button disabled={busy || selected === data.mode} className="rounded bg-orange-600 px-4 py-2 text-white disabled:opacity-50">{busy ? 'Saving…' : 'Save authentication'}</button>
    </form>}
  </section>
}
