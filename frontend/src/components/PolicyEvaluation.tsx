import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { settingsApi } from '../api/client'
import { apiError } from '../api/errors'
import type { EvaluationStatus } from '../types'

export default function PolicyEvaluation() {
  const client = useQueryClient()
  const { data, error, isLoading, refetch } = useQuery<EvaluationStatus>({
    queryKey: ['audioEvaluation'], queryFn: async () => (await settingsApi.getEvaluation()).data,
    refetchInterval: (query) => ['queued', 'running'].includes(query.state.data?.latest_job?.status || '') ? 2000 : 10000,
  })
  const start = useMutation({ mutationFn: settingsApi.reevaluate,
    onSuccess: () => Promise.all(['audioEvaluation', 'jobs'].map((key) => client.invalidateQueries({ queryKey: [key] }))),
  })
  const job = data?.latest_job
  const active = job && ['queued', 'running'].includes(job.status)
  return <section aria-label="Audio policy status" className="p-6 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 space-y-3 text-gray-900 dark:text-gray-100">
    <h2 className="text-lg font-semibold">Cached audio policy</h2>
    <p className="text-sm text-gray-600 dark:text-gray-400">Refresh issue flags using saved tracks and existing title classifications. No media probes, Plex requests, or media edits are performed; last-scan dates are preserved.</p>
    {isLoading && <p>Loading policy status…</p>}
    {data && <>
      <p>{data.files_current} current · {data.files_pending} awaiting reevaluation · {data.files_needing_scan} need a physical scan</p>
      <p className="text-xs text-gray-500" title={data.policy_revision}>Policy revision: {data.policy_revision.slice(0, 12)}</p>
      {data.files_needing_scan > 0 && <p className="text-sm">A physical scan is needed for files without usable cached analysis. Cached results describe the last successful scan, not subsequent external file changes.</p>}
      {job && <p role="status">Job #{job.id}: {job.status.replaceAll('_', ' ')}. <Link to="/jobs" className="underline text-orange-600">View policy job</Link></p>}
    </>}
    <button onClick={() => start.mutate()} disabled={!data || !!active || start.isPending}
      className="px-4 py-2 rounded-lg bg-orange-500 text-white disabled:opacity-50">{start.isPending ? 'Queueing…' : 'Reevaluate cached audio'}</button>
    {error && <div role="alert"><p>{apiError(error, 'Could not load audio policy status.')}</p><button className="underline" onClick={() => void refetch()}>Retry policy status</button></div>}
    {start.isError && <p role="alert">{apiError(start.error, 'Could not queue reevaluation. Please retry.')}</p>}
  </section>
}
