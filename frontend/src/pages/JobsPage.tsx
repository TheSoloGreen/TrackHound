import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { jobsApi } from '../api/client'
import { apiError } from '../api/errors'
import { useJobs } from '../hooks/useJobs'
import type { Job } from '../types'

const labels: Record<Job['kind'], string> = {
  scan: 'Library scan', rescan_file: 'File rescan', rescan_show: 'Title rescan',
  default_audio: 'Default audio edit', remove_audio: 'Audio track removal',
  reevaluate: 'Cached audio reevaluation',
}
const date = (value: string) => new Date(value.endsWith('Z') || /[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`).toLocaleString()

export default function JobsPage() {
  const [offset, setOffset] = useState(0)
  const client = useQueryClient()
  const { data, isLoading, error } = useJobs(offset)
  const cancel = useMutation({ mutationFn: jobsApi.cancel,
    onSuccess: () => client.invalidateQueries({ queryKey: ['jobs'] }),
  })
  return <div className="space-y-6 text-gray-900 dark:text-gray-100">
    <h1 className="text-2xl font-bold">Jobs</h1>
    <p className="text-sm text-gray-600 dark:text-gray-400">Work continues after you leave the page. The latest 200 finished jobs are retained alongside queued and running work. Interrupted jobs are never automatically retried.</p>
    {(error || cancel.isError) && <p role="alert" className="text-red-600">{apiError(error || cancel.error, 'Could not load or update jobs. Please retry.')}</p>}
    {isLoading && <p>Loading jobs…</p>}
    {data?.items.length === 0 && <p>No jobs yet.</p>}
    {data?.items.map((job) => <section key={job.id} id={`job-${job.id}`} aria-label={`Job #${job.id}`} className="p-4 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 space-y-2 break-words">
      <h2 className="font-semibold">#{job.id} · {labels[job.kind]} · {job.status.replaceAll('_', ' ')}</h2>
      <p className="text-sm text-gray-500">Queued {date(job.created_at)}{job.finished_at && ` · Finished ${date(job.finished_at)}`}</p>
      {job.progress.files_total !== undefined && <p>{job.progress.files_scanned || 0} / {job.progress.files_total} files processed</p>}
      {job.progress.current_file && job.status === 'running' && <p>{job.progress.current_file}</p>}
      {job.result.message && <p>{job.result.message}</p>}
      {job.kind === 'reevaluate' && job.result.policy_revision && <p className="text-sm">{job.result.reevaluated || 0} reevaluated · {job.result.unchanged || 0} already current · {job.result.needs_scan || 0} need a physical scan</p>}
      {job.target_file_id && <Link className="underline text-orange-600" to={`/files?file_id=${job.target_file_id}&expanded=${job.target_file_id}`}>Review file #{job.target_file_id}</Link>}
      {job.target_show_id && <Link className="underline text-orange-600" to={`/library/${job.target_show_id}`}>Review title #{job.target_show_id}</Link>}
      {job.result.backup_path && <p>Original backup: {job.result.backup_path}</p>}
      {job.error && <p role="alert" className="text-red-600 dark:text-red-400">{job.error}</p>}
      {(['errors', 'warnings'] as const).map((kind) => !!job.progress[kind]?.length && <details key={kind}>
        <summary>{kind === 'errors' ? 'Errors' : 'Warnings'} (first 50)</summary>
        <ul className="space-y-1 text-sm">{job.progress[kind]?.map((message, index) => <li key={index}>{message}</li>)}</ul>
      </details>)}
      {job.cancel_requested && job.status === 'running' && <p role="status">Cancellation requested; waiting for the current operation to stop safely.</p>}
      {(job.status === 'queued' || job.status === 'running' && !['default_audio', 'remove_audio'].includes(job.kind)) && <button
        className="px-3 py-1 rounded border border-red-400 text-red-600 disabled:opacity-50" disabled={cancel.isPending || job.cancel_requested}
        onClick={() => cancel.mutate(job.id)}>Cancel job #{job.id}</button>}
      {job.status === 'running' && ['default_audio', 'remove_audio'].includes(job.kind) && <p className="text-sm">Media edit in progress. Cancellation is disabled until the write and verification finish.</p>}
    </section>)}
    <div className="flex gap-3">
      <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))} className="disabled:opacity-40">Previous</button>
      <button disabled={!data || offset + 50 >= data.total} onClick={() => setOffset(offset + 50)} className="disabled:opacity-40">Next</button>
    </div>
  </div>
}
