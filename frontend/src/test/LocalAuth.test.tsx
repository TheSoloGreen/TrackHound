import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import { authApi } from '../api/client'
import LoginPage from '../pages/LoginPage'
import AccountPage from '../pages/AccountPage'
import App from '../App'
import { renderWithClient } from './helpers'

const { state, login } = vi.hoisted(() => ({ state: { user: null as any, isAuthenticated: false, isLoading: false }, login: vi.fn() }))
vi.mock('../hooks/useAuth', () => ({ useAuth: () => ({ ...state, login, logout: vi.fn() }) }))
vi.mock('../hooks/useScanStatus', () => ({ useScanStatus: () => ({}) }))

beforeEach(() => {
  vi.restoreAllMocks(); login.mockReset()
  state.user = null; state.isAuthenticated = false
})

it('offers password and Plex login and sends the password only on submit', async () => {
  const request = vi.spyOn(authApi, 'passwordLogin').mockResolvedValue({ data: { access_token: 'synthetic-token' } } as never)
  renderWithClient(<MemoryRouter><LoginPage /></MemoryRouter>)
  expect(screen.getByRole('button', { name: 'Sign in with Plex' })).toBeVisible()
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Username'), 'admin')
  await user.type(screen.getByLabelText('Password', { exact: true }), 'synthetic-password')
  expect(request).not.toHaveBeenCalled()
  await user.click(screen.getByRole('button', { name: /^Sign in$/ }))
  await waitFor(() => expect(login).toHaveBeenCalledWith('synthetic-token'))
  expect(request).toHaveBeenCalledWith('admin', 'synthetic-password')
})

it('shows failed login without losing the username', async () => {
  vi.spyOn(authApi, 'passwordLogin').mockRejectedValue({ isAxiosError: true, response: { status: 401, data: { detail: 'Invalid username or password.' } } })
  renderWithClient(<MemoryRouter><LoginPage /></MemoryRouter>)
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Username'), 'owner')
  await user.type(screen.getByLabelText('Password', { exact: true }), 'wrong')
  await user.click(screen.getByRole('button', { name: /^Sign in$/ }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Invalid username or password.')
  expect(screen.getByLabelText('Username')).toHaveValue('owner')
})

it('requires initial-password change before showing the library', async () => {
  state.user = { id: 1, username: 'admin', has_local_password: true, must_change_password: true }
  state.isAuthenticated = true
  renderWithClient(<MemoryRouter initialEntries={['/files']}><App /></MemoryRouter>)
  expect(await screen.findByRole('heading', { name: 'Account' })).toBeVisible()
  expect(screen.getByRole('alert')).toHaveTextContent('Change your initial password')
  expect(screen.queryByRole('heading', { name: 'Files' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Connect Plex' })).not.toBeInTheDocument()
})

it('validates confirmation then rotates credentials and updates the session', async () => {
  state.user = { id: 1, username: 'admin', has_local_password: true, must_change_password: true }
  state.isAuthenticated = true
  const request = vi.spyOn(authApi, 'updateAccount').mockResolvedValue({ data: { access_token: 'rotated-token' } } as never)
  renderWithClient(<MemoryRouter><AccountPage /></MemoryRouter>)
  const user = userEvent.setup()
  await user.clear(screen.getByLabelText('Username'))
  await user.type(screen.getByLabelText('Username'), 'owner')
  await user.type(screen.getByLabelText('Current password'), 'initial-password')
  await user.type(screen.getByLabelText('New password', { exact: true }), 'replacement-password')
  await user.type(screen.getByLabelText('Confirm new password'), 'does-not-match')
  await user.click(screen.getByRole('button', { name: 'Save account' }))
  expect(screen.getAllByRole('alert').some(el => el.textContent?.includes('do not match'))).toBe(true)
  expect(request).not.toHaveBeenCalled()
  await user.clear(screen.getByLabelText('Confirm new password'))
  await user.type(screen.getByLabelText('Confirm new password'), 'replacement-password')
  await user.click(screen.getByRole('button', { name: 'Save account' }))
  await waitFor(() => expect(login).toHaveBeenCalledWith('rotated-token'))
  expect(request).toHaveBeenCalledWith({ username: 'owner', current_password: 'initial-password', new_password: 'replacement-password' })
  expect(screen.getByLabelText('Current password')).toHaveValue('')
})
