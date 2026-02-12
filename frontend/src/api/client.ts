import axios from 'axios'

const API_BASE_URL = import.meta.env.VITE_API_URL || ''

export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Add auth token to requests
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Handle auth errors — clear token and dispatch a storage event
// so useAuth can react via React Router instead of a hard redirect
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      // Dispatch storage event so useAuth picks up the change
      window.dispatchEvent(new StorageEvent('storage', { key: 'token', newValue: null }))
    }
    return Promise.reject(error)
  }
)

// Auth API
export const authApi = {
  initiateLogin: () => api.get<{ pin_id: number; pin_code: string; auth_url: string }>('/api/auth/plex/login'),
  completeLogin: (pinId: number) => api.post<{ access_token: string }>(`/api/auth/plex/callback?pin_id=${pinId}`),
  getCurrentUser: () => api.get('/api/auth/me'),
  logout: () => api.post('/api/auth/logout'),
}

// Scan API
export const scanApi = {
  browse: (path?: string) => api.get('/api/scan/browse', { params: { path } }),
  getLocations: () => api.get('/api/scan/locations'),
  createLocation: (data: { path: string; label: string; media_type: string }) =>
    api.post('/api/scan/locations', data),
  updateLocation: (id: number, data: { label?: string; media_type?: string; enabled?: boolean }) =>
    api.patch(`/api/scan/locations/${id}`, data),
  deleteLocation: (id: number) => api.delete(`/api/scan/locations/${id}`),
  getStatus: () => api.get('/api/scan/status'),
  start: (data?: { location_ids?: number[]; incremental?: boolean }) => api.post('/api/scan/start', data || {}),
  cancel: () => api.post('/api/scan/cancel'),
}

// Media API
export const mediaApi = {
  getStats: () => api.get('/api/media/stats'),
  getShows: (params?: { page?: number; page_size?: number; media_type?: string; is_anime?: boolean; has_issues?: boolean; search?: string }) =>
    api.get('/api/media/shows', { params }),
  getShow: (id: number) => api.get(`/api/media/shows/${id}`),
  updateShow: (id: number, data: { media_type?: string; is_anime?: boolean; anime_source?: string }) =>
    api.patch(`/api/media/shows/${id}`, data),
  getSeason: (showId: number, seasonNumber: number) =>
    api.get(`/api/media/shows/${showId}/seasons/${seasonNumber}`),
  getFiles: (params?: { page?: number; page_size?: number; has_issues?: boolean; show_id?: number; search?: string }) =>
    api.get('/api/media/files', { params }),
  getFile: (id: number) => api.get(`/api/media/files/${id}`),
  updateDefaultAudio: (id: number, language: string) =>
    api.post(`/api/media/files/${id}/default-audio`, { language }),
  rescanFile: (id: number) => api.post(`/api/media/files/${id}/rescan`),
}

// Settings API
export const settingsApi = {
  get: () => api.get('/api/settings'),
  update: (data: object) => api.put('/api/settings', data),
  reset: () => api.delete('/api/settings'),
}
