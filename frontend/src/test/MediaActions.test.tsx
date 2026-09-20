import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { expect, it, vi } from 'vitest'
import { mediaApi } from '../api/client'
import ShowDetailPage from '../pages/ShowDetailPage'
import FilesPage from '../pages/FilesPage'
import { makeClient, mediaFile, renderWithClient } from './helpers'
import type { ShowDetail } from '../types'

it.each(['tv', 'movie'] as const)('marks and unmarks %s consistently and refreshes aggregates', async (base) => {
  const client = makeClient()
  const user = userEvent.setup()
  let show: ShowDetail = { id: 1, title: 'A title', media_type: base, base_media_type: base,
    is_anime: false, anime_source: null, thumb_url: null, season_count: 1, episode_count: 1,
    file_count: 1, issues_count: 0, created_at: '', updated_at: '', media_files: [mediaFile],
    seasons: [{ id: 1, season_number: 0, episode_count: 1, issues_count: 0 }] }
  vi.spyOn(mediaApi, 'getShow').mockImplementation(async () => ({ data: show }) as Awaited<ReturnType<typeof mediaApi.getShow>>)
  const update = vi.spyOn(mediaApi, 'updateShow').mockImplementation(async (_id, data) => {
    show = { ...show, is_anime: !!data.is_anime, media_type: data.is_anime ? 'anime' : base,
      anime_source: 'manual', issues_count: data.is_anime ? 1 : 0 }
    return { data: show } as Awaited<ReturnType<typeof mediaApi.updateShow>>
  })
  vi.spyOn(mediaApi, 'getSeason').mockResolvedValue({ data: { ...show.seasons[0], media_files: [mediaFile] } } as Awaited<ReturnType<typeof mediaApi.getSeason>>)
  const keys = [['stats'], ['shows', 'anime'], ['files'], ['season', '1', 0], ['scanLocations']]
  keys.forEach((key) => client.setQueryData(key, { before: true }))
  renderWithClient(<MemoryRouter initialEntries={['/library/1']}><Routes>
    <Route path="/library/:id" element={<ShowDetailPage />} />
  </Routes></MemoryRouter>, client)
  await user.click(await screen.findByRole('button', { name: 'Mark as Anime' }))
  expect(await screen.findByText('Anime', { selector: 'span' })).toBeVisible()
  expect(screen.getByText('• 1 issue')).toBeVisible()
  keys.forEach((key) => expect(client.getQueryState(key)?.isInvalidated).toBe(true))
  if (base === 'movie') {
    expect(screen.getByText('movie.mkv')).toBeVisible()
    expect(screen.queryByRole('heading', { name: 'Seasons' })).not.toBeInTheDocument()
  }
  await waitFor(() => expect(screen.getByRole('button', { name: 'Unmark as Anime' })).toBeEnabled())
  await user.click(screen.getByRole('button', { name: 'Unmark as Anime' }))
  expect(await screen.findByText(base === 'movie' ? 'Movie' : 'TV Show', { selector: 'span' })).toBeVisible()
  expect(screen.queryByText('• 1 issue')).not.toBeInTheDocument()
  expect(update).toHaveBeenCalledTimes(2)
})

it('uses the saved removal plan and sends an explicit manual override with an exact confirmation', async () => {
  const client = makeClient()
  const user = userEvent.setup()
  vi.spyOn(mediaApi, 'getFiles').mockResolvedValue({ data: { items: [mediaFile], page: 1, pages: 1, total: 1, page_size: 25 } } as Awaited<ReturnType<typeof mediaApi.getFiles>>)
  // The backend normalizes Japanese raw codes and missing/undefined languages.
  vi.spyOn(mediaApi, 'getAudioTrackRemovalPlan').mockResolvedValue({ data: {
    file_id: 1, last_scanned: mediaFile.last_scanned, keep_track_indices: [2, 3],
  } } as Awaited<ReturnType<typeof mediaApi.getAudioTrackRemovalPlan>>)
  const remove = vi.spyOn(mediaApi, 'removeAudioTracks').mockResolvedValue({ data: {} } as Awaited<ReturnType<typeof mediaApi.removeAudioTracks>>)
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
  const keys = [['stats'], ['shows'], ['show', '1'], ['season', '1', 1], ['file', 1], ['scanLocations']]
  keys.forEach((key) => client.setQueryData(key, { before: true }))
  renderWithClient(<FilesPage />, client)
  await user.click(await screen.findByText('movie.mkv'))
  const english = screen.getByRole('checkbox', { name: 'Keep #1 EN' })
  const japanese = screen.getByRole('checkbox', { name: 'Keep #2 JA' })
  const undefinedLanguage = screen.getByRole('checkbox', { name: 'Keep #3 UND' })
  await waitFor(() => expect(japanese).toBeChecked())
  expect(english).not.toBeChecked()
  expect(undefinedLanguage).toBeChecked()
  await user.click(english)
  await user.click(japanese)
  await user.click(screen.getByRole('button', { name: 'Remove Unchecked Tracks' }))
  expect(confirm.mock.calls[0][0]).toContain('Keep: #1 EN, #3 UND\nRemove: #2 JA')
  await waitFor(() => expect(remove).toHaveBeenCalledWith(1, {
    keep_track_indices: [1, 3], keep_backup: true, expected_last_scanned: mediaFile.last_scanned,
  }))
  await waitFor(() => expect(client.getQueryState(['stats'])?.isInvalidated).toBe(true))
  keys.forEach((key) => expect(client.getQueryState(key)?.isInvalidated).toBe(true))
})

it('refreshes detail and location counts after a library reset', async () => {
  const client = makeClient()
  vi.spyOn(mediaApi, 'getFiles').mockResolvedValue({ data: { items: [], page: 1, pages: 1, total: 0 } } as Awaited<ReturnType<typeof mediaApi.getFiles>>)
  const reset = vi.spyOn(mediaApi, 'resetFiles').mockResolvedValue({ data: {} } as Awaited<ReturnType<typeof mediaApi.resetFiles>>)
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  const keys = [['stats'], ['shows'], ['show', '1'], ['season', '1', 1], ['file', 1], ['scanLocations']]
  keys.forEach((key) => client.setQueryData(key, { before: true }))
  renderWithClient(<FilesPage />, client)
  await userEvent.click(await screen.findByRole('button', { name: /Reset Scanned Files/i }))
  await waitFor(() => expect(reset).toHaveBeenCalledTimes(1))
  await waitFor(() => expect(client.getQueryState(['scanLocations'])?.isInvalidated).toBe(true))
  keys.forEach((key) => expect(client.getQueryState(key)?.isInvalidated).toBe(true))
})
