import { Fragment, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Search, AlertTriangle, FileVideo, ChevronDown, ChevronUp, Download, RefreshCw } from 'lucide-react'
import { mediaApi } from '../api/client'
import { useDebounce } from '../hooks/useDebounce'
import type { MediaFile, PaginatedResponse } from '../types'

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
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [hasIssues, setHasIssues] = useState<boolean | undefined>(undefined)
  const [expandedFile, setExpandedFile] = useState<number | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const debouncedSearch = useDebounce(search, 300)

  const updateDefaultAudio = useMutation({
    mutationFn: ({ fileId, language }: { fileId: number; language: string }) =>
      mediaApi.updateDefaultAudio(fileId, language),
    onSuccess: () => {
      setActionError(null)
      queryClient.invalidateQueries({ queryKey: ['files'] })
    },
    onError: () => {
      setActionError('Failed to update default audio track. Ensure this is an MKV file and the language exists.')
    },
  })


  const rescanFile = useMutation({
    mutationFn: (fileId: number) => mediaApi.rescanFile(fileId),
    onSuccess: () => {
      setActionError(null)
      queryClient.invalidateQueries({ queryKey: ['files'] })
    },
    onError: () => {
      setActionError('Failed to rescan file. Please confirm the file still exists and try again.')
    },
  })

  const { data, isLoading, error } = useQuery<PaginatedResponse<MediaFile>>({
    queryKey: ['files', page, debouncedSearch, hasIssues],
    queryFn: async () => {
      const response = await mediaApi.getFiles({
        page,
        page_size: 25,
        search: debouncedSearch || undefined,
        has_issues: hasIssues,
      })
      return response.data
    },
  })

  const formatFileSize = (bytes: number) => {
    const gb = bytes / (1024 * 1024 * 1024)
    if (gb >= 1) return `${gb.toFixed(2)} GB`
    const mb = bytes / (1024 * 1024)
    return `${mb.toFixed(1)} MB`
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
        <button
          className="flex items-center gap-2 px-4 py-2 bg-gray-100 hover:bg-gray-200 dark:bg-gray-700 dark:hover:bg-gray-600 text-gray-700 dark:text-gray-200 rounded-lg transition-colors"
        >
          <Download className="w-4 h-4" />
          Export CSV
        </button>
      </div>

      {/* Search and Filters */}
      <div className="flex flex-col sm:flex-row gap-4">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
          <input
            type="text"
            placeholder="Search files..."
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              setPage(1)
            }}
            className="w-full pl-10 pr-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-orange-500 focus:border-transparent"
          />
        </div>
        <select
          value={hasIssues === undefined ? '' : hasIssues.toString()}
          onChange={(e) => {
            setHasIssues(e.target.value === '' ? undefined : e.target.value === 'true')
            setPage(1)
          }}
          className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
        >
          <option value="">All Files</option>
          <option value="true">Has Issues</option>
          <option value="false">No Issues</option>
        </select>
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

      {/* Files Table */}
      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-500"></div>
        </div>
      ) : (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
          <table className="w-full">
            <thead className="bg-gray-50 dark:bg-gray-700/50">
              <tr>
                <th className="px-4 py-3 text-left text-sm font-medium text-gray-500 dark:text-gray-400">File</th>
                <th className="px-4 py-3 text-left text-sm font-medium text-gray-500 dark:text-gray-400 hidden md:table-cell">Size</th>
                <th className="px-4 py-3 text-left text-sm font-medium text-gray-500 dark:text-gray-400">Audio Tracks</th>
                <th className="px-4 py-3 text-left text-sm font-medium text-gray-500 dark:text-gray-400 hidden lg:table-cell">Status</th>
                <th className="w-10"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
              {data?.items.map((file) => (
                <Fragment key={file.id}>
                  <tr
                    className={`hover:bg-gray-50 dark:hover:bg-gray-700/50 cursor-pointer ${
                      file.has_issues ? 'bg-red-50/50 dark:bg-red-900/10' : ''
                    }`}
                    onClick={() => setExpandedFile(expandedFile === file.id ? null : file.id)}
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <FileVideo className="w-5 h-5 text-gray-400 flex-shrink-0" />
                        <span className="text-sm text-gray-900 dark:text-white truncate max-w-xs">
                          {file.filename}
                        </span>
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
                    <tr className="bg-gray-50 dark:bg-gray-700/30">
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
                                disabled={updateDefaultAudio.isPending}
                                className="px-2.5 py-1 text-xs rounded border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50"
                              >
                                {lang.toUpperCase()}
                              </button>
                            ))}
                          </div>
                          <div>
                            <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Audio Tracks:</span>
                            <div className="mt-2 space-y-2">
                              {file.audio_tracks.map((track) => (
                                <div key={track.id} className="flex items-center gap-4 text-sm">
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
              No files found
            </div>
          )}
        </div>
      )}

      {/* Pagination */}
      {data && data.pages > 1 && (
        <div className="flex items-center justify-between">
          <span className="text-sm text-gray-600 dark:text-gray-400">
            Showing {(page - 1) * 25 + 1} - {Math.min(page * 25, data.total)} of {data.total} files
          </span>
          <div className="flex items-center gap-2">
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
