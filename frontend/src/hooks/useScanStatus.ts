import { useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { scanApi } from '../api/client'
import { refreshLibrary } from '../api/cache'
import type { ScanStatus } from '../types'

// Cache ownership keeps the completion marker scoped to the signed-in session.
const refreshedCompletions = new WeakMap<object, string>()

export function useScanStatus() {
  const queryClient = useQueryClient()
  const query = useQuery<ScanStatus>({
    queryKey: ['scanStatus'],
    queryFn: async () => (await scanApi.getStatus()).data,
    refetchInterval: (query) => query.state.data?.is_running ? 2000 : 10000,
  })
  const status = query.data
  const cache = queryClient.getQueryCache()
  useEffect(() => {
    if (!status || status.is_running || !status.finished_at) return
    const marker = `${status.started_at}:${status.finished_at}`
    // Use the query object, which is removed on logout, rather than a global user marker.
    const scanQuery = cache.find({ queryKey: ['scanStatus'], exact: true })
    if (!scanQuery || refreshedCompletions.get(scanQuery) === marker) return
    refreshedCompletions.set(scanQuery, marker)
    void refreshLibrary(queryClient)
  }, [status, cache, queryClient])
  return query
}
