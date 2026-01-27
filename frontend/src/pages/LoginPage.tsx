import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Tv, Loader2 } from 'lucide-react'
import { useAuth } from '../hooks/useAuth'
import { authApi } from '../api/client'

export default function LoginPage() {
  const { isAuthenticated, login } = useAuth()
  const navigate = useNavigate()
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pinId, setPinId] = useState<number | null>(null)

  // Redirect if already authenticated
  useEffect(() => {
    if (isAuthenticated) {
      navigate('/', { replace: true })
    }
  }, [isAuthenticated, navigate])

  // Poll for Plex authorization
  const pollForAuth = useCallback(async (id: number) => {
    let attempts = 0
    const maxAttempts = 60 // 5 minutes with 5-second intervals

    const poll = async () => {
      try {
        const response = await authApi.completeLogin(id)
        await login(response.data.access_token)
        navigate('/', { replace: true })
      } catch (err: unknown) {
        attempts++
        if (attempts < maxAttempts) {
          // PIN not yet authorized, keep polling
          setTimeout(poll, 5000)
        } else {
          setError('Authorization timed out. Please try again.')
          setIsLoading(false)
          setPinId(null)
        }
      }
    }

    poll()
  }, [login, navigate])

  const handlePlexLogin = async () => {
    setIsLoading(true)
    setError(null)

    try {
      const response = await authApi.initiateLogin()
      const { pin_id, auth_url } = response.data

      setPinId(pin_id)

      // Open Plex auth in a new window
      const authWindow = window.open(
        auth_url,
        'plex-auth',
        'width=600,height=700,menubar=no,toolbar=no'
      )

      // Start polling for authorization
      pollForAuth(pin_id)

      // Also check if window closed without completing auth
      const checkWindowClosed = setInterval(() => {
        if (authWindow?.closed && pinId === pin_id) {
          // Window closed, but we're still polling - that's fine
          clearInterval(checkWindowClosed)
        }
      }, 1000)
    } catch (err) {
      console.error('Login error:', err)
      setError('Failed to initiate Plex login. Please try again.')
      setIsLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 flex items-center justify-center p-4">
      <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl p-8 w-full max-w-md">
        {/* Logo */}
        <div className="flex flex-col items-center mb-8">
          <div className="w-16 h-16 bg-orange-500 rounded-2xl flex items-center justify-center mb-4">
            <Tv className="w-10 h-10 text-white" />
          </div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            CineAudit Pro
          </h1>
          <p className="text-gray-500 dark:text-gray-400 mt-2 text-center">
            Media audio track scanner with Plex integration
          </p>
        </div>

        {/* Error message */}
        {error && (
          <div className="mb-6 p-4 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-lg">
            <p className="text-sm text-red-700 dark:text-red-400">{error}</p>
          </div>
        )}

        {/* Login button */}
        <button
          onClick={handlePlexLogin}
          disabled={isLoading}
          className="w-full flex items-center justify-center gap-3 px-6 py-4 bg-[#e5a00d] hover:bg-[#f5b82e] disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold rounded-xl transition-colors"
        >
          {isLoading ? (
            <>
              <Loader2 className="w-5 h-5 animate-spin" />
              <span>Waiting for authorization...</span>
            </>
          ) : (
            <>
              <svg className="w-6 h-6" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm-2-3.5l6-4.5-6-4.5v9z" />
              </svg>
              <span>Sign in with Plex</span>
            </>
          )}
        </button>

        {isLoading && (
          <p className="mt-4 text-sm text-gray-500 dark:text-gray-400 text-center">
            Complete authorization in the popup window
          </p>
        )}

        {/* Features */}
        <div className="mt-8 pt-6 border-t border-gray-200 dark:border-gray-700">
          <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-4">
            What you can do:
          </h3>
          <ul className="space-y-2 text-sm text-gray-600 dark:text-gray-400">
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 bg-orange-500 rounded-full"></span>
              Scan media files across multiple locations
            </li>
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 bg-orange-500 rounded-full"></span>
              Identify missing audio tracks (English, Japanese)
            </li>
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 bg-orange-500 rounded-full"></span>
              Sync metadata from your Plex server
            </li>
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 bg-orange-500 rounded-full"></span>
              Export reports to CSV or JSON
            </li>
          </ul>
        </div>
      </div>
    </div>
  )
}
