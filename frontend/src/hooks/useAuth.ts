import { useState, useEffect, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { authApi } from '../api/client'
import type { User } from '../types'

export function useAuth() {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('token'))
  const queryClient = useQueryClient()

  const { data: user, isLoading, error } = useQuery<User>({
    queryKey: ['currentUser'],
    queryFn: async () => {
      const response = await authApi.getCurrentUser()
      return response.data
    },
    enabled: !!token,
    retry: false,
  })

  const login = useCallback(async (accessToken: string) => {
    localStorage.setItem('token', accessToken)
    setToken(accessToken)
    await queryClient.invalidateQueries({ queryKey: ['currentUser'] })
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
    isAuthenticated: !!token && !!user,
    isLoading: isLoading && !!token,
    error,
    login,
    logout,
  }
}
