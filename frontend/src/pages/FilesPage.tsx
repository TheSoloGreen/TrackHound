import { Fragment, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import LanguageReview from '../components/LanguageReview'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Search, AlertTriangle, FileVideo, ChevronDown, ChevronUp, Download, RefreshCw, Trash2 } from 'lucide-react'
import { mediaApi } from '../api/client'
import { refreshLibrary } from '../api/cache'
import { useDebounce } from '../hooks/useDebounce'
import type { MediaFile, PaginatedResponse, AudioTrackRemovalPlan, IssueCategory, MediaType } from '../types'
import { isAxiosError } from 'axios'

function AudioTrackBadge({ track }: { track: MediaFile['audio_tracks'][0] }) {
  const langColors: Record<string, string> = {
    en: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
    ja: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
  }
  const color = langColors[track.language || ''] || 'bg-gray-100 text-gray-700 dark:bg-gray-600 dark:text-gray-300'

  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded ${color}`}
      title={`${track.codec || 'Unknown codec'} ${track.channel_layout || ''} ${track.bitrate ? `${Math.round(track.bitrate / 1000)}kbps` : ''} ${track.is_default ? '(default)' : ''}`}
    >
      {track.language?.toUpperCase() || 'UND'}
      {track.is_default && <span className="text-[10px]">★</span>}
    </span>
  )
}

export default function FilesPage() {
  const [params, setParams] = useSearchParams()
  const positiveInt = (value: string | null) => value && /^\d+$/.test(value) && Number.isSafeInteger(Number(value)) && Number(value) > 0 ? Number(value) : undefined
  const page = positiveInt(params.get('page')) ?? 1
  const search = params.get('search') ?? ''
  const hasIssues = params.get('has_issues') === 'true' ? true : params.get('has_issues') === 'false' ? false : undefined
  const categories: IssueCategory[] = ['missing_required_audio', 'preferred_not_default', 'missing_english', 'missing_japanese', 'missing_dual_audio', 'unknown_language']
  const issueCategory = categories.includes(params.get('issue_category') as IssueCategory) ? params.get('issue_category') as IssueCategory : undefined
  const mediaType = ['tv', 'movie', 'anime'].includes(params.get('media_type') || '') ? params.get('media_type') as MediaType : undefined
  const fileId = positiveInt(params.get('file_id'))
  const expandedFile = positiveInt(params.get('expanded'))
  const returnTo = params.get('return_to')
  const safeReturn = returnTo && /^\/library(?:\/\d+)?(?:\?[^#]*)?$/.test(returnTo) ? returnTo : null
  const update = (values: Record<string, string | undefined>, replace = false) => {
    setParams((previous) => {
      const next = new URLSearchParams(previous)
      Object.entries(values).forEach(([key, value]) => value === undefined ? next.delete(key) : next.set(key, value))
      return next
    }, { replace })
  }
  const setPage = (value: number | ((previous: number) => number)) => update({ page: String(typeof value === 'function' ? value(page) : value) })
  const setExpandedFile = (id: number | null) => update({ expanded: id === null ? undefined : String(id) })
  const [trackKeepSelections, setTrackKeepSelections] = useState<Record<string, number[]>>({})
  const [actionError, setActionError] = useState<string | null>(null)
  const [isResetting, setIsResetting] = useState(false)
  const queryClient = useQueryClient()
  const debouncedSearch = useDebounce(search, 300)

  const refreshMedia = () => {
    setTrackKeepSelections({})
    return refreshLibrary(queryClient)
  }

  const showActionError = (error: unknown) => {
    setActionError(isAxiosError(error) && typeof error.response?.data?.detail === 'string'
      ? error.response.data.detail : 'The operation failed. Please try again.')
    void refreshMedia()
  }

  const updateDefaultAudio = useMutation({
    mutationFn: ({ fileId, language }: { fileId: number; language: string }) =>
      mediaApi.updateDefaultAudio(fileId, language),
    onSuccess: () => {
      setActionError(null)
      return refreshMedia()
    },
    onError: showActionError,
  })


  const rescanFile = useMutation({
    mutationFn: (fileId: number) => mediaApi.rescanFile(fileId),
    onSuccess: () => {
      setActionError(null)
      return refreshMedia()
    },
    onError: showActionError,
  })

  const removeAudioTracks = useMutation({
    mutationFn: ({ file, keepTrackIndices }: { file: MediaFile; keepTrackIndices: number[] }) =>
      mediaApi.removeAudioTracks(file.id, { keep_track_indices: keepTrackIndices, keep_backup: true, expected_last_scanned: file.last_scanned }),
    onSuccess: () => {
      setActionError(null)
      return refreshMedia()
    },
    onError: showActionError,
  })

  const { data, isLoading, error } = useQuery<PaginatedResponse<MediaFile>>({
    queryKey: ['files', page, debouncedSearch, hasIssues, issueCategory, mediaType, fileId],
    queryFn: async () => {
      const response = await mediaApi.getFiles({
        page,
        page_size: 25,
        search: debouncedSearch || undefined,
        has_issues: hasIssues,
        issue_category: issueCategory,
        media_type: mediaType,
        file_id: fileId,
      })
      return response.data
    },
  })

  const expandedMediaFile = data?.items.find((file) => file.id === expandedFile)
  const { data: removalPlan, isFetching: planLoading, error: planError } = useQuery<AudioTrackRemovalPlan>({
    queryKey: ['trackRemovalPlan', expandedFile, expandedMediaFile?.last_scanned],
    queryFn: async () => (await mediaApi.getAudioTrackRemovalPlan(expandedFile!)).data,
    enabled: !!expandedMediaFile,
  })


  const handleExport = async (format: 'csv' | 'json' = 'csv') => {
    try {
      setActionError(null)
      const response = await mediaApi.exportFiles({
        format,
        has_issues: hasIssues,
        issue_category: issueCategory,
        media_type: mediaType,
        file_id: fileId,
        search: debouncedSearch || undefined,
      })

      const blob = new Blob([response.data], {
        type: format === 'csv' ? 'text/csv;charset=utf-8' : 'application/json;charset=utf-8',
      })
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      const timestamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')
      link.href = url
      link.download = `trackhound-files-${timestamp}.${format}`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      window.URL.revokeObjectURL(url)
    } catch {
      setActionError('Failed to export files. Please try again.')
    }
  }

  const handleResetScannedFiles = async () => {
    const confirmed = window.confirm(
      'Reset scanned files? This will delete scanned files, shows, and issue history. Scan locations will be kept.'
    )
    if (!confirmed) return

    try {
      setActionError(null)
      setIsResetting(true)
      await mediaApi.resetFiles()
      setExpandedFile(null)
      setPage(1)
      await refreshMedia()
    } catch {
      setActionError('Failed to reset scanned files. Please try again.')
    } finally {
      setIsResetting(false)
    }
  }

  const formatFileSize = (bytes: number) => {
    const gb = bytes / (1024 * 1024 * 1024)
    if (gb >= 1) return `${gb.toFixed(2)} GB`
    const mb = bytes / (1024 * 1024)
    return `${mb.toFixed(1)} MB`
  }

  const selectedKeepTrackIndices = (file: MediaFile) =>
    trackKeepSelections[`${file.id}:${file.last_scanned}`] ??
      (removalPlan?.file_id === file.id && removalPlan.last_scanned === file.last_scanned ? removalPlan.keep_track_indices : [])

  const toggleKeepTrack = (file: MediaFile, trackIndex: number) => {
    const selected = new Set(selectedKeepTrackIndices(file))
    if (selected.has(trackIndex)) {
      selected.delete(trackIndex)
    } else {
      selected.add(trackIndex)
    }
    setTrackKeepSelections((prev) => ({
      ...prev,
      [`${file.id}:${file.last_scanned}`]: [...selected].sort((a, b) => a - b),
    }))
  }

  const handleRemoveAudioTracks = (file: MediaFile) => {
    if (planLoading || planError || !file.edit_capabilities?.remove_audio_tracks) return
    const keepTrackIndices = selectedKeepTrackIndices(file)
    const removeCount = file.audio_tracks.length - keepTrackIndices.length
    if (keepTrackIndices.length === 0) {
      setActionError('Select at least one audio track to keep.')
      return
    }
    if (removeCount <= 0) {
      setActionError('Select fewer tracks to keep before removing audio tracks.')
      return
    }
    const describe = (keep: boolean) => file.audio_tracks
      .filter((track) => keepTrackIndices.includes(track.track_index) === keep)
      .map((track) => `#${track.track_index} ${(track.language || track.language_raw || 'und').toUpperCase()}${track.title ? ` (${track.title})` : ''}`)
      .join(', ')
    const confirmed = window.confirm(
      `Edit ${file.filename}?\n\nKeep: ${describe(true)}\nRemove: ${describe(false)}\n\nThe original will be preserved as a .bak file. Existing backups will not be overwritten.`
    )
    if (!confirmed) return
    removeAudioTracks.mutate({ file, keepTrackIndices })
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Files</h1>
          <p className="text-gray-500 dark:text-gray-400 mt-1">
            Browse all scanned media files
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => handleExport('csv')}
            className="flex items-center gap-2 px-4 py-2 bg-gray-100 hover:bg-gray-200 dark:bg-gray-700 dark:hover:bg-gray-600 text-gray-700 dark:text-gray-200 rounded-lg transition-colors"
          >
            <Download className="w-4 h-4" />
            Export CSV
          </button>
          <button
            onClick={() => handleExport('json')}
            className="flex items-center gap-2 px-4 py-2 bg-gray-100 hover:bg-gray-200 dark:bg-gray-700 dark:hover:bg-gray-600 text-gray-700 dark:text-gray-200 rounded-lg transition-colors"
          >
            <Download className="w-4 h-4" />
            Export JSON
          </button>
          <button
            onClick={handleResetScannedFiles}
            disabled={isResetting}
            className="flex items-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white rounded-lg transition-colors"
          >
            <Trash2 className="w-4 h-4" />
            {isResetting ? 'Resetting...' : 'Reset Scanned Files'}
          </button>
        </div>
      </div>

      {safeReturn && <Link to={safeReturn} className="text-orange-600 underline">Back to title and season</Link>}
      {fileId && <p className="text-sm">Viewing file #{fileId}. <Link className="text-orange-600 underline" to="/files">Browse all files</Link></p>}
      {/* Search and Filters */}
      <div className="flex flex-wrap gap-4">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
          <input
            type="text"
            aria-label="Search files"
            placeholder="Search files..."
            value={search}
            onChange={(e) => {
              update({ search: e.target.value || undefined, page: undefined }, true)
            }}
            className="w-full pl-10 pr-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-orange-500 focus:border-transparent"
          />
        </div>
        <select
          aria-label="Issue status"
          value={hasIssues === undefined ? '' : hasIssues.toString()}
          onChange={(e) => {
            update({ has_issues: e.target.value || undefined, page: undefined })
          }}
          className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
        >
          <option value="">All Files</option>
          <option value="true">Has Issues</option>
          <option value="false">No Issues</option>
        </select>
        <select
          aria-label="Issue type"
          value={issueCategory ?? ''}
          onChange={(e) => {
            update({ issue_category: e.target.value || undefined, page: undefined })
          }}
          className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
        >
          <option value="">All Issue Types</option>
          <option value="missing_required_audio">Missing required audio</option>
          <option value="preferred_not_default">Preferred audio not default</option>
          <option value="missing_english">No English tag</option>
          <option value="missing_japanese">No Japanese tag</option>
          <option value="missing_dual_audio">Missing dual audio</option>
          <option value="unknown_language">Unknown language</option>
        </select>
        <select aria-label="Media type" value={mediaType || ''} onChange={(event) => update({ media_type: event.target.value || undefined, page: undefined })}
          className="rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2">
          <option value="">All media types</option><option value="movie">Movies</option><option value="tv">TV shows</option><option value="anime">Anime</option>
        </select>
        <button onClick={() => setParams({})} className="text-sm underline">Clear filters</button>
      </div>

      {/* Error message */}
      {error && (
        <div className="p-4 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-lg">
          <p className="text-sm text-red-700 dark:text-red-400">Failed to load files. Please try again.</p>
        </div>
      )}

      {actionError && (
        <div className="p-4 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-lg">
          <p className="text-sm text-red-700 dark:text-red-400">{actionError}</p>
        </div>
      )}

      <p className="text-xs text-gray-500 md:hidden">Scroll the table sideways to view all audio tracks and controls.</p>
      {/* Files Table */}
      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-500"></div>
        </div>
      ) : (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-x-auto">
          <table className="w-full min-w-[600px]">
            <thead className="bg-gray-50 dark:bg-gray-700/50">
              <tr>
                <th className="px-4 py-3 text-left text-sm font-medium text-gray-500 dark:text-gray-400">File</th>
                <th className="px-4 py-3 text-left text-sm font-medium text-gray-500 dark:text-gray-400 hidden md:table-cell">Size</th>
                <th className="px-4 py-3 text-left text-sm font-medium text-gray-500 dark:text-gray-400">Audio Tracks</th>
                <th className="px-4 py-3 text-left text-sm font-medium text-gray-500 dark:text-gray-400 hidden lg:table-cell">Status</th>
                <th className="relative w-10"><span className="sr-only">Details</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
              {data?.items.map((file) => (
                <Fragment key={file.id}>
                  <tr
                    className={`hover:bg-gray-50 dark:hover:bg-gray-700/50 cursor-pointer ${
                      file.has_issues ? 'bg-red-50/50 dark:bg-red-900/10' : ''
                    }`}
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <FileVideo className="w-5 h-5 text-gray-400 flex-shrink-0" />
                        <button type="button" aria-label={`Audio details for ${file.filename}`} aria-expanded={expandedFile === file.id}
                          aria-controls={`file-details-${file.id}`} onClick={() => setExpandedFile(expandedFile === file.id ? null : file.id)}
                          className="text-left text-sm text-gray-900 dark:text-white max-w-xs break-words underline decoration-dotted">
                          {file.filename}
                        </button>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500 dark:text-gray-400 hidden md:table-cell">
                      {formatFileSize(file.file_size)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {file.audio_tracks.slice(0, 3).map((track) => (
                          <AudioTrackBadge key={track.id} track={track} />
                        ))}
                        {file.audio_tracks.length > 3 && (
                          <span className="text-xs text-gray-500">+{file.audio_tracks.length - 3}</span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 hidden lg:table-cell">
                      {file.has_issues ? (
                        <span className="flex items-center gap-1 text-sm text-red-600 dark:text-red-400">
                          <AlertTriangle className="w-4 h-4" />
                          Issues
                        </span>
                      ) : (
                        <span className="text-sm text-green-600 dark:text-green-400">OK</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {expandedFile === file.id ? (
                        <ChevronUp className="w-4 h-4 text-gray-400" />
                      ) : (
                        <ChevronDown className="w-4 h-4 text-gray-400" />
                      )}
                    </td>
                  </tr>
                  {expandedFile === file.id && (
                    <tr id={`file-details-${file.id}`} className="bg-gray-50 dark:bg-gray-700/30">
                      <td colSpan={5} className="px-4 py-4">
                        <div className="space-y-3">
                          <div>
                            <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Full Path:</span>
                            <p className="text-sm text-gray-500 dark:text-gray-400 break-all">{file.file_path}</p>
                          </div>
                          {file.issue_details && (
                            <div>
                              <span className="text-sm font-medium text-red-700 dark:text-red-400">Issues:</span>
                              <p className="text-sm text-red-600 dark:text-red-400">{file.issue_details}</p>
                            </div>
                          )}
                          <div className="flex flex-wrap items-center gap-2">
                            <button
                              onClick={(e) => {
                                e.stopPropagation()
                                rescanFile.mutate(file.id)
                              }}
                              disabled={rescanFile.isPending}
                              className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs rounded border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50"
                            >
                              <RefreshCw className={`w-3.5 h-3.5 ${rescanFile.isPending && rescanFile.variables === file.id ? 'animate-spin' : ''}`} />
                              Rescan File
                            </button>
                            <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Set default audio:</span>
                            {[...new Set(file.audio_tracks.map((track) => (track.language || '').toLowerCase()).filter(Boolean))].map((lang) => (
                              <button
                                key={lang}
                                onClick={(e) => {
                                  e.stopPropagation()
                                  updateDefaultAudio.mutate({ fileId: file.id, language: lang })
                                }}
                                disabled={updateDefaultAudio.isPending || removeAudioTracks.isPending || !file.edit_capabilities?.set_default_audio}
                                title={file.edit_capabilities?.default_audio_reason || undefined}
                                className="px-2.5 py-1 text-xs rounded border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50"
                              >
                                {lang.toUpperCase()}
                              </button>
                            ))}
                          </div>
                          {file.edit_capabilities?.default_audio_reason && (
                            <p className="text-xs text-gray-500 dark:text-gray-400">{file.edit_capabilities.default_audio_reason}</p>
                          )}
                          <div className="rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20 p-3 space-y-3">
                            <div>
                              <span className="text-sm font-medium text-amber-800 dark:text-amber-300">Remove audio tracks:</span>
                              <p className="text-xs text-amber-700 dark:text-amber-400 mt-1">
                                Select the tracks to keep. The initial selection uses your saved language preferences.
                              </p>
                              <p className="text-xs text-amber-700 dark:text-amber-400 mt-1" role="status">
                                {file.edit_capabilities?.track_removal_reason || (planError ? 'Unable to load saved track preferences. Try reopening this file.' : planLoading ? 'Loading saved track preferences...' : '')}
                              </p>
                            </div>
                            <div className="flex flex-wrap gap-2">
                              {file.audio_tracks.map((track) => {
                                const selected = selectedKeepTrackIndices(file).includes(track.track_index)
                                return (
                                  <label
                                    key={track.id}
                                    className="inline-flex items-center gap-2 px-2.5 py-1 text-xs rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200"
                                  >
                                    <input
                                      type="checkbox"
                                      checked={selected}
                                      disabled={planLoading || !!planError || removeAudioTracks.isPending || !file.edit_capabilities?.remove_audio_tracks}
                                      onChange={() => toggleKeepTrack(file, track.track_index)}
                                      className="w-3.5 h-3.5 text-orange-500 rounded"
                                    />
                                    Keep #{track.track_index} {track.language?.toUpperCase() || track.language_raw?.toUpperCase() || 'UND'}
                                  </label>
                                )
                              })}
                            </div>
                            <button
                              onClick={(e) => {
                                e.stopPropagation()
                                handleRemoveAudioTracks(file)
                              }}
                              disabled={removeAudioTracks.isPending || updateDefaultAudio.isPending || planLoading || !!planError || removalPlan?.last_scanned !== file.last_scanned || !file.edit_capabilities?.remove_audio_tracks}
                              className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs rounded bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                              {removeAudioTracks.isPending && removeAudioTracks.variables?.file.id === file.id
                                ? 'Removing...'
                                : 'Remove Unchecked Tracks'}
                            </button>
                          </div>
                          <LanguageReview key={file.id} file={file} />
                          <div>
                            <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Audio Tracks:</span>
                            <div className="mt-2 space-y-2">
                              {file.audio_tracks.map((track) => (
                                <div key={track.id} className="flex flex-wrap items-center gap-2 text-sm">
                                  <span>#{track.track_index} · Raw language: {track.language_raw || 'not tagged'}</span>
                                  <AudioTrackBadge track={track} />
                                  <span className="text-gray-600 dark:text-gray-400">
                                    {track.codec} • {track.channel_layout || `${track.channels}ch`}
                                    {track.bitrate && ` • ${Math.round(track.bitrate / 1000)}kbps`}
                                    {track.title && ` • "${track.title}"`}
                                  </span>
                                </div>
                              ))}
                            </div>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
          {data?.items.length === 0 && (
            <div className="p-8 text-center text-gray-500 dark:text-gray-400">
              {fileId ? 'File not found or unavailable with these filters.' : 'No files found'}
            </div>
          )}
        </div>
      )}

      {/* Pagination */}
      {data && data.pages > 1 && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-sm text-gray-600 dark:text-gray-400">
            Showing {(page - 1) * 25 + 1} - {Math.min(page * 25, data.total)} of {data.total} files
          </span>
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="px-3 py-1 rounded border border-gray-300 dark:border-gray-600 disabled:opacity-50"
            >
              Previous
            </button>
            <span className="text-sm text-gray-600 dark:text-gray-400">
              Page {page} of {data.pages}
            </span>
            <label className="text-sm text-gray-600 dark:text-gray-400">Jump to</label>
            <input
              aria-label="Page number"
              type="number"
              min={1}
              max={data.pages}
              value={page}
              onChange={(e) => {
                const value = Number(e.target.value)
                if (!Number.isNaN(value)) {
                  setPage(Math.min(data.pages, Math.max(1, value)))
                }
              }}
              className="w-16 px-2 py-1 text-sm border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
            />
            <button
              onClick={() => setPage((p) => Math.min(data.pages, p + 1))}
              disabled={page === data.pages}
              className="px-3 py-1 rounded border border-gray-300 dark:border-gray-600 disabled:opacity-50"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
