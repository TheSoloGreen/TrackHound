import { act, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import { mediaApi, scanApi } from '../api/client'
import DashboardPage from '../pages/DashboardPage'
import FilesPage from '../pages/FilesPage'
import ShowDetailPage from '../pages/ShowDetailPage'
import ShowsPage from '../pages/ShowsPage'
import type { ShowDetail } from '../types'
import { makeClient, mediaFile, renderWithClient, runningScan } from './helpers'

const apiFailure = (status: number, detail: string) => ({
  isAxiosError: true,
  response: { status, data: { detail } },
})

const movie: ShowDetail = {
  id: 1,
  title: 'A movie',
  media_type: 'movie',
  base_media_type: 'movie',
  is_anime: false,
  anime_source: null,
  thumb_url: null,
  season_count: 0,
  episode_count: 0,
  file_count: 1,
  issues_count: 0,
  created_at: '',
  updated_at: '',
  media_files: [mediaFile],
  seasons: [],
}

const series: ShowDetail = {
  ...movie,
  title: 'A series',
  media_type: 'tv',
  base_media_type: 'tv',
  season_count: 1,
  episode_count: 1,
  media_files: [],
  seasons: [{ id: 3, season_number: 1, episode_count: 1, issues_count: 0 }],
}

beforeEach(() => {
  vi.restoreAllMocks()
})

it('surfaces a reset conflict and preserves the cached file list', async () => {
  vi.spyOn(mediaApi, 'getFiles').mockResolvedValue({ data: { items: [mediaFile], total: 1, pages: 1 } } as never)
  vi.spyOn(mediaApi, 'resetFiles').mockRejectedValue(apiFailure(409, 'A scan is currently running'))
  vi.spyOn(window, 'confirm').mockReturnValue(true)

  renderWithClient(<MemoryRouter><FilesPage /></MemoryRouter>)
  expect(await screen.findByText('movie.mkv')).toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: 'Reset Scanned Files' }))

  expect(await screen.findByText('A scan is currently running')).toBeVisible()
  expect(screen.getByText('movie.mkv')).toBeVisible()
})

it('surfaces backend conflict details for file and title rescans', async () => {
  vi.spyOn(mediaApi, 'getShow').mockResolvedValue({ data: movie } as never)
  vi.spyOn(mediaApi, 'rescanFile').mockRejectedValue(apiFailure(409, 'File changed since it was loaded'))
  vi.spyOn(mediaApi, 'rescanShow').mockRejectedValue(apiFailure(409, 'Title scan already queued'))

  renderWithClient(<MemoryRouter initialEntries={['/library/1']}><Routes>
    <Route path="/library/:id" element={<ShowDetailPage />} />
  </Routes></MemoryRouter>)

  await userEvent.click(await screen.findByRole('button', { name: 'Rescan' }))
  expect(await screen.findByText('File changed since it was loaded')).toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: 'Rescan Series' }))
  expect(await screen.findByText('Title scan already queued')).toBeVisible()
})

it('distinguishes a failed title load from not found and retries successfully', async () => {
  vi.spyOn(mediaApi, 'getShow')
    .mockRejectedValueOnce(apiFailure(500, 'Database temporarily unavailable'))
    .mockResolvedValue({ data: movie } as never)

  renderWithClient(<MemoryRouter initialEntries={['/library/1']}><Routes>
    <Route path="/library/:id" element={<ShowDetailPage />} />
  </Routes></MemoryRouter>)

  expect(await screen.findByRole('alert')).toHaveTextContent('Database temporarily unavailable')
  expect(screen.queryByText('Title not found')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Retry title' }))
  expect(await screen.findByRole('heading', { name: 'A movie' })).toBeVisible()
})

it('keeps the genuine title not-found state for a 404', async () => {
  vi.spyOn(mediaApi, 'getShow').mockRejectedValue(apiFailure(404, 'Show not found'))

  renderWithClient(<MemoryRouter initialEntries={['/library/404']}><Routes>
    <Route path="/library/:id" element={<ShowDetailPage />} />
  </Routes></MemoryRouter>)

  expect(await screen.findByText('Title not found')).toBeVisible()
  expect(screen.queryByRole('button', { name: 'Retry title' })).not.toBeInTheDocument()
})

it('replaces a cached title with not found when a refetch returns 404', async () => {
  const client = makeClient()
  vi.spyOn(mediaApi, 'getShow')
    .mockResolvedValueOnce({ data: movie } as never)
    .mockRejectedValueOnce(apiFailure(404, 'Show not found'))

  renderWithClient(<MemoryRouter initialEntries={['/library/1']}><Routes>
    <Route path="/library/:id" element={<ShowDetailPage />} />
  </Routes></MemoryRouter>, client)

  expect(await screen.findByRole('heading', { name: 'A movie' })).toBeVisible()
  await act(async () => { await client.refetchQueries({ queryKey: ['show', '1'], exact: true }) })

  expect(await screen.findByText('Title not found')).toBeVisible()
  expect(screen.queryByRole('heading', { name: 'A movie' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Rescan Series' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Mark as Anime' })).not.toBeInTheDocument()
})

it('shows a failed season load and retries it instead of prompting to select a season', async () => {
  vi.spyOn(mediaApi, 'getShow').mockResolvedValue({ data: series } as never)
  vi.spyOn(mediaApi, 'getSeason')
    .mockRejectedValueOnce(apiFailure(500, 'Season service unavailable'))
    .mockResolvedValue({ data: { ...series.seasons[0], media_files: [mediaFile] } } as never)

  renderWithClient(<MemoryRouter initialEntries={['/library/1?season=1']}><Routes>
    <Route path="/library/:id" element={<ShowDetailPage />} />
  </Routes></MemoryRouter>)

  expect(await screen.findByRole('alert')).toHaveTextContent('Season service unavailable')
  expect(screen.queryByText('Click a season to view episodes')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Retry season' }))
  expect(await screen.findByText('movie.mkv')).toBeVisible()
})

it('disables scan actions when status fails and recovers to the active action on retry', async () => {
  vi.spyOn(mediaApi, 'getStats').mockResolvedValue({ data: {} } as never)
  vi.spyOn(scanApi, 'getStatus')
    .mockRejectedValueOnce(apiFailure(500, 'Cannot determine scan status'))
    .mockResolvedValue({ data: runningScan } as never)

  renderWithClient(<MemoryRouter><DashboardPage /></MemoryRouter>)

  expect(await screen.findByRole('alert')).toHaveTextContent('Cannot determine scan status')
  expect(screen.getByRole('button', { name: 'Start Scan' })).toBeDisabled()
  await userEvent.click(screen.getByRole('button', { name: 'Retry scan status' }))
  expect(await screen.findByRole('button', { name: 'Cancel Scan' })).toBeEnabled()
})

it('omits malformed library filters and defaults an invalid page to one', async () => {
  const getShows = vi.spyOn(mediaApi, 'getShows').mockResolvedValue({ data: { items: [], total: 0, pages: 1 } } as never)

  renderWithClient(<MemoryRouter initialEntries={['/library?page=1.5&has_issues=yes&media_type=documentary']}><ShowsPage /></MemoryRouter>)

  await screen.findByText('No titles found')
  expect(getShows).toHaveBeenCalledWith(expect.objectContaining({
    page: 1,
    has_issues: undefined,
    media_type: undefined,
  }))
})
