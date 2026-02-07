import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Save, Plus, Trash2, FolderOpen, RefreshCw } from 'lucide-react'
import { settingsApi, scanApi } from '../api/client'
import type { UserSettings, ScanLocation } from '../types'

export default function SettingsPage() {
  const queryClient = useQueryClient()
  const [newLocation, setNewLocation] = useState({ path: '', label: '', is_anime_folder: false })

  // Fetch settings
  const { data: settings, isLoading: settingsLoading } = useQuery<UserSettings>({
    queryKey: ['settings'],
    queryFn: async () => {
      const response = await settingsApi.get()
      return response.data
    },
  })

  // Fetch scan locations
  const { data: locations, isLoading: locationsLoading } = useQuery<ScanLocation[]>({
    queryKey: ['scanLocations'],
    queryFn: async () => {
      const response = await scanApi.getLocations()
      return response.data
    },
  })

  // Update settings mutation
  const updateSettings = useMutation({
    mutationFn: (data: Partial<UserSettings>) => settingsApi.update(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings'] })
    },
    onError: () => {
      // Refetch to revert optimistic changes
      queryClient.invalidateQueries({ queryKey: ['settings'] })
    },
  })

  // Location mutations
  const addLocation = useMutation({
    mutationFn: (data: { path: string; label: string; is_anime_folder: boolean }) =>
      scanApi.createLocation(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scanLocations'] })
      setNewLocation({ path: '', label: '', is_anime_folder: false })
    },
  })

  const deleteLocation = useMutation({
    mutationFn: (id: number) => scanApi.deleteLocation(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scanLocations'] })
    },
  })

  const toggleLocation = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      scanApi.updateLocation(id, { enabled }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scanLocations'] })
    },
  })

  const handleAddLocation = (e: React.FormEvent) => {
    e.preventDefault()
    if (newLocation.path && newLocation.label) {
      addLocation.mutate(newLocation)
    }
  }

  if (settingsLoading || locationsLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-500"></div>
      </div>
    )
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Settings</h1>
        <p className="text-gray-500 dark:text-gray-400 mt-1">
          Configure scan locations and audio preferences
        </p>
      </div>

      {/* Scan Locations */}
      <section className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
          <FolderOpen className="w-5 h-5" />
          Scan Locations
        </h2>

        {/* Existing locations */}
        <div className="space-y-3 mb-6">
          {locations?.map((loc) => (
            <div
              key={loc.id}
              className="flex items-center gap-4 p-3 bg-gray-50 dark:bg-gray-700/50 rounded-lg"
            >
              <input
                type="checkbox"
                checked={loc.enabled}
                onChange={(e) => toggleLocation.mutate({ id: loc.id, enabled: e.target.checked })}
                className="w-4 h-4 text-orange-500 rounded"
              />
              <div className="flex-1 min-w-0">
                <p className="font-medium text-gray-900 dark:text-white">{loc.label}</p>
                <p className="text-sm text-gray-500 dark:text-gray-400 truncate">{loc.path}</p>
              </div>
              {loc.is_anime_folder && (
                <span className="px-2 py-0.5 text-xs font-medium bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400 rounded">
                  Anime
                </span>
              )}
              <span className="text-sm text-gray-500">{loc.file_count} files</span>
              <button
                onClick={() => deleteLocation.mutate(loc.id)}
                className="p-1 text-red-500 hover:text-red-700"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))}
          {locations?.length === 0 && (
            <p className="text-gray-500 dark:text-gray-400 text-center py-4">
              No scan locations configured
            </p>
          )}
        </div>

        {/* Add new location */}
        <form onSubmit={handleAddLocation} className="flex flex-col sm:flex-row gap-3">
          <input
            type="text"
            placeholder="Path (e.g., /media/tv)"
            value={newLocation.path}
            onChange={(e) => setNewLocation({ ...newLocation, path: e.target.value })}
            className="flex-1 px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
          />
          <input
            type="text"
            placeholder="Label (e.g., TV Shows)"
            value={newLocation.label}
            onChange={(e) => setNewLocation({ ...newLocation, label: e.target.value })}
            className="sm:w-40 px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
          />
          <label className="flex items-center gap-2 px-3">
            <input
              type="checkbox"
              checked={newLocation.is_anime_folder}
              onChange={(e) => setNewLocation({ ...newLocation, is_anime_folder: e.target.checked })}
              className="w-4 h-4 text-orange-500 rounded"
            />
            <span className="text-sm text-gray-700 dark:text-gray-300">Anime</span>
          </label>
          <button
            type="submit"
            disabled={!newLocation.path || !newLocation.label || addLocation.isPending}
            className="flex items-center gap-2 px-4 py-2 bg-orange-500 hover:bg-orange-600 disabled:opacity-50 text-white rounded-lg"
          >
            <Plus className="w-4 h-4" />
            Add
          </button>
        </form>
      </section>

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
                updateSettings.mutate({
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
                updateSettings.mutate({
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
                updateSettings.mutate({
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
                updateSettings.mutate({
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
                updateSettings.mutate({
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
            <label className="block font-medium text-gray-900 dark:text-white mb-2">
              Anime folder keywords
            </label>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-2">
              Paths containing these words will be marked as anime
            </p>
            <input
              type="text"
              value={settings?.anime_detection.anime_folder_keywords.join(', ') ?? ''}
              onChange={(e) => {
                if (!settings) return
                updateSettings.mutate({
                  anime_detection: {
                    ...settings.anime_detection,
                    anime_folder_keywords: e.target.value.split(',').map((s) => s.trim()).filter(Boolean),
                  },
                })
              }}
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
            value={settings?.file_extensions.join(', ') ?? ''}
            onChange={(e) =>
              updateSettings.mutate({
                file_extensions: e.target.value.split(',').map((s) => s.trim()).filter(Boolean),
              })
            }
            placeholder=".mkv, .mp4, .avi"
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
          />
        </div>
      </section>
    </div>
  )
}
