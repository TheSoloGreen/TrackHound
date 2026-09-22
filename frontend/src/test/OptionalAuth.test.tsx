import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { authApi } from '../api/client'
import { useAuth } from '../hooks/useAuth'
import AuthenticationSettings from '../components/AuthenticationSettings'
import BuildVersion from '../components/BuildVersion'
import { renderWithClient } from './helpers'

beforeEach(() => { vi.restoreAllMocks(); localStorage.clear() })

function Session() {
  const { isAuthenticated, authRequired, isLoading, user } = useAuth()
  return <p>{isLoading ? 'Loading' : isAuthenticated ? `Library for ${user?.username}; login ${authRequired ? 'required' : 'not required'}` : 'Sign in required'}</p>
}

it('opens the shared account without a stored token when mode is None', async () => {
  vi.spyOn(authApi, 'getConfig').mockResolvedValue({ data: { mode: 'none' } } as never)
  vi.spyOn(authApi, 'getCurrentUser').mockResolvedValue({ data: { id: 1, username: 'owner' } } as never)
  renderWithClient(<Session />)
  expect(await screen.findByText('Library for owner; login not required')).toBeVisible()
  expect(localStorage.getItem('token')).toBeNull()
})

it('does not open a protected account without a token', async () => {
  vi.spyOn(authApi, 'getConfig').mockResolvedValue({ data: { mode: 'login' } } as never)
  const me = vi.spyOn(authApi, 'getCurrentUser')
  renderWithClient(<Session />)
  expect(await screen.findByText('Sign in required')).toBeVisible()
  expect(me).not.toHaveBeenCalled()
})

it('shows None by default and asks for credentials before enabling login', async () => {
  vi.spyOn(authApi, 'getConfig').mockResolvedValue({ data: { mode: 'none' } } as never)
  const save = vi.spyOn(authApi, 'setConfig').mockRejectedValue({ isAxiosError: true, response: { data: { detail: 'That username is already in use.' } } })
  renderWithClient(<AuthenticationSettings />)
  const user = userEvent.setup()
  const method = await screen.findByRole('combobox', { name: 'Login method' })
  expect(method).toHaveValue('none')
  await user.selectOptions(method, 'login')
  await user.type(screen.getByLabelText('Login password', { exact: true }), 'synthetic-password')
  await user.type(screen.getByLabelText('Confirm login password'), 'different-password')
  await user.click(screen.getByRole('button', { name: 'Save authentication' }))
  expect(screen.getByRole('alert')).toHaveTextContent('Passwords do not match')
  expect(save).not.toHaveBeenCalled()
  await user.clear(screen.getByLabelText('Confirm login password'))
  await user.type(screen.getByLabelText('Confirm login password'), 'synthetic-password')
  await user.click(screen.getByRole('button', { name: 'Save authentication' }))
  await waitFor(() => expect(save).toHaveBeenCalledWith({ mode: 'login', username: 'admin', password: 'synthetic-password' }))
  expect(screen.getByRole('alert')).toHaveTextContent('already in use')
})

it('displays the running server version and revision, including the full revision on hover', async () => {
  vi.spyOn(authApi, 'getBuildInfo').mockResolvedValue({ data: { version: '0.2.0', revision: 'abc123def4567890' } } as never)
  renderWithClient(<BuildVersion />)
  expect(await screen.findByText('TrackHound v0.2.0 · abc123def456')).toHaveAttribute('title', 'Container revision: abc123def4567890')
})
