import { isAxiosError } from 'axios'

export function apiError(error: unknown, fallback: string): string {
  if (!isAxiosError(error)) return fallback
  const detail = error.response?.data?.detail
  const errors = Array.isArray(detail) ? detail : detail?.errors ?? error.response?.data?.errors
  const messages = Array.isArray(errors) ? errors.map((item: string | { msg?: unknown }) => typeof item === 'string' ? item : item.msg).filter((msg): msg is string => typeof msg === 'string') : []
  return messages.length ? messages.join('; ') : typeof detail === 'string' ? detail : typeof detail?.message === 'string' ? detail.message : fallback
}
