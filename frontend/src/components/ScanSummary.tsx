import type { ScanStatus } from '../types'
import { formatServerDate } from '../utils/dates'

const labels: Record<ScanStatus['outcome'], string> = {
  idle: '', running: 'Scan in progress', completed: 'Scan completed',
  completed_with_errors: 'Scan completed with errors', cancelled: 'Scan cancelled', failed: 'Scan failed',
}

export default function ScanSummary({ status }: { status?: ScanStatus }) {
  if (!status || status.outcome === 'idle') return null
  return (
    <section aria-label="Scan status" className="space-y-3 p-4 border border-orange-200 dark:border-orange-800 bg-orange-50 dark:bg-orange-900/20 rounded-xl">
      <div role="status" aria-live="polite">
        <h2 className="font-semibold text-gray-900 dark:text-white">{status.job_status === 'interrupted' ? 'Scan interrupted by application restart' : status.job_status === 'queued' ? 'Scan queued' : labels[status.outcome]}</h2>
        {status.cancel_requested && status.is_running && <p>Cancellation requested; stopping safely…</p>}
        <p className="text-sm text-gray-700 dark:text-gray-300">
          {status.files_scanned} / {status.files_total} files processed · {status.files_removed} missing records removed
        </p>
        {status.is_running && <p className="text-sm break-words">{status.current_file || 'Discovering files…'}</p>}
        {!status.is_running && status.finished_at && (
          <p className="text-sm text-gray-600 dark:text-gray-400">Finished {formatServerDate(status.finished_at)}</p>
        )}
      </div>
      {status.is_running && <progress aria-label="Scan progress" value={status.files_scanned} max={Math.max(status.files_total, 1)} className="w-full" />}
      {(['errors', 'warnings'] as const).map((kind) => {
        const count = kind === 'errors' ? status.error_count : status.warning_count
        if (!count) return null
        return (
          <details key={kind} className="text-sm text-gray-800 dark:text-gray-200">
            <summary className="cursor-pointer font-medium">{count} scan {kind}</summary>
            <ul className="mt-2 space-y-1 break-words max-h-64 overflow-auto" aria-label={`Scan ${kind}`}>
              {status[kind].slice(0, 50).map((message, index) => <li key={index}>{message}</li>)}
            </ul>
            {count > 50 && <p>Showing the first 50 {kind}.</p>}
          </details>
        )
      })}
    </section>
  )
}
