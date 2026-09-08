import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { scanApi } from '../api/client'
import { useScanStatus } from '../hooks/useScanStatus'
import ScanSummary from '../components/ScanSummary'
import DashboardPage from '../pages/DashboardPage'
import { mediaApi } from '../api/client'
import { makeClient, renderWithClient, runningScan } from './helpers'
import type { ScanStatus } from '../types'

function Monitor() { const { data } = useScanStatus(); return <ScanSummary status={data} /> }

it.each(['completed', 'completed_with_errors', 'cancelled', 'failed'] as const)('refreshes all cached results once on %s and keeps the completion visible', async (outcome) => {
  const client = makeClient()
  vi.spyOn(scanApi, 'getStatus').mockResolvedValue({ data: runningScan } as Awaited<ReturnType<typeof scanApi.getStatus>>)
  const keys = [['stats'], ['shows', 'anime', 2], ['files', 3], ['file', 1], ['show', '1'], ['season', '1', 0], ['scanLocations'], ['trackRemovalPlan', 1]]
  keys.forEach((key) => client.setQueryData(key, { before: true }))
  client.setQueryData(['scanStatus'], runningScan)
  const invalidate = vi.spyOn(client, 'invalidateQueries')
  const view = renderWithClient(<Monitor />, client)
  const finished: ScanStatus = { ...runningScan, is_running: false, outcome, files_scanned: 2, finished_at: '2026-09-08T16:01:00Z' }
  await act(async () => { client.setQueryData(['scanStatus'], finished) })
  await waitFor(() => expect(client.getQueryState(['stats'])?.isInvalidated).toBe(true))
  keys.forEach((key) => expect(client.getQueryState(key)?.isInvalidated).toBe(true))
  const count = invalidate.mock.calls.length
  await act(async () => { client.setQueryData(['scanStatus'], { ...finished }) })
  view.unmount()
  renderWithClient(<Monitor />, client)
  expect(invalidate).toHaveBeenCalledTimes(count)
  expect(screen.getByRole('status')).toHaveTextContent(outcome === 'completed_with_errors' ? 'Scan completed with errors' : `Scan ${outcome}`)
})

it('shows bounded, expandable errors and Plex warnings after completion', async () => {
  renderWithClient(<ScanSummary status={{ ...runningScan, outcome: 'completed_with_errors', is_running: false,
    finished_at: '2026-09-08T16:01:00Z', error_count: 64, warning_count: 1,
    errors: Array.from({ length: 64 }, (_, i) => `Unreadable file ${i}`), warnings: ['Plex unavailable; local scanning continues.'] }} />)
  expect(screen.getByRole('status')).toHaveTextContent('Scan completed with errors')
  await userEvent.click(screen.getByText('64 scan errors'))
  expect(within(screen.getByRole('list', { name: 'Scan errors' })).getAllByRole('listitem')).toHaveLength(50)
  expect(screen.getByText('Showing the first 50 errors.')).toBeVisible()
  expect(screen.queryByText('Unreadable file 50')).not.toBeInTheDocument()
  await userEvent.click(screen.getByText('1 scan warnings'))
  expect(screen.getByText('Plex unavailable; local scanning continues.')).toBeVisible()
})

it('lets the user request a full scan of unchanged files', async () => {
  vi.spyOn(mediaApi, 'getStats').mockResolvedValue({ data: {} } as Awaited<ReturnType<typeof mediaApi.getStats>>)
  vi.spyOn(scanApi, 'getStatus').mockResolvedValue({ data: { ...runningScan, is_running: false, outcome: 'idle' } } as Awaited<ReturnType<typeof scanApi.getStatus>>)
  const start = vi.spyOn(scanApi, 'start').mockResolvedValue({ data: runningScan } as Awaited<ReturnType<typeof scanApi.start>>)
  renderWithClient(<DashboardPage />)
  await userEvent.click(await screen.findByRole('checkbox', { name: 'Full scan' }))
  await userEvent.click(screen.getByRole('button', { name: 'Start Scan' }))
  await waitFor(() => expect(start).toHaveBeenCalledWith({ incremental: false }))
})
