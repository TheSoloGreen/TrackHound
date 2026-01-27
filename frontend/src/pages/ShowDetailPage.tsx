import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, AlertTriangle, Languages, Check, X } from 'lucide-react'
import { mediaApi } from '../api/client'
import type { ShowDetail, SeasonDetail } from '../types'
import { useState } from 'react'

export default function ShowDetailPage() {
  const { id } = useParams<{ id: string }>()
  const queryClient = useQueryClient()
  const [selectedSeason, setSelectedSeason] = useState<number | null>(null)

  const { data: show, isLoading } = useQuery<ShowDetail>({
    queryKey: ['show', id],
    queryFn: async () => {
      const response = await mediaApi.getShow(Number(id))
      return response.data
    },
  })

  const { data: seasonDetail } = useQuery<SeasonDetail>({
    queryKey: ['season', id, selectedSeason],
    queryFn: async () => {
      const response = await mediaApi.getSeason(Number(id), selectedSeason!)
      return response.data
    },
    enabled: !!selectedSeason,
  })

  const toggleAnimeMutation = useMutation({
    mutationFn: (isAnime: boolean) =>
      mediaApi.updateShow(Number(id), { is_anime: isAnime, anime_source: isAnime ? 'manual' : undefined }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['show', id] })
    },
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-500"></div>
      </div>
    )
  }

  if (!show) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500">Show not found</p>
        <Link to="/shows" className="text-orange-500 hover:underline mt-2 inline-block">
          Back to shows
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start gap-4">
        <Link
          to="/shows"
          className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
        >
          <ArrowLeft className="w-5 h-5 text-gray-500" />
        </Link>
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
              {show.title}
            </h1>
            {show.is_anime && (
              <span className="px-2 py-0.5 text-xs font-medium bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400 rounded">
                Anime
              </span>
            )}
          </div>
          <p className="text-gray-500 dark:text-gray-400 mt-1">
            {show.season_count} seasons • {show.episode_count} episodes
            {show.issues_count > 0 && (
              <span className="text-red-500 ml-2">
                • {show.issues_count} issues
              </span>
            )}
          </p>
        </div>
        <button
          onClick={() => toggleAnimeMutation.mutate(!show.is_anime)}
          disabled={toggleAnimeMutation.isPending}
          className={`px-4 py-2 rounded-lg font-medium transition-colors ${
            show.is_anime
              ? 'bg-purple-100 text-purple-700 hover:bg-purple-200 dark:bg-purple-900/30 dark:text-purple-400'
              : 'bg-gray-100 text-gray-700 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-300'
          }`}
        >
          {show.is_anime ? 'Marked as Anime' : 'Mark as Anime'}
        </button>
      </div>

      {/* Seasons */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Season List */}
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4">
          <h2 className="font-semibold text-gray-900 dark:text-white mb-4">Seasons</h2>
          <div className="space-y-2">
            {show.seasons.map((season) => (
              <button
                key={season.id}
                onClick={() => setSelectedSeason(season.season_number)}
                className={`w-full flex items-center justify-between p-3 rounded-lg transition-colors ${
                  selectedSeason === season.season_number
                    ? 'bg-orange-100 dark:bg-orange-900/30'
                    : 'hover:bg-gray-100 dark:hover:bg-gray-700'
                }`}
              >
                <span className="font-medium text-gray-900 dark:text-white">
                  Season {season.season_number}
                </span>
                <div className="flex items-center gap-2 text-sm">
                  <span className="text-gray-500">{season.episode_count} eps</span>
                  {season.issues_count > 0 && (
                    <span className="flex items-center gap-1 text-red-500">
                      <AlertTriangle className="w-4 h-4" />
                      {season.issues_count}
                    </span>
                  )}
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Episode List */}
        <div className="lg:col-span-2 bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4">
          <h2 className="font-semibold text-gray-900 dark:text-white mb-4">
            {selectedSeason ? `Season ${selectedSeason} Episodes` : 'Select a season'}
          </h2>
          {seasonDetail ? (
            <div className="space-y-3 max-h-[500px] overflow-y-auto">
              {seasonDetail.media_files.map((file) => (
                <div
                  key={file.id}
                  className={`p-3 rounded-lg border ${
                    file.has_issues
                      ? 'border-red-200 bg-red-50 dark:border-red-800 dark:bg-red-900/20'
                      : 'border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-700/50'
                  }`}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <p className="font-medium text-gray-900 dark:text-white truncate">
                        {file.episode_number ? `E${file.episode_number}` : ''} {file.filename}
                      </p>
                      {file.issue_details && (
                        <p className="text-sm text-red-600 dark:text-red-400 mt-1">
                          {file.issue_details}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-1">
                      {file.audio_tracks.map((track, i) => (
                        <span
                          key={i}
                          className={`px-2 py-0.5 text-xs rounded ${
                            track.language === 'en'
                              ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'
                              : track.language === 'ja'
                              ? 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400'
                              : 'bg-gray-100 text-gray-700 dark:bg-gray-600 dark:text-gray-300'
                          }`}
                          title={`${track.codec} ${track.channel_layout || ''} ${track.is_default ? '(default)' : ''}`}
                        >
                          {track.language?.toUpperCase() || 'UND'}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-gray-500 dark:text-gray-400 text-center py-8">
              Click a season to view episodes
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
