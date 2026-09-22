import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { useAuth } from './hooks/useAuth'
import Layout from './components/Layout'
import AccountPage from './pages/AccountPage'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import ShowsPage from './pages/ShowsPage'
import ShowDetailPage from './pages/ShowDetailPage'
import FilesPage from './pages/FilesPage'
import SettingsPage from './pages/SettingsPage'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading, user, authRequired } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-orange-500"></div>
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  if (authRequired !== false && user?.must_change_password && location.pathname !== "/account") return <Navigate to="/account" replace />

  return <>{children}</>
}

function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/*"
        element={
          <ProtectedRoute>
            <Layout>
              <Routes>
                <Route path="/" element={<DashboardPage />} />
                <Route path="/library" element={<ShowsPage />} />
                <Route path="/library/:id" element={<ShowDetailPage />} />
                {/* Redirect old /shows routes to /library */}
                <Route path="/shows" element={<Navigate to="/library" replace />} />
                <Route path="/shows/:id" element={<Navigate to="/library" replace />} />
                <Route path="/files" element={<FilesPage />} />
                <Route path="/account" element={<AccountPage />} />
                <Route path="/settings" element={<SettingsPage />} />
              </Routes>
            </Layout>
          </ProtectedRoute>
        }
      />
    </Routes>
  )
}

export default App
