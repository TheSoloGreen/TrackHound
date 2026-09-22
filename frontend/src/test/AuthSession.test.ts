import { afterEach, expect, it } from 'vitest'
import { AxiosError } from 'axios'
import { api } from '../api/client'

const originalAdapter = api.defaults.adapter
afterEach(() => { api.defaults.adapter = originalAdapter; localStorage.removeItem('token') })

it('keeps a rotated token when an older in-flight request returns 401', async () => {
  localStorage.setItem('token', 'old-token')
  api.defaults.adapter = async config => {
    localStorage.setItem('token', 'new-token')
    throw new AxiosError('Unauthorized', '401', config, null, { status: 401, data: {}, headers: {}, statusText: 'Unauthorized', config })
  }
  await expect(api.get('/api/auth/me')).rejects.toThrow()
  expect(localStorage.getItem('token')).toBe('new-token')
})

it('clears a token rejected by its own request', async () => {
  localStorage.setItem('token', 'rejected-token')
  api.defaults.adapter = async config => {
    throw new AxiosError('Unauthorized', '401', config, null, { status: 401, data: {}, headers: {}, statusText: 'Unauthorized', config })
  }
  await expect(api.get('/api/auth/me')).rejects.toThrow()
  expect(localStorage.getItem('token')).toBeNull()
})
