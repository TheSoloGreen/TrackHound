import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Search, AlertTriangle, ChevronRight } from 'lucide-react'
import { mediaApi } from '../api/client'
import { useDebounce } from '../hooks/useDebounce'
import type { Show, PaginatedResponse, MediaType } from '../types'

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

function mediaTypeSummary(show: Show): string {
  if (show.media_type === 'movie') {
    const count = show.file_count || 1
    return `${count} file${count !== 1 ? 's' : ''}`
  }
  return `${show.season_count} season${show.season_count !== 1 ? 's' : ''} • ${show.episode_count} episode${show.episode_count !== 1 ? 's' : ''}`
}

export default function ShowsPage() {
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [filters, setFilters] = useState({
    media_type: undefined as string | undefined,
    has_issues: undefined as boolean | undefined,
  })

  const debouncedSearch = useDebounce(search, 300)

  const { data, isLoading, error } = useQuery<PaginatedResponse<Show>>({
    queryKey: ['shows', page, debouncedSearch, filters],
    queryFn: async () => {
      const response = await mediaApi.getShows({
        page,
        page_size: 20,
        search: debouncedSearch || undefined,
        media_type: filters.media_type,
        has_issues: filters.has_issues,
      })
      return response.data
    },
  })

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Library</h1>
        <p className="text-gray-500 dark:text-gray-400 mt-1">
          Browse your media library
        </p>
      </div>

      {/* Search and Filters */}
      <div className="flex flex-col sm:flex-row gap-4">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
          <input
            type="text"
            placeholder="Search library..."
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              setPage(1)
            }}
            className="w-full pl-10 pr-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-orange-500 focus:border-transparent"
          />
        </div>
        <div className="flex gap-2">
          <select
            value={filters.media_type || ''}
            onChange={(e) => {
              setFilters({
                ...filters,
                media_type: e.target.value || undefined,
              })
              setPage(1)
            }}
            className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
          >
            <option value="">All Types</option>
            <option value="movie">Movies</option>
            <option value="tv">TV Shows</option>
            <option value="anime">Anime</option>
          </select>
          <select
            value={filters.has_issues === undefined ? '' : filters.has_issues.toString()}
            onChange={(e) => {
              setFilters({
                ...filters,
                has_issues: e.target.value === '' ? undefined : e.target.value === 'true',
              })
              setPage(1)
            }}
            className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
          >
            <option value="">All Status</option>
            <option value="true">Has Issues</option>
            <option value="false">No Issues</option>
          </select>
        </div>
      </div>

      {/* Error message */}
      {error && (
        <div className="p-4 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-lg">
          <p className="text-sm text-red-700 dark:text-red-400">Failed to load library. Please try again.</p>
        </div>
      )}

      {/* Library List */}
      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-500"></div>
        </div>
      ) : (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
          <div className="divide-y divide-gray-200 dark:divide-gray-700">
            {data?.items.map((show) => {
              const badge = MEDIA_TYPE_BADGE[show.media_type] || MEDIA_TYPE_BADGE.tv
              return (
                <Link
                  key={show.id}
                  to={`/library/${show.id}`}
                  className="flex items-center gap-4 p-4 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
                >
                  {show.thumb_url ? (
                    <img
                      src={show.thumb_url}
                      alt={show.title}
                      className="w-16 h-24 object-cover rounded-lg"
                    />
                  ) : (
                    <div className="w-16 h-24 bg-gray-200 dark:bg-gray-700 rounded-lg flex items-center justify-center">
                      <span className="text-2xl font-bold text-gray-400">
                        {show.title[0]}
                      </span>
                    </div>
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <h3 className="font-semibold text-gray-900 dark:text-white truncate">
                        {show.title}
                      </h3>
                      <span className={`px-2 py-0.5 text-xs font-medium rounded ${badge.classes}`}>
                        {badge.label}
                      </span>
                    </div>
                    <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                      {mediaTypeSummary(show)}
                    </p>
                    {show.issues_count > 0 && (
                      <div className="flex items-center gap-1 mt-2 text-sm text-red-600 dark:text-red-400">
                        <AlertTriangle className="w-4 h-4" />
                        {show.issues_count} file{show.issues_count !== 1 ? 's' : ''} with issues
                      </div>
                    )}
                  </div>
                  <ChevronRight className="w-5 h-5 text-gray-400" />
                </Link>
              )
            })}
            {data?.items.length === 0 && (
              <div className="p-8 text-center text-gray-500 dark:text-gray-400">
                No titles found
              </div>
            )}
          </div>
        </div>
      )}

      {/* Pagination */}
      {data && data.pages > 1 && (
        <div className="flex items-center justify-center gap-2">
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
      )}
    </div>
  )
}
