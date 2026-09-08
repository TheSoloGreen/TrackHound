import { useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import { settingsApi } from '../api/client'
import type { UserSettings, MediaEditCapabilities } from '../types'

const splitList = (text: string) => text.split(',').map((value) => value.trim()).filter(Boolean)

export default function PreferencesForm({ initialSettings, editCapabilities }: {
  initialSettings: UserSettings
  editCapabilities?: MediaEditCapabilities
}) {
  const queryClient = useQueryClient()
  const [settings, setSettings] = useState(initialSettings)
  const [keywords, setKeywords] = useState(initialSettings.anime_detection.anime_folder_keywords.join(', '))
  const [extensions, setExtensions] = useState(initialSettings.file_extensions.join(', '))
  const revision = useRef(0)
  const inFlight = useRef(false)
  const [savedRevision, setSavedRevision] = useState(0)
  const dirty = revision.current !== savedRevision

  const editSettings = (changes: Partial<UserSettings>) => {
    revision.current++
    setSettings((previous) => ({ ...previous, ...changes }))
  }
  const save = useMutation({
    mutationFn: async (submission: { settings: UserSettings; revision: number }) => {
      await queryClient.cancelQueries({ queryKey: ['settings'] })
      return (await settingsApi.update(submission.settings)).data as UserSettings
    },
    onSuccess: (response, submission) => {
      queryClient.setQueryData(['settings'], response)
      setSavedRevision(submission.revision)
      // A response may normalize saved values, but cannot replace newer local edits.
      if (revision.current === submission.revision) {
        setSettings(response)
        setKeywords(response.anime_detection.anime_folder_keywords.join(', '))
        setExtensions(response.file_extensions.join(', '))
      }
      return queryClient.invalidateQueries({ queryKey: ['trackRemovalPlan'] })
    },
    onSettled: () => { inFlight.current = false },
  })
  const handleSave = (event: React.FormEvent) => {
    event.preventDefault()
    // Also guard same-tick submissions before React has disabled the button.
    if (inFlight.current || !dirty) return
    inFlight.current = true
    save.mutate({ revision: revision.current, settings: {
      ...settings,
      anime_detection: { ...settings.anime_detection, anime_folder_keywords: splitList(keywords) },
      file_extensions: splitList(extensions),
    } })
  }
  const errorDetail = isAxiosError(save.error)
    ? (save.error.response?.data?.errors?.join(' ') || save.error.response?.data?.detail)
    : null

  return (
    <form onSubmit={handleSave} className="space-y-8" aria-label="Preferences">
      {/* Audio Preferences */}
      <section className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Audio Preferences
        </h2>

        <div className="space-y-4">
          <label className="flex items-center gap-3">
            <input
              type="checkbox"
              checked={settings?.audio_preferences.require_english_non_anime ?? true}
              onChange={(e) => {
                if (!settings) return
                editSettings({
                  audio_preferences: {
                    ...settings.audio_preferences,
                    require_english_non_anime: e.target.checked,
                  },
                })
              }}
              className="w-4 h-4 text-orange-500 rounded"
            />
            <div>
              <span className="font-medium text-gray-900 dark:text-white">
                Require English audio for non-anime
              </span>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Flag files missing English audio track
              </p>
            </div>
          </label>

          <label className="flex items-center gap-3">
            <input
              type="checkbox"
              checked={settings?.audio_preferences.require_japanese_anime ?? true}
              onChange={(e) => {
                if (!settings) return
                editSettings({
                  audio_preferences: {
                    ...settings.audio_preferences,
                    require_japanese_anime: e.target.checked,
                  },
                })
              }}
              className="w-4 h-4 text-orange-500 rounded"
            />
            <div>
              <span className="font-medium text-gray-900 dark:text-white">
                Require Japanese audio for anime
              </span>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Flag anime files missing Japanese audio track
              </p>
            </div>
          </label>

          <label className="flex items-center gap-3">
            <input
              type="checkbox"
              checked={settings?.audio_preferences.require_dual_audio_anime ?? true}
              onChange={(e) => {
                if (!settings) return
                editSettings({
                  audio_preferences: {
                    ...settings.audio_preferences,
                    require_dual_audio_anime: e.target.checked,
                  },
                })
              }}
              className="w-4 h-4 text-orange-500 rounded"
            />
            <div>
              <span className="font-medium text-gray-900 dark:text-white">
                Require dual audio for anime
              </span>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Flag anime files without both English and Japanese audio
              </p>
            </div>
          </label>

          <label className="flex items-center gap-3">
            <input
              type="checkbox"
              checked={settings?.audio_preferences.check_default_track ?? true}
              onChange={(e) => {
                if (!settings) return
                editSettings({
                  audio_preferences: {
                    ...settings.audio_preferences,
                    check_default_track: e.target.checked,
                  },
                })
              }}
              className="w-4 h-4 text-orange-500 rounded"
            />
            <div>
              <span className="font-medium text-gray-900 dark:text-white">
                Check default audio track
              </span>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Flag if default track isn't the preferred language
              </p>
            </div>
          </label>


          <label className="flex items-center gap-3">
            <input
              type="checkbox"
              checked={settings?.audio_preferences.auto_fix_english_default_non_anime ?? false}
              disabled={!editCapabilities?.set_default_audio && !settings.audio_preferences.auto_fix_english_default_non_anime}
              onChange={(e) => {
                if (!settings) return
                editSettings({
                  audio_preferences: {
                    ...settings.audio_preferences,
                    auto_fix_english_default_non_anime: e.target.checked,
                  },
                })
              }}
              className="w-4 h-4 text-orange-500 rounded"
            />
            <div>
              <span className="font-medium text-gray-900 dark:text-white">
                Auto-fix default to English (non-anime)
              </span>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                {editCapabilities?.default_audio_reason || 'Automatically set English as default during scans for writable non-anime MKV files.'}
              </p>
            </div>
          </label>

          <div className="rounded-lg border border-gray-200 dark:border-gray-700 p-4 space-y-3">
            <div>
              <span className="font-medium text-gray-900 dark:text-white">
                Default audio tracks to keep when removing tracks
              </span>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Used by the removal tool when you do not manually override track selection. UND stays enabled by default because it can be mislabeled English.
              </p>
            </div>
            <div className="flex flex-wrap gap-4">
              {[
                { value: 'en', label: 'English' },
                { value: 'und', label: 'Undefined / UND' },
                { value: 'ja', label: 'Japanese' },
              ].map((option) => {
                const keepLanguages = settings?.audio_preferences.audio_track_keep_languages ?? ['en', 'und']
                const checked = keepLanguages.includes(option.value)
                return (
                  <label key={option.value} className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(e) => {
                        if (!settings) return
                        const current = new Set(settings.audio_preferences.audio_track_keep_languages ?? ['en', 'und'])
                        if (e.target.checked) {
                          current.add(option.value)
                        } else {
                          current.delete(option.value)
                        }
                        editSettings({
                          audio_preferences: {
                            ...settings.audio_preferences,
                            audio_track_keep_languages: [...current],
                          },
                        })
                      }}
                      className="w-4 h-4 text-orange-500 rounded"
                    />
                    {option.label}
                  </label>
                )
              })}
            </div>
          </div>
        </div>
      </section>

      {/* Anime Detection */}
      <section className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Anime Detection
        </h2>

        <div className="space-y-4">
          <label className="flex items-center gap-3">
            <input
              type="checkbox"
              checked={settings?.anime_detection.use_plex_genres ?? true}
              onChange={(e) => {
                if (!settings) return
                editSettings({
                  anime_detection: {
                    ...settings.anime_detection,
                    use_plex_genres: e.target.checked,
                  },
                })
              }}
              className="w-4 h-4 text-orange-500 rounded"
            />
            <div>
              <span className="font-medium text-gray-900 dark:text-white">
                Use Plex genres
              </span>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Auto-detect anime from Plex genre tags
              </p>
            </div>
          </label>

          <div>
            <label htmlFor="anime-keywords" className="block font-medium text-gray-900 dark:text-white mb-2">
              Anime folder keywords
            </label>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-2">
              Paths containing these words will be marked as anime. Leave blank to disable folder detection.
            </p>
            <input
              type="text"
              id="anime-keywords"
              value={keywords}
              onChange={(e) => { revision.current++; setKeywords(e.target.value) }}
              placeholder="anime, animation"
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
            />
          </div>
        </div>
      </section>

      {/* File Extensions */}
      <section className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          File Extensions
        </h2>

        <div>
          <p className="text-sm text-gray-500 dark:text-gray-400 mb-2">
            File extensions to scan (comma-separated)
          </p>
          <input
            type="text"
            id="file-extensions"
            aria-label="File extensions"
            value={extensions}
            onChange={(e) => { revision.current++; setExtensions(e.target.value) }}
            placeholder=".mkv, .mp4, .avi"
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
          />
        </div>
      </section>
      <div className="flex flex-wrap items-center gap-4">
        <button type="submit" disabled={!dirty || save.isPending}
          className="px-4 py-2 bg-orange-500 hover:bg-orange-600 disabled:opacity-50 text-white rounded-lg">
          {save.isPending ? 'Saving…' : 'Save preferences'}
        </button>
        <p role="status" className="text-sm text-gray-600 dark:text-gray-400">
          {save.isPending ? 'Saving preferences…' : dirty ? 'Unsaved changes' : save.isSuccess ? 'Preferences saved' : 'No unsaved changes'}
        </p>
        <p className="text-sm text-gray-600 dark:text-gray-400">Run a full scan after saving to apply changes to unchanged files.</p>
      </div>
      {save.isError && <p role="alert" className="text-sm text-red-600 dark:text-red-400">
        Could not save preferences. {typeof errorDetail === 'string' ? errorDetail : 'Please try again.'} Your edits have been kept.
      </p>}
    </form>
  )
}
