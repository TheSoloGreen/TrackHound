import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { expect, it, vi } from 'vitest'
import { jobsApi, mediaApi } from '../api/client'
import JobsPage from '../pages/JobsPage'
import FilesPage from '../pages/FilesPage'
import { makeClient, mediaFile, renderWithClient } from './helpers'
import type { Job } from '../types'

const job: Job = { id: 11, kind: 'rescan_file', status: 'queued', progress: {}, result: {}, error: null,
  cancel_requested: false, created_at: '2026-10-15T18:00:00', started_at: null, finished_at: null, target_file_id: 1 }

it('shows saved outcomes, review links and recovery paths without exposing raw payloads', async () => {
  vi.spyOn(jobsApi, 'list').mockResolvedValue({ data: { items: [
    { ...job, status: 'interrupted', finished_at: '2026-10-15T18:02:00', error: 'The application stopped. This edit was not retried.' },
    { ...job, id: 12, kind: 'remove_audio', status: 'completed', result: { backup_path: '/media/movie.mkv.bak' } },
  ], total: 2 } } as never)
  renderWithClient(<MemoryRouter><JobsPage /></MemoryRouter>)
  expect(await screen.findByRole('alert')).toHaveTextContent('not retried')
  expect(screen.getByText('Original backup: /media/movie.mkv.bak')).toBeVisible()
  expect(screen.getAllByRole('link', { name: 'Review file #1' })[0]).toHaveAttribute('href', '/files?file_id=1&expanded=1')
  expect(screen.queryByRole('button', { name: /Cancel job/ })).not.toBeInTheDocument()
})

it('cancels queued work but disables mid-write cancellation and shows failures', async () => {
  const client = makeClient()
  vi.spyOn(jobsApi, 'list').mockResolvedValue({ data: { items: [job,
    { ...job, id: 12, kind: 'remove_audio', status: 'running' },
  ], total: 2 } } as never)
  const cancel = vi.spyOn(jobsApi, 'cancel').mockRejectedValue({ isAxiosError: true, response: { data: { detail: 'This job already finished.' } } })
  renderWithClient(<MemoryRouter><JobsPage /></MemoryRouter>, client)
  const button = await screen.findByRole('button', { name: 'Cancel job #11' })
  expect(screen.queryByRole('button', { name: 'Cancel job #12' })).not.toBeInTheDocument()
  expect(screen.getByText(/Cancellation is disabled/)).toBeVisible()
  await userEvent.click(button)
  expect(cancel).toHaveBeenCalledWith(11, expect.anything())
  expect(await screen.findByRole('alert')).toHaveTextContent('This job already finished.')
})

it('refreshes every library view when a background job finishes', async () => {
  const client = makeClient()
  const keys = [['stats'], ['files'], ['show', '1'], ['season', '1', 1], ['scanLocations']]
  keys.forEach((key) => client.setQueryData(key, { before: true }))
  vi.spyOn(jobsApi, 'list').mockResolvedValue({ data: { items: [{ ...job, status: 'completed', finished_at: '2026-10-15T18:02:00' }], total: 1 } } as never)
  renderWithClient(<MemoryRouter><JobsPage /></MemoryRouter>, client)
  await screen.findByText(/#11 · File rescan · completed/)
  await waitFor(() => keys.forEach((key) => expect(client.getQueryState(key)?.isInvalidated).toBe(true)))
})

it('refreshes on completion even when active jobs fill the first page', async () => {
  const client = makeClient()
  client.setQueryData(['stats'], { before: true })
  vi.spyOn(jobsApi, 'list').mockResolvedValue({ data: { items: [job], total: 101, latest_finished_at: '2026-10-15T18:02:00' } } as never)
  renderWithClient(<MemoryRouter><JobsPage /></MemoryRouter>, client)
  await screen.findByRole('button', { name: 'Cancel job #11' })
  await waitFor(() => expect(client.getQueryState(['stats'])?.isInvalidated).toBe(true))
})

it('acknowledges a queued file action and links to durable progress instead of claiming completion', async () => {
  vi.spyOn(mediaApi, 'getFiles').mockResolvedValue({ data: { items: [mediaFile], total: 1, pages: 1 } } as never)
  vi.spyOn(mediaApi, 'getAudioTrackRemovalPlan').mockResolvedValue({ data: { file_id: 1, last_scanned: mediaFile.last_scanned, keep_track_indices: [1, 2, 3] } } as never)
  vi.spyOn(mediaApi, 'rescanFile').mockResolvedValue({ data: job } as never)
  renderWithClient(<MemoryRouter initialEntries={['/files?expanded=1']}><FilesPage /></MemoryRouter>)
  await userEvent.click(await screen.findByRole('button', { name: /Rescan File/i }))
  expect(await screen.findByText(/Job #11 queued/)).toBeVisible()
  expect(screen.getByRole('link', { name: 'View progress and results in Jobs' })).toHaveAttribute('href', '/jobs')
})
