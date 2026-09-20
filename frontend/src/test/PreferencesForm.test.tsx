import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { settingsApi } from '../api/client'
import PreferencesForm from '../components/PreferencesForm'
import { deferred, makeClient, renderWithClient, settings } from './helpers'

describe('preference saves', () => {
  it('keeps rapid typing local, serializes saves, and retains edits made during a delayed response', async () => {
    const first = deferred<Awaited<ReturnType<typeof settingsApi.update>>>()
    const update = vi.spyOn(settingsApi, 'update').mockReturnValueOnce(first.promise)
      .mockImplementation(async (data) => ({ data }) as Awaited<ReturnType<typeof settingsApi.update>>)
    const user = userEvent.setup()
    const client = makeClient()
    client.setQueryData(['settings'], settings)
    renderWithClient(<PreferencesForm initialSettings={settings} />, client)
    const keywords = screen.getByLabelText('Anime folder keywords')
    await user.clear(keywords)
    await user.type(keywords, 'anime, animation, ')
    await user.click(screen.getByRole('checkbox', { name: /Require English audio/ }))
    await user.click(screen.getByRole('checkbox', { name: /Require Japanese audio/ }))
    expect(keywords).toHaveValue('anime, animation, ')
    expect(update).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Save preferences' }))
    await waitFor(() => expect(update).toHaveBeenCalledTimes(1))
    const submitted = update.mock.calls[0][0]
    expect(submitted).toMatchObject({ audio_preferences: { require_english_non_anime: false, require_japanese_anime: false } })
    await user.type(keywords, 'newer draft')
    fireEvent.submit(screen.getByRole('form', { name: 'Preferences' }))
    expect(screen.getByRole('button', { name: 'Saving…' })).toBeDisabled()
    expect(update).toHaveBeenCalledTimes(1)
    await act(async () => first.resolve({ data: submitted } as Awaited<ReturnType<typeof settingsApi.update>>))
    expect(keywords).toHaveValue('anime, animation, newer draft')
    expect(client.getQueryData(['settings'])).toEqual(submitted)
    await user.click(screen.getByRole('button', { name: 'Save preferences' }))
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Preferences saved'))
    expect(update).toHaveBeenCalledTimes(2)
    expect(update.mock.calls[1][0]).toMatchObject({ anime_detection: { anime_folder_keywords: ['anime', 'animation', 'newer draft'] } })
  })

  it('ignores an older query result after a newer save and retains failed edits for retry', async () => {
    const client = makeClient()
    const oldRead = deferred<typeof settings>()
    const update = vi.spyOn(settingsApi, 'update').mockRejectedValueOnce(new Error('offline'))
      .mockImplementation(async (data) => ({ data }) as Awaited<ReturnType<typeof settingsApi.update>>)
    client.setQueryData(['settings'], settings)
    // Simulate a GET already in flight when the user begins saving.
    const oldRequest = client.fetchQuery({ queryKey: ['settings'], queryFn: () => oldRead.promise, staleTime: 0 }).catch(() => {})
    const user = userEvent.setup()
    renderWithClient(<PreferencesForm initialSettings={settings} />, client)
    const extensions = screen.getByLabelText('File extensions')
    await user.type(extensions, ', .mp4')
    await user.click(screen.getByRole('button', { name: 'Save preferences' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Your edits have been kept')
    expect(extensions).toHaveValue('.mkv, .mp4')
    await user.click(screen.getByRole('button', { name: 'Save preferences' }))
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Preferences saved'))
    await act(async () => { oldRead.resolve(settings); await oldRequest })
    expect(client.getQueryData(['settings'])).toMatchObject({ file_extensions: ['.mkv', '.mp4'] })
    expect(update).toHaveBeenCalledTimes(2)
  })
})
