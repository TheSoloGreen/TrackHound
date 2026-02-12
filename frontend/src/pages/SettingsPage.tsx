import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, FolderOpen, ChevronRight, Folder } from 'lucide-react'
import { settingsApi, scanApi } from '../api/client'
import type { UserSettings, ScanLocation, DirectoryBrowseResponse, MediaType } from '../types'

const MEDIA_TYPE_OPTIONS: { value: MediaType; label: string }[] = [
  { value: 'movie', label: 'Movies' },
  { value: 'tv', label: 'TV Shows' },
  { value: 'anime', label: 'Anime' },
]

const MEDIA_TYPE_BADGE: Record<MediaType, { label: string; classes: string }> = {
  movie: {
    label: 'Movie',
    classes: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  },
  tv: {
    label: 'TV Show',
    classes: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
  },
  anime: {
    label: 'Anime',
    classes: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
  },
}

function DirectoryPicker({
  onSelect,
  onCancel,
}: {
  onSelect: (path: string, name: string) => void
  onCancel: () => void
}) {
  const [currentPath, setCurrentPath] = useState('/media')

  const { data, isLoading, error } = useQuery<DirectoryBrowseResponse>({
    queryKey: ['browse', currentPath],
    queryFn: async () => {
      const response = await scanApi.browse(currentPath)
      return response.data
    },
  })

  // Build breadcrumb parts from the current path
  const pathParts = currentPath.split('/').filter(Boolean)
  const breadcrumbs = pathParts.map((part, i) => ({
    name: part,
    path: '/' + pathParts.slice(0, i + 1).join('/'),
  }))

  return (
    <div className="border border-gray-300 dark:border-gray-600 rounded-lg overflow-hidden">
      {/* Breadcrumb */}
      <div className="flex items-center gap-1 px-3 py-2 bg-gray-100 dark:bg-gray-700 text-sm overflow-x-auto">
        {breadcrumbs.map((crumb, i) => (
          <span key={crumb.path} className="flex items-center gap-1 flex-shrink-0">
            {i > 0 && <ChevronRight className="w-3 h-3 text-gray-400" />}
            <button
              onClick={() => setCurrentPath(crumb.path)}
              className="text-orange-600 dark:text-orange-400 hover:underline"
            >
              {crumb.name}
            </button>
          </span>
        ))}
      </div>

      {/* Directory listing */}
      <div className="max-h-64 overflow-y-auto">
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-orange-500"></div>
          </div>
        ) : error ? (
          <div className="p-4 text-sm text-red-600 dark:text-red-400">
            Could not browse this directory.
          </div>
        ) : data && data.directories.length > 0 ? (
          <div className="divide-y divide-gray-200 dark:divide-gray-700">
            {data.directories.map((dir) => (
              <button
                key={dir.path}
                onClick={() => setCurrentPath(dir.path)}
                className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors text-left"
              >
                <Folder className="w-4 h-4 text-orange-500 flex-shrink-0" />
                <span className="text-gray-900 dark:text-white truncate">{dir.name}</span>
                <ChevronRight className="w-4 h-4 text-gray-400 ml-auto flex-shrink-0" />
              </button>
            ))}
          </div>
        ) : (
          <div className="p-4 text-sm text-gray-500 dark:text-gray-400 text-center">
            No subdirectories found
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center justify-between px-3 py-2 bg-gray-50 dark:bg-gray-700/50 border-t border-gray-200 dark:border-gray-600">
        <span className="text-xs text-gray-500 dark:text-gray-400 truncate mr-2">
          {currentPath}
        </span>
        <div className="flex gap-2 flex-shrink-0">
          <button
            onClick={onCancel}
            className="px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-600"
          >
            Cancel
          </button>
          <button
            onClick={() => {
              const name = currentPath.split('/').filter(Boolean).pop() || 'media'
              onSelect(currentPath, name)
            }}
            className="px-3 py-1.5 text-sm bg-orange-500 hover:bg-orange-600 text-white rounded-lg"
          >
            Select This Folder
          </button>
        </div>
      </div>
    </div>
  )
}

export default function SettingsPage() {
  const queryClient = useQueryClient()
  const [showPicker, setShowPicker] = useState(false)
  const [newLocation, setNewLocation] = useState({
    path: '',
    label: '',
    media_type: 'tv' as MediaType,
  })

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
      queryClient.invalidateQueries({ queryKey: ['settings'] })
    },
  })

  // Location mutations
  const addLocation = useMutation({
    mutationFn: (data: { path: string; label: string; media_type: string }) =>
      scanApi.createLocation(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scanLocations'] })
      setNewLocation({ path: '', label: '', media_type: 'tv' })
      setShowPicker(false)
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

  const handleDirectorySelect = (path: string, name: string) => {
    setNewLocation((prev) => ({
      ...prev,
      path,
      label: prev.label || name.charAt(0).toUpperCase() + name.slice(1),
    }))
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
          {locations?.map((loc) => {
            const badge = MEDIA_TYPE_BADGE[loc.media_type] || MEDIA_TYPE_BADGE.tv
            return (
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
                <span className={`px-2 py-0.5 text-xs font-medium rounded ${badge.classes}`}>
                  {badge.label}
                </span>
                <span className="text-sm text-gray-500">{loc.file_count} files</span>
                <button
                  onClick={() => deleteLocation.mutate(loc.id)}
                  className="p-1 text-red-500 hover:text-red-700"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            )
          })}
          {locations?.length === 0 && (
            <p className="text-gray-500 dark:text-gray-400 text-center py-4">
              No scan locations configured
            </p>
          )}
        </div>

        {/* Add new location */}
        {showPicker ? (
          <div className="space-y-4">
            <DirectoryPicker
              onSelect={handleDirectorySelect}
              onCancel={() => setShowPicker(false)}
            />
            {newLocation.path && (
              <form onSubmit={handleAddLocation} className="flex flex-col sm:flex-row gap-3">
                <div className="flex-1 px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-gray-50 dark:bg-gray-700 text-gray-700 dark:text-gray-300 text-sm truncate">
                  {newLocation.path}
                </div>
                <input
                  type="text"
                  placeholder="Label"
                  value={newLocation.label}
                  onChange={(e) => setNewLocation({ ...newLocation, label: e.target.value })}
                  className="sm:w-40 px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                />
                <select
                  value={newLocation.media_type}
                  onChange={(e) => setNewLocation({ ...newLocation, media_type: e.target.value as MediaType })}
                  className="sm:w-36 px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                >
                  {MEDIA_TYPE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
                <button
                  type="submit"
                  disabled={!newLocation.path || !newLocation.label || addLocation.isPending}
                  className="flex items-center gap-2 px-4 py-2 bg-orange-500 hover:bg-orange-600 disabled:opacity-50 text-white rounded-lg"
                >
                  <Plus className="w-4 h-4" />
                  Add
                </button>
              </form>
            )}
          </div>
        ) : (
          <button
            onClick={() => setShowPicker(true)}
            className="flex items-center gap-2 px-4 py-2 bg-orange-500 hover:bg-orange-600 text-white rounded-lg"
          >
            <Plus className="w-4 h-4" />
            Add Scan Location
          </button>
        )}
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


          <label className="flex items-center gap-3">
            <input
              type="checkbox"
              checked={settings?.audio_preferences.auto_fix_english_default_non_anime ?? false}
              onChange={(e) => {
                if (!settings) return
                updateSettings.mutate({
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
                Automatically set English as default during scans for non-anime files when available
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
