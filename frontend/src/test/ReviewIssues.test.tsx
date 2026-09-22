import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Link, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import axe from 'axe-core'
import { mediaApi, scanApi, settingsApi } from '../api/client'
import { apiError } from '../api/errors'
import FilesPage from '../pages/FilesPage'
import SettingsPage from '../pages/SettingsPage'
import { mediaFile, renderWithClient, settings } from './helpers'

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(mediaApi, 'getFiles').mockResolvedValue({ data: { items: [mediaFile], total: 1, pages: 1 } } as never)
  vi.spyOn(mediaApi, 'getAudioTrackRemovalPlan').mockResolvedValue({ data: { file_id: 1, last_scanned: mediaFile.last_scanned, keep_track_indices: [1] } } as never)
})

function Location() {
  const location = useLocation()
  const navigate = useNavigate()
  return <><output aria-label="Current URL">{location.pathname + location.search}</output><button onClick={() => navigate(-1)}>Browser back</button></>
}

it('preserves URL filters through Back and exposes keyboard-operable file details', async () => {
  const user = userEvent.setup()
  const view = renderWithClient(<MemoryRouter initialEntries={['/files?search=movie&issue_category=unknown_language&media_type=tv']}>
    <Location /><Link to="/settings">Settings</Link><Routes><Route path="/files" element={<FilesPage />} /><Route path="/settings" element={<p>Other page</p>} /></Routes>
  </MemoryRouter>)
  const expansion = await screen.findByRole('button', { name: 'Audio details for movie.mkv' })
  expect(screen.getByRole('textbox', { name: 'Search files' })).toHaveValue('movie')
  expect(mediaApi.getFiles).toHaveBeenLastCalledWith(expect.objectContaining({ search: 'movie', issue_category: 'unknown_language', media_type: 'tv' }))
  expansion.focus()
  await user.keyboard('{Enter}')
  expect(expansion).toHaveAttribute('aria-expanded', 'true')
  expect(await screen.findByRole('button', { name: 'Rescan File' })).toBeVisible()
  expect(document.getElementById(expansion.getAttribute('aria-controls')!)).toBeVisible()
  const result = await axe.run(view.container, { rules: { 'color-contrast': { enabled: false } } })
  expect(result.violations.map((violation) => violation.id)).toEqual([])
  await user.click(screen.getByRole('link', { name: 'Settings' }))
  await user.click(screen.getByRole('button', { name: 'Browser back' }))
  expect(await screen.findByRole('textbox', { name: 'Search files' })).toHaveValue('movie')
  expect(screen.getByRole('button', { name: 'Audio details for movie.mkv' })).toHaveAttribute('aria-expanded', 'true')
})

it('opens a linked file and retains its title/season return path', async () => {
  renderWithClient(<MemoryRouter initialEntries={['/files?file_id=1&expanded=1&return_to=%2Flibrary%2F3%3Fseason%3D2']}><FilesPage /></MemoryRouter>)
  expect(await screen.findByRole('button', { name: 'Rescan File' })).toBeVisible()
  expect(mediaApi.getFiles).toHaveBeenCalledWith(expect.objectContaining({ file_id: 1, page: 1 }))
  expect(screen.getByRole('link', { name: 'Back to title and season' })).toHaveAttribute('href', '/library/3?season=2')
})

it('ignores malformed page/filter values and never follows external return links', async () => {
  renderWithClient(<MemoryRouter initialEntries={['/files?page=NaN&file_id=-2&issue_category=bad&return_to=https://example.org']}><FilesPage /></MemoryRouter>)
  await screen.findByRole('button', { name: 'Audio details for movie.mkv' })
  expect(mediaApi.getFiles).toHaveBeenCalledWith(expect.objectContaining({ page: 1, file_id: undefined, issue_category: undefined }))
  expect(screen.queryByRole('link', { name: 'Back to title and season' })).not.toBeInTheDocument()
})

function setupSettings() {
  vi.spyOn(settingsApi, 'get').mockResolvedValue({ data: settings } as never)
  vi.spyOn(mediaApi, 'getCapabilities').mockResolvedValue({ data: mediaFile.edit_capabilities } as never)
  vi.spyOn(scanApi, 'getLocations').mockResolvedValue({ data: [{ id: 1, label: 'Movies', path: '/media/movies', media_type: 'movie', enabled: true, file_count: 1 }] } as never)
  vi.spyOn(scanApi, 'browse').mockResolvedValue({ data: { current_path: '/media', directories: [] } } as never)
}

const error = (detail: unknown) => ({ isAxiosError: true, response: { data: { detail } } })

it('keeps duplicate-path drafts and recovers on successful add retry', async () => {
  setupSettings()
  const create = vi.spyOn(scanApi, 'createLocation').mockRejectedValueOnce(error('Scan location with this path already exists')).mockResolvedValue({ data: {} } as never)
  renderWithClient(<MemoryRouter><SettingsPage /></MemoryRouter>)
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Add Scan Location' }))
  await user.click(await screen.findByRole('button', { name: 'Select This Folder' }))
  await user.clear(screen.getByRole('textbox', { name: 'Location label' }))
  await user.type(screen.getByRole('textbox', { name: 'Location label' }), 'Draft label')
  await user.click(screen.getByRole('button', { name: 'Add' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('already exists')
  expect(screen.getByRole('textbox', { name: 'Location label' })).toHaveValue('Draft label')
  await user.click(screen.getByRole('button', { name: 'Add' }))
  await waitFor(() => expect(create).toHaveBeenCalledTimes(2))
  expect(await screen.findByRole('button', { name: 'Add Scan Location' })).toBeVisible()
})

it('shows failed location loads separately from empty results and retries', async () => {
  setupSettings()
  vi.mocked(scanApi.getLocations).mockRejectedValueOnce(error('Service unavailable'))
  renderWithClient(<MemoryRouter><SettingsPage /></MemoryRouter>)
  expect(await screen.findByRole('alert')).toHaveTextContent('Service unavailable')
  expect(screen.queryByText('No scan locations configured')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Retry scan locations' }))
  expect(await screen.findByRole('button', { name: 'Delete Movies' })).toBeVisible()
})

it('reports failed toggles and deletes without pretending they succeeded', async () => {
  setupSettings()
  vi.spyOn(scanApi, 'updateLocation').mockRejectedValue(error('Permission denied'))
  vi.spyOn(scanApi, 'deleteLocation').mockRejectedValue(error('Cannot delete location'))
  renderWithClient(<MemoryRouter><SettingsPage /></MemoryRouter>)
  await userEvent.click(await screen.findByRole('checkbox', { name: 'Enable Movies' }))
  expect(await screen.findByText('Permission denied')).toBeVisible()
  expect(screen.getByRole('checkbox', { name: 'Enable Movies' })).toBeChecked()
  await userEvent.click(screen.getByRole('button', { name: 'Delete Movies' }))
  expect(await screen.findByText('Cannot delete location')).toBeVisible()
  expect(screen.getByRole('checkbox', { name: 'Enable Movies' })).toBeVisible()
})

it('presents structured validation messages rather than a generic error', () => {
  expect(apiError({ isAxiosError: true, response: { data: { detail: 'Invalid request input.', errors: ['path: Invalid path'] } } }, 'fallback')).toBe('path: Invalid path')
  expect(apiError(error({ errors: [{ msg: 'Choose a media type' }] }), 'fallback')).toBe('Choose a media type')
})

it('saves a user language note separately from track metadata', async () => {
  const save = vi.spyOn(mediaApi, 'updateLanguageReview').mockResolvedValue({ data: {} } as never)
  renderWithClient(<MemoryRouter initialEntries={['/files?expanded=1']}><FilesPage /></MemoryRouter>)
  const input = await screen.findByRole('textbox', { name: 'Your language review note' })
  await userEvent.type(input, 'Verified by listening: English')
  await userEvent.click(screen.getByRole('button', { name: 'Save review note' }))
  await waitFor(() => expect(save).toHaveBeenCalledWith(1, 'Verified by listening: English'))
  expect(await screen.findByText('Review note saved.')).toBeVisible()
})
