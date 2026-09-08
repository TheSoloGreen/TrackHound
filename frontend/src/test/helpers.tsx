import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import type { MediaFile, ScanStatus, UserSettings } from '../types'

export function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity, gcTime: Infinity }, mutations: { retry: false } } })
}
export function renderWithClient(children: ReactNode, client = makeClient()) {
  return { ...render(<QueryClientProvider client={client}>{children}</QueryClientProvider>), client }
}
export function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
export const settings: UserSettings = {
  audio_preferences: { require_english_non_anime: true, require_japanese_anime: true,
    require_dual_audio_anime: true, check_default_track: true, preferred_codecs: [],
    auto_fix_english_default_non_anime: false, audio_track_keep_languages: ['ja', 'und'] },
  anime_detection: { use_plex_genres: true, anime_folder_keywords: ['anime'] },
  file_extensions: ['.mkv'],
}
export const runningScan: ScanStatus = {
  is_running: true, outcome: 'running', started_at: '2026-09-08T16:00:00Z', finished_at: null,
  current_location: '/media', current_file: 'movie.mkv', files_scanned: 0, files_total: 2,
  files_removed: 0, errors: [], warnings: [], error_count: 0, warning_count: 0,
}
export const mediaFile: MediaFile = {
  id: 1, filename: 'movie.mkv', file_path: '/media/movie.mkv', episode_number: null, episode_title: null,
  file_size: 1024, container_format: 'Matroska', duration_ms: 1000, last_scanned: '2026-09-08T16:00:00',
  has_issues: false, issue_details: null,
  edit_capabilities: { set_default_audio: true, remove_audio_tracks: true, default_audio_reason: null, track_removal_reason: null },
  audio_tracks: [
    { language: 'en', language_raw: 'eng' }, { language: 'ja', language_raw: 'jpn' },
    { language: null, language_raw: null },
  ].map((language, index) => ({ id: index + 1, track_index: index + 1, ...language,
    codec: 'AAC', channels: 2, channel_layout: 'stereo', bitrate: null, is_default: index === 0, is_forced: false, title: null })),
}
