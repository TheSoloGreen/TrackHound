import { screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { jobsApi, mediaApi, scanApi } from '../api/client'
import DashboardPage from '../pages/DashboardPage'
import JobsPage from '../pages/JobsPage'
import { formatServerDate, parseServerDate } from '../utils/dates'
import { renderWithClient, runningScan } from './helpers'

// A UTC-only CI runner would hide regressions that interpret naive dates locally.
beforeEach(() => vi.stubEnv('TZ', 'America/Chicago'))
afterEach(() => vi.unstubAllEnvs())

it.each(['2026-10-18T09:22:14.357968', '2026-10-18T09:22:14.357968Z',
  '2026-10-18T04:22:14.357968-05:00', '2026-10-18T11:22:14.357968+0200'])(
  'interprets %s as the same UTC instant', (value) => {
    expect(parseServerDate(value).toISOString()).toBe('2026-10-18T09:22:14.357Z')
    expect(formatServerDate(value)).toBe(new Date('2026-10-18T09:22:14.357Z').toLocaleString())
  })

it('renders the same completion time in Dashboard, scan summary, and Jobs', async () => {
  const timestamp = '2026-10-18T09:22:14.357968'
  const date = formatServerDate(timestamp)
  vi.spyOn(mediaApi, 'getStats').mockResolvedValue({ data: { last_scan: timestamp } } as never)
  vi.spyOn(scanApi, 'getStatus').mockResolvedValue({ data: { ...runningScan,
    is_running: false, outcome: 'completed', finished_at: timestamp } } as never)
  vi.spyOn(jobsApi, 'list').mockResolvedValue({ data: { items: [{ id: 1, kind: 'scan', status: 'completed',
    created_at: timestamp, finished_at: timestamp, progress: {}, result: {} }], total: 1 } } as never)
  renderWithClient(<MemoryRouter><DashboardPage /><JobsPage /></MemoryRouter>)
  expect(await screen.findByText(`Last scan: ${date}`)).toBeVisible()
  expect(await screen.findByText(`Finished ${date}`)).toBeVisible()
  expect(await screen.findByText(`Queued ${date} · Finished ${date}`)).toBeVisible()
})
