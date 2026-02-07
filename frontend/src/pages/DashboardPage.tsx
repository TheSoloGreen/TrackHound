import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Layers,
  Film,
  Tv,
  AlertTriangle,
  Play,
  Square,
  RefreshCw,
  FileVideo,
  Sparkles,
} from 'lucide-react'
import { mediaApi, scanApi } from '../api/client'
import type { DashboardStats, ScanStatus } from '../types'

function StatCard({
  icon: Icon,
  label,
  value,
  color = 'blue',
}: {
  icon: React.ElementType
  label: string
  value: number | string
  color?: 'blue' | 'green' | 'orange' | 'red' | 'purple'
}) {
  const colors = {
    blue: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
    green: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
    orange: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400',
    red: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
    purple: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl p-6 shadow-sm border border-gray-200 dark:border-gray-700">
      <div className="flex items-center gap-4">
        <div className={`p-3 rounded-lg ${colors[color]}`}>
          <Icon className="w-6 h-6" />
        </div>
        <div>
          <p className="text-sm text-gray-500 dark:text-gray-400">{label}</p>
          <p className="text-2xl font-bold text-gray-900 dark:text-white">{value}</p>
        </div>
      </div>
    </div>
  )
}

export default function DashboardPage() {
  const queryClient = useQueryClient()

  const { data: stats, isLoading: statsLoading, error: statsError } = useQuery<DashboardStats>({
    queryKey: ['stats'],
    queryFn: async () => {
      const response = await mediaApi.getStats()
      return response.data
    },
  })

  const { data: scanStatus } = useQuery<ScanStatus>({
    queryKey: ['scanStatus'],
    queryFn: async () => {
      const response = await scanApi.getStatus()
      return response.data
    },
    refetchInterval: (query) => {
      return query.state.data?.is_running ? 2000 : 10000
    },
  })

  const startScan = useMutation({
    mutationFn: () => scanApi.start({ incremental: true }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scanStatus'] })
    },
    onError: () => {
      queryClient.invalidateQueries({ queryKey: ['scanStatus'] })
    },
  })

  const cancelScan = useMutation({
    mutationFn: () => scanApi.cancel(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scanStatus'] })
    },
    onError: () => {
      queryClient.invalidateQueries({ queryKey: ['scanStatus'] })
    },
  })

  const isScanning = scanStatus?.is_running

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Dashboard</h1>
          <p className="text-gray-500 dark:text-gray-400 mt-1">
            Overview of your media library audio tracks
          </p>
        </div>
        <div className="flex gap-2">
          {isScanning ? (
            <button
              onClick={() => cancelScan.mutate()}
              disabled={cancelScan.isPending}
              className="flex items-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white rounded-lg transition-colors"
            >
              <Square className="w-4 h-4" />
              Cancel Scan
            </button>
          ) : (
            <button
              onClick={() => startScan.mutate()}
              disabled={startScan.isPending}
              className="flex items-center gap-2 px-4 py-2 bg-orange-500 hover:bg-orange-600 disabled:opacity-50 text-white rounded-lg transition-colors"
            >
              <Play className="w-4 h-4" />
              Start Scan
            </button>
          )}
        </div>
      </div>

      {/* Scan Status */}
      {isScanning && scanStatus && (
        <div className="bg-orange-50 dark:bg-orange-900/20 border border-orange-200 dark:border-orange-800 rounded-xl p-4">
          <div className="flex items-center gap-3 mb-3">
            <RefreshCw className="w-5 h-5 text-orange-600 dark:text-orange-400 animate-spin" />
            <span className="font-medium text-orange-800 dark:text-orange-300">
              Scan in progress...
            </span>
          </div>
          <div className="space-y-2">
            <div className="flex justify-between text-sm">
              <span className="text-orange-700 dark:text-orange-400">
                {scanStatus.current_file || 'Starting...'}
              </span>
              <span className="text-orange-700 dark:text-orange-400">
                {scanStatus.files_scanned} / {scanStatus.files_total || '?'}
              </span>
            </div>
            <div className="w-full bg-orange-200 dark:bg-orange-800 rounded-full h-2">
              <div
                className="bg-orange-500 h-2 rounded-full transition-all duration-300"
                style={{
                  width: `${scanStatus.files_total ? (scanStatus.files_scanned / scanStatus.files_total) * 100 : 0}%`,
                }}
              />
            </div>
          </div>
        </div>
      )}

      {/* Error message */}
      {statsError && (
        <div className="p-4 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-lg">
          <p className="text-sm text-red-700 dark:text-red-400">Failed to load dashboard stats. Please try again.</p>
        </div>
      )}

      {/* Scan error messages */}
      {(startScan.isError || cancelScan.isError) && (
        <div className="p-4 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-lg">
          <p className="text-sm text-red-700 dark:text-red-400">
            {startScan.isError ? 'Failed to start scan.' : 'Failed to cancel scan.'} Please try again.
          </p>
        </div>
      )}

      {/* Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          icon={Layers}
          label="Total Titles"
          value={statsLoading ? '...' : stats?.total_titles || 0}
          color="blue"
        />
        <StatCard
          icon={FileVideo}
          label="Total Files"
          value={statsLoading ? '...' : stats?.total_files || 0}
          color="green"
        />
        <StatCard
          icon={AlertTriangle}
          label="Files with Issues"
          value={statsLoading ? '...' : stats?.total_files_with_issues || 0}
          color="red"
        />
        <StatCard
          icon={Sparkles}
          label="Anime Titles"
          value={statsLoading ? '...' : stats?.anime_count || 0}
          color="purple"
        />
      </div>

      {/* Content Breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Library Breakdown */}
        <div className="bg-white dark:bg-gray-800 rounded-xl p-6 shadow-sm border border-gray-200 dark:border-gray-700">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
            Library Breakdown
          </h2>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Film className="w-4 h-4 text-blue-500" />
                <span className="text-gray-600 dark:text-gray-400">Movies</span>
              </div>
              <span className="font-semibold text-gray-900 dark:text-white">
                {stats?.movie_count || 0}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Tv className="w-4 h-4 text-emerald-500" />
                <span className="text-gray-600 dark:text-gray-400">TV Shows</span>
              </div>
              <span className="font-semibold text-gray-900 dark:text-white">
                {stats?.tv_count || 0}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-purple-500" />
                <span className="text-gray-600 dark:text-gray-400">Anime</span>
              </div>
              <span className="font-semibold text-gray-900 dark:text-white">
                {stats?.anime_count || 0}
              </span>
            </div>
            <div className="h-4 flex rounded-full overflow-hidden bg-gray-200 dark:bg-gray-700">
              {stats && stats.total_titles > 0 && (
                <>
                  <div
                    className="bg-blue-500"
                    style={{
                      width: `${(stats.movie_count / stats.total_titles) * 100}%`,
                    }}
                  />
                  <div
                    className="bg-emerald-500"
                    style={{
                      width: `${(stats.tv_count / stats.total_titles) * 100}%`,
                    }}
                  />
                  <div
                    className="bg-purple-500"
                    style={{
                      width: `${(stats.anime_count / stats.total_titles) * 100}%`,
                    }}
                  />
                </>
              )}
            </div>
          </div>
        </div>

        {/* Audio Issues */}
        <div className="bg-white dark:bg-gray-800 rounded-xl p-6 shadow-sm border border-gray-200 dark:border-gray-700">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
            Audio Issues Summary
          </h2>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-gray-600 dark:text-gray-400">Missing English Audio</span>
              <span className="font-semibold text-red-600 dark:text-red-400">
                {stats?.missing_english_count || 0}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-gray-600 dark:text-gray-400">Missing Japanese Audio (Anime)</span>
              <span className="font-semibold text-red-600 dark:text-red-400">
                {stats?.missing_japanese_count || 0}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-gray-600 dark:text-gray-400">Missing Dual Audio (Anime)</span>
              <span className="font-semibold text-orange-600 dark:text-orange-400">
                {stats?.missing_dual_audio_count || 0}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Last Scan Info */}
      {stats?.last_scan && (
        <div className="text-sm text-gray-500 dark:text-gray-400 text-center">
          Last scan: {new Date(stats.last_scan).toLocaleString()}
        </div>
      )}
    </div>
  )
}
