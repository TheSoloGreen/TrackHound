import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { expect, it, vi } from 'vitest'
import PolicyEvaluation from '../components/PolicyEvaluation'
import { settingsApi } from '../api/client'
import { makeClient, renderWithClient } from './helpers'

const status = { policy_revision: 'a'.repeat(64), files_total: 8, files_current: 3,
  files_pending: 4, files_needing_scan: 1, latest_job: null }

it('shows policy freshness separately from missing analysis and queues read-only reevaluation', async () => {
  const client = makeClient()
  vi.spyOn(settingsApi, 'getEvaluation').mockResolvedValue({ data: status } as never)
  const start = vi.spyOn(settingsApi, 'reevaluate').mockResolvedValue({ data: { id: 5 } } as never)
  renderWithClient(<MemoryRouter><PolicyEvaluation /></MemoryRouter>, client)
  expect(await screen.findByText('3 current · 4 awaiting reevaluation · 1 need a physical scan')).toBeVisible()
  expect(screen.getByText(/No media probes, Plex requests, or media edits/)).toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: 'Reevaluate cached audio' }))
  await waitFor(() => expect(start).toHaveBeenCalledTimes(1))
})

it('links active jobs and preserves an actionable load error/retry', async () => {
  const read = vi.spyOn(settingsApi, 'getEvaluation').mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValue({ data: { ...status, latest_job: { id: 5, status: 'running' } } } as never)
  renderWithClient(<MemoryRouter><PolicyEvaluation /></MemoryRouter>)
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not load audio policy status')
  await userEvent.click(screen.getByRole('button', { name: 'Retry policy status' }))
  expect(await screen.findByRole('status')).toHaveTextContent('Job #5: running')
  expect(screen.getByRole('button', { name: 'Reevaluate cached audio' })).toBeDisabled()
  expect(screen.getByRole('link', { name: 'View policy job' })).toHaveAttribute('href', '/jobs')
  expect(read).toHaveBeenCalledTimes(2)
})
