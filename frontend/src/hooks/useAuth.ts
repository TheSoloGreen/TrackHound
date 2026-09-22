import { useState, useEffect, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { authApi } from '../api/client'
import type { User } from '../types'

export function useAuth() {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('token'))
  const queryClient = useQueryClient()

  const policy = useQuery({ queryKey: ['authConfig'], queryFn: async () => (await authApi.getConfig()).data,
    retry: false, staleTime: 0, refetchInterval: 15000 })
  const authRequired = policy.data?.mode !== 'none'

  const { data: user, isLoading, error } = useQuery<User>({
    queryKey: ['currentUser'],
    queryFn: async () => {
      const response = await authApi.getCurrentUser()
      return response.data
    },
    enabled: !!policy.data && (!!token || !authRequired),
    retry: false,
  })

  const login = useCallback(async (accessToken: string) => {
    localStorage.setItem('token', accessToken)
    setToken(accessToken)
    const response = await authApi.getCurrentUser()
    const previous = queryClient.getQueryData<User>(['currentUser'])
    if (previous && previous.id !== response.data.id) queryClient.clear()
    queryClient.setQueryData(['currentUser'], response.data)
    window.dispatchEvent(new StorageEvent('storage', { key: 'token', newValue: accessToken }))
  }, [queryClient])

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } catch {
      // Ignore errors on logout
    }
    localStorage.removeItem('token')
    setToken(null)
    queryClient.clear()
    window.dispatchEvent(new StorageEvent('storage', { key: 'token', newValue: null }))
  }, [queryClient])

  // Check for token changes (from other tabs or 401 interceptor)
  useEffect(() => {
    const handleStorageChange = (e: StorageEvent) => {
      if (e.key === 'token' || e.key === null) {
        const newToken = localStorage.getItem('token')
        setToken(newToken)
      }
    }

    window.addEventListener('storage', handleStorageChange)
    return () => window.removeEventListener('storage', handleStorageChange)
  }, [])

  return {
    user,
    isAuthenticated: !!user && (!authRequired || !!token),
    authRequired,
    isLoading: policy.isLoading || (isLoading && (!!token || !authRequired)),
    error: policy.error || error,
    login,
    logout,
  }
}
