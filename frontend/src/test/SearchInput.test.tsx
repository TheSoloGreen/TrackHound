import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BrowserRouter, useNavigate } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import { mediaApi } from '../api/client'
import ShowsPage from '../pages/ShowsPage'
import FilesPage from '../pages/FilesPage'
import { renderWithClient } from './helpers'

beforeEach(() => {
  window.history.replaceState({}, '', '/')
  vi.spyOn(mediaApi, 'getShows').mockResolvedValue({ data: { items: [], total: 0, pages: 1 } } as never)
  vi.spyOn(mediaApi, 'getFiles').mockResolvedValue({ data: { items: [], total: 0, pages: 1 } } as never)
})

function Navigation() {
  const navigate = useNavigate()
  return <button onClick={() => navigate('?search=restored')}>Restore a saved search</button>
}

it.each(['library', 'files'])('retains burst typing in the %s search while URL navigation is deferred', async (page) => {
  renderWithClient(<BrowserRouter>{page === 'library' ? <ShowsPage /> : <FilesPage />}</BrowserRouter>)
  const input = screen.getByPlaceholderText(page === 'library' ? 'Search library...' : 'Search files...') as HTMLInputElement
  // BrowserRouter transitions are deferred; each next event starts from the
  // actual displayed value, as rapid native typing does, not a hard-coded string.
  act(() => {
    for (const character of '11eyes') fireEvent.change(input, { target: { value: input.value + character } })
  })
  expect(input).toHaveValue('11eyes')
  await waitFor(() => expect(new URLSearchParams(window.location.search).get('search')).toBe('11eyes'))
  const api = page === 'library' ? mediaApi.getShows : mediaApi.getFiles
  await waitFor(() => expect(api).toHaveBeenLastCalledWith(expect.objectContaining({ search: '11eyes', page: 1 })))
})

it.each(['library', 'files'])('updates the %s input after navigation and restores it with Back', async (page) => {
  window.history.replaceState({}, '', '/?search=initial')
  renderWithClient(<BrowserRouter><Navigation />{page === 'library' ? <ShowsPage /> : <FilesPage />}</BrowserRouter>)
  const input = screen.getByPlaceholderText(page === 'library' ? 'Search library...' : 'Search files...')
  expect(input).toHaveValue('initial')
  await userEvent.click(screen.getByRole('button', { name: 'Restore a saved search' }))
  await waitFor(() => expect(input).toHaveValue('restored'))
  act(() => window.history.back())
  await waitFor(() => expect(input).toHaveValue('initial'))
  act(() => window.history.forward())
  await waitFor(() => expect(input).toHaveValue('restored'))
})

it.each(['library', 'files'])('pastes complete %s searches while preserving filters and resetting the page', async (page) => {
  window.history.replaceState({}, '', '/?media_type=anime&has_issues=true&page=3')
  renderWithClient(<BrowserRouter>{page === 'library' ? <ShowsPage /> : <FilesPage />}</BrowserRouter>)
  const user = userEvent.setup()
  const input = screen.getByPlaceholderText(page === 'library' ? 'Search library...' : 'Search files...')
  await user.click(input)
  await user.paste('日本語 11eyes')
  expect(input).toHaveValue('日本語 11eyes')
  await waitFor(() => {
    const params = new URLSearchParams(window.location.search)
    expect(params.get('search')).toBe('日本語 11eyes')
    expect(params.get('media_type')).toBe('anime')
    expect(params.get('has_issues')).toBe('true')
    expect(params.has('page')).toBe(false)
  })
  if (page === 'files') {
    await user.click(screen.getByRole('button', { name: 'Clear filters' }))
    await waitFor(() => expect(input).toHaveValue(''))
  }
})
