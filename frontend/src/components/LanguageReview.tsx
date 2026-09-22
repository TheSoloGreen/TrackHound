import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { mediaApi } from '../api/client'
import { apiError } from '../api/errors'
import { refreshLibrary } from '../api/cache'
import type { MediaFile } from '../types'

export default function LanguageReview({ file }: { file: MediaFile }) {
  const [note, setNote] = useState(file.language_review_note || '')
  const [saved, setSaved] = useState(file.language_review_note || '')
  const client = useQueryClient()
  const save = useMutation({
    mutationFn: () => mediaApi.updateLanguageReview(file.id, note),
    onSuccess: (_data, _variables, _context) => { setSaved(note); return refreshLibrary(client) },
  })
  return <form onSubmit={(event) => { event.preventDefault(); save.mutate() }} className="space-y-2 border-t border-gray-300 dark:border-gray-600 pt-3">
    <label htmlFor={`language-review-${file.id}`} className="block text-sm font-medium">Your language review note</label>
    <p className="text-xs text-gray-500 dark:text-gray-400">Record what you verified by listening. This catalog note survives rescans; it does not change media tags or dismiss detected issues. Clear and save to remove it.</p>
    <textarea id={`language-review-${file.id}`} value={note} maxLength={2000} disabled={save.isPending}
      onChange={(event) => setNote(event.target.value)} rows={2}
      className="block w-full rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 p-2 text-sm" />
    <button type="submit" disabled={save.isPending || note === saved} className="rounded border px-3 py-1 text-sm disabled:opacity-50">{save.isPending ? 'Saving note…' : 'Save review note'}</button>
    {save.isError && <p role="alert" className="text-sm text-red-600">{apiError(save.error, 'Could not save note. Please try again.')}</p>}
    {save.isSuccess && note === saved && <p role="status" className="text-sm">Review note saved.</p>}
  </form>
}
