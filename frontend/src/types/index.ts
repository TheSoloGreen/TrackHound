// User types
export interface User {
  id: number
  plex_username: string
  plex_email: string | null
  plex_thumb_url: string | null
  created_at: string
  last_login: string
}

// Media type union
export type MediaType = 'tv' | 'movie' | 'anime'

// Scan types
export interface ScanLocation {
  id: number
  path: string
  label: string
  media_type: MediaType
  enabled: boolean
  last_scanned: string | null
  file_count: number
  created_at: string
}

export interface DirectoryEntry {
  name: string
  path: string
}

export interface DirectoryBrowseResponse {
  current_path: string
  directories: DirectoryEntry[]
}

export interface ScanStatus {
  is_running: boolean
  current_location: string | null
  files_scanned: number
  files_total: number
  current_file: string | null
  started_at: string | null
  errors: string[]
}

// Audio track types
export interface AudioTrack {
  id: number
  track_index: number
  language: string | null
  language_raw: string | null
  codec: string | null
  channels: number | null
  channel_layout: string | null
  bitrate: number | null
  is_default: boolean
  is_forced: boolean
  title: string | null
}

// Media types
export interface MediaFile {
  id: number
  file_path: string
  filename: string
  episode_number: number | null
  episode_title: string | null
  file_size: number
  container_format: string | null
  duration_ms: number | null
  last_scanned: string
  has_issues: boolean
  issue_details: string | null
  audio_tracks: AudioTrack[]
}

export interface Season {
  id: number
  season_number: number
  episode_count: number
  issues_count: number
}

export interface SeasonDetail extends Season {
  media_files: MediaFile[]
}

export interface Show {
  id: number
  title: string
  media_type: MediaType
  is_anime: boolean
  anime_source: string | null
  thumb_url: string | null
  season_count: number
  episode_count: number
  file_count: number
  issues_count: number
  created_at: string
  updated_at: string
}

export interface ShowDetail extends Show {
  seasons: Season[]
  media_files: MediaFile[]
}

// Settings types
export interface AudioPreferences {
  require_english_non_anime: boolean
  require_japanese_anime: boolean
  require_dual_audio_anime: boolean
  check_default_track: boolean
  preferred_codecs: string[]
  auto_fix_english_default_non_anime: boolean
}

export interface AnimeDetectionSettings {
  use_plex_genres: boolean
  anime_folder_keywords: string[]
}

export interface UserSettings {
  audio_preferences: AudioPreferences
  anime_detection: AnimeDetectionSettings
  file_extensions: string[]
}

// Dashboard stats
export interface DashboardStats {
  total_titles: number
  total_files: number
  total_files_with_issues: number
  movie_count: number
  tv_count: number
  anime_count: number
  missing_english_count: number
  missing_japanese_count: number
  missing_dual_audio_count: number
  missing_english_movies_count: number
  missing_english_tv_count: number
  missing_english_anime_count: number
  missing_japanese_movies_count: number
  missing_japanese_tv_count: number
  missing_japanese_anime_count: number
  missing_dual_audio_movies_count: number
  missing_dual_audio_tv_count: number
  missing_dual_audio_anime_count: number
  last_scan: string | null
}

// Pagination
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  pages: number
}
