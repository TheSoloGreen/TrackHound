import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import ShowArtwork from '../components/ShowArtwork'
import { api, mediaApi } from '../api/client'
import { deferred } from './helpers'

const createObjectURL = vi.fn(() => 'blob:synthetic-poster')
const revokeObjectURL = vi.fn()
beforeEach(() => {
  vi.restoreAllMocks()
  createObjectURL.mockClear()
  revokeObjectURL.mockClear()
  vi.stubGlobal('URL', { createObjectURL, revokeObjectURL })
})
afterEach(() => { vi.unstubAllGlobals(); localStorage.clear() })

it('loads authorized artwork as a blob and releases it on unmount', async () => {
  const get = vi.spyOn(mediaApi, 'getArtwork').mockResolvedValue({ data: new Blob(['image']) } as never)
  const view = render(<ShowArtwork id={12} alt="Movie" fallback={<span>No poster</span>} />)
  expect(await screen.findByAltText('Movie')).toHaveAttribute('src', 'blob:synthetic-poster')
  expect(get).toHaveBeenCalledWith(12, expect.any(AbortSignal))
  view.unmount()
  expect(revokeObjectURL).toHaveBeenCalledWith('blob:synthetic-poster')
})

it('keeps the fallback on an artwork failure', async () => {
  vi.spyOn(mediaApi, 'getArtwork').mockRejectedValue(new Error('Plex unavailable'))
  render(<ShowArtwork id={12} alt="Movie" fallback={<span>No poster</span>} />)
  await waitFor(() => expect(mediaApi.getArtwork).toHaveBeenCalled())
  expect(screen.getByText('No poster')).toBeVisible()
  expect(screen.queryByRole('img')).not.toBeInTheDocument()
})

it('aborts a pending request and ignores its late result', async () => {
  const response = deferred<Awaited<ReturnType<typeof mediaApi.getArtwork>>>()
  const get = vi.spyOn(mediaApi, 'getArtwork').mockReturnValue(response.promise)
  const view = render(<ShowArtwork id={12} alt="Movie" fallback={<span>No poster</span>} />)
  const signal = get.mock.calls[0][1]!
  view.unmount()
  expect(signal.aborted).toBe(true)
  response.resolve({ data: new Blob(['image']) } as never)
  await response.promise
  expect(createObjectURL).not.toHaveBeenCalled()
})

it('artwork requests use the current bearer session', async () => {
  const adapter = api.defaults.adapter
  localStorage.setItem('token', 'synthetic-session')
  api.defaults.adapter = async (config) => {
    expect(config.url).toBe('/api/media/shows/12/artwork')
    expect(config.headers.Authorization).toBe('Bearer synthetic-session')
    expect(config.responseType).toBe('blob')
    return { data: new Blob(['image']), status: 200, statusText: 'OK', headers: {}, config }
  }
  try { await mediaApi.getArtwork(12) } finally { api.defaults.adapter = adapter }
})
