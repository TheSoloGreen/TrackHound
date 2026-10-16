import { useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { jobsApi } from '../api/client'
import { refreshLibrary } from '../api/cache'
import type { Job } from '../types'

const completions = new WeakMap<object, string>()

export function useJobs(offset = 0) {
  const client = useQueryClient()
  const query = useQuery<{ items: Job[]; total: number; latest_finished_at?: string | null }>({
    queryKey: ['jobs', offset],
    queryFn: async () => (await jobsApi.list(offset)).data,
    refetchInterval: (query) => query.state.data?.items.some((job) => ['queued', 'running'].includes(job.status)) ? 2000 : 10000,
  })
  useEffect(() => {
    if (!query.data) return
    const marker = query.data.latest_finished_at || query.data.items.filter((job) => job.finished_at).map((job) => `${job.id}:${job.finished_at}`).join(',')
    const cacheQuery = client.getQueryCache().find({ queryKey: ['jobs', offset], exact: true })
    if (!cacheQuery || !marker || completions.get(cacheQuery) === marker) return
    completions.set(cacheQuery, marker)
    void refreshLibrary(client)
    void client.invalidateQueries({ queryKey: ['scanStatus'] })
  }, [query.data, client, offset])
  return query
}
