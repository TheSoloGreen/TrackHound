import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Layers,
  Film,
  Tv,
  AlertTriangle,
  Play,
  Square,
  FileVideo,
  Sparkles,
} from 'lucide-react'
import { mediaApi, scanApi } from '../api/client'
import type { DashboardStats, ScanStatus } from '../types'
import { useScanStatus } from '../hooks/useScanStatus'
import ScanSummary from '../components/ScanSummary'
import { useState } from 'react'

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

  const { data: scanStatus } = useScanStatus()
  const [incremental, setIncremental] = useState(true)

  const startScan = useMutation({
    mutationFn: () => scanApi.start({ incremental }),
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: ['scanStatus'] })
      const previousStatus = queryClient.getQueryData<ScanStatus>(['scanStatus'])

      queryClient.setQueryData<ScanStatus>(['scanStatus'], {
        is_running: true, outcome: 'running', current_location: null,
        files_scanned: 0, files_total: 0, files_removed: 0, current_file: 'Starting…',
        started_at: null, finished_at: null, errors: [], warnings: [], error_count: 0, warning_count: 0,
      })

      return { previousStatus }
    },
    onSuccess: (response) => {
      queryClient.setQueryData(['scanStatus'], response.data)
      queryClient.invalidateQueries({ queryKey: ['scanStatus'] })
    },
    onError: (_error, _variables, context) => {
      if (context?.previousStatus) {
        queryClient.setQueryData(['scanStatus'], context.previousStatus)
      }
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
        <div className="flex gap-2 items-center">
          {!isScanning && <label className="text-sm text-gray-700 dark:text-gray-300">
            <input type="checkbox" checked={!incremental} onChange={(event) => setIncremental(!event.target.checked)} className="mr-2" />
            Full scan
          </label>}
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

      <ScanSummary status={scanStatus} />

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
            Audio Issues Summary by Media Type
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-gray-500 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700">
                  <th className="py-2 pr-2">Issue</th>
                  <th className="py-2 px-2">Movies</th>
                  <th className="py-2 px-2">TV</th>
                  <th className="py-2 px-2">Anime</th>
                  <th className="py-2 pl-2 text-right">Total</th>
                </tr>
              </thead>
              <tbody className="text-gray-700 dark:text-gray-300">
                <tr className="border-b border-gray-100 dark:border-gray-700/60">
                  <td className="py-2 pr-2">Missing English Audio</td>
                  <td className="py-2 px-2">{stats?.missing_english_movies_count || 0}</td>
                  <td className="py-2 px-2">{stats?.missing_english_tv_count || 0}</td>
                  <td className="py-2 px-2">{stats?.missing_english_anime_count || 0}</td>
                  <td className="py-2 pl-2 text-right font-semibold text-red-600 dark:text-red-400">{stats?.missing_english_count || 0}</td>
                </tr>
                <tr className="border-b border-gray-100 dark:border-gray-700/60">
                  <td className="py-2 pr-2">Missing Japanese Audio</td>
                  <td className="py-2 px-2">{stats?.missing_japanese_movies_count || 0}</td>
                  <td className="py-2 px-2">{stats?.missing_japanese_tv_count || 0}</td>
                  <td className="py-2 px-2">{stats?.missing_japanese_anime_count || 0}</td>
                  <td className="py-2 pl-2 text-right font-semibold text-red-600 dark:text-red-400">{stats?.missing_japanese_count || 0}</td>
                </tr>
                <tr>
                  <td className="py-2 pr-2">Missing Dual Audio</td>
                  <td className="py-2 px-2">{stats?.missing_dual_audio_movies_count || 0}</td>
                  <td className="py-2 px-2">{stats?.missing_dual_audio_tv_count || 0}</td>
                  <td className="py-2 px-2">{stats?.missing_dual_audio_anime_count || 0}</td>
                  <td className="py-2 pl-2 text-right font-semibold text-orange-600 dark:text-orange-400">{stats?.missing_dual_audio_count || 0}</td>
                </tr>
              </tbody>
            </table>
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
