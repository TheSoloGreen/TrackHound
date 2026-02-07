import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, AlertTriangle } from 'lucide-react'
import { mediaApi } from '../api/client'
import type { ShowDetail, SeasonDetail, MediaFile, MediaType } from '../types'
import { useState } from 'react'

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

function FileRow({ file, showEpisodeNumber }: { file: MediaFile; showEpisodeNumber: boolean }) {
  return (
    <div
      className={`p-3 rounded-lg border ${
        file.has_issues
          ? 'border-red-200 bg-red-50 dark:border-red-800 dark:bg-red-900/20'
          : 'border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-700/50'
      }`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="font-medium text-gray-900 dark:text-white truncate">
            {showEpisodeNumber && file.episode_number ? `E${file.episode_number} ` : ''}{file.filename}
          </p>
          {file.issue_details && (
            <p className="text-sm text-red-600 dark:text-red-400 mt-1">
              {file.issue_details}
            </p>
          )}
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          {file.audio_tracks.map((track) => (
            <span
              key={track.id}
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
  )
}

export default function ShowDetailPage() {
  const { id } = useParams<{ id: string }>()
  const queryClient = useQueryClient()
  const [selectedSeason, setSelectedSeason] = useState<number | null>(null)

  const showId = Number(id)

  const { data: show, isLoading } = useQuery<ShowDetail>({
    queryKey: ['show', id],
    queryFn: async () => {
      const response = await mediaApi.getShow(showId)
      return response.data
    },
    enabled: !isNaN(showId),
  })

  const { data: seasonDetail, isLoading: seasonLoading } = useQuery<SeasonDetail>({
    queryKey: ['season', id, selectedSeason],
    queryFn: async () => {
      const response = await mediaApi.getSeason(showId, selectedSeason!)
      return response.data
    },
    enabled: !!selectedSeason && !isNaN(showId) && show?.media_type !== 'movie',
  })

  const toggleAnimeMutation = useMutation({
    mutationFn: (isAnime: boolean) =>
      mediaApi.updateShow(showId, { is_anime: isAnime, anime_source: isAnime ? 'manual' : undefined }),
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
        <p className="text-gray-500">Title not found</p>
        <Link to="/library" className="text-orange-500 hover:underline mt-2 inline-block">
          Back to library
        </Link>
      </div>
    )
  }

  const badge = MEDIA_TYPE_BADGE[show.media_type] || MEDIA_TYPE_BADGE.tv
  const isMovie = show.media_type === 'movie'

  function renderSummary() {
    if (isMovie) {
      const count = show!.media_files?.length || show!.file_count || 0
      return `${count} file${count !== 1 ? 's' : ''}`
    }
    return `${show!.season_count} season${show!.season_count !== 1 ? 's' : ''} • ${show!.episode_count} episode${show!.episode_count !== 1 ? 's' : ''}`
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start gap-4">
        <Link
          to="/library"
          className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
        >
          <ArrowLeft className="w-5 h-5 text-gray-500" />
        </Link>
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
              {show.title}
            </h1>
            <span className={`px-2 py-0.5 text-xs font-medium rounded ${badge.classes}`}>
              {badge.label}
            </span>
          </div>
          <p className="text-gray-500 dark:text-gray-400 mt-1">
            {renderSummary()}
            {show.issues_count > 0 && (
              <span className="text-red-500 ml-2">
                • {show.issues_count} issue{show.issues_count !== 1 ? 's' : ''}
              </span>
            )}
          </p>
        </div>
        {/* Only show anime toggle for TV shows */}
        {show.media_type === 'tv' && (
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
        )}
      </div>

      {/* Content — Movies: flat file list, TV/Anime: season layout */}
      {isMovie ? (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4">
          <h2 className="font-semibold text-gray-900 dark:text-white mb-4">Files</h2>
          {show.media_files && show.media_files.length > 0 ? (
            <div className="space-y-3 max-h-[600px] overflow-y-auto">
              {show.media_files.map((file) => (
                <FileRow key={file.id} file={file} showEpisodeNumber={false} />
              ))}
            </div>
          ) : (
            <p className="text-gray-500 dark:text-gray-400 text-center py-8">
              No files found
            </p>
          )}
        </div>
      ) : (
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
              {show.seasons.length === 0 && (
                <p className="text-gray-500 dark:text-gray-400 text-center py-4 text-sm">
                  No seasons found
                </p>
              )}
            </div>
          </div>

          {/* Episode List */}
          <div className="lg:col-span-2 bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4">
            <h2 className="font-semibold text-gray-900 dark:text-white mb-4">
              {selectedSeason ? `Season ${selectedSeason} Episodes` : 'Select a season'}
            </h2>
            {seasonLoading ? (
              <div className="flex items-center justify-center py-8">
                <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-orange-500"></div>
              </div>
            ) : seasonDetail ? (
              <div className="space-y-3 max-h-[500px] overflow-y-auto">
                {seasonDetail.media_files.map((file) => (
                  <FileRow key={file.id} file={file} showEpisodeNumber={true} />
                ))}
              </div>
            ) : (
              <p className="text-gray-500 dark:text-gray-400 text-center py-8">
                Click a season to view episodes
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
