'use client'

import { useEffect, useState } from 'react'
import ChatInterface from '@/components/ChatInterface'
import KnowledgeBase from '@/components/KnowledgeBase'
import FavoritesView from '@/components/FavoritesView'
import GraphInfo from '@/components/GraphInfo'
import Sidebar, { MenuOption } from '@/components/Sidebar'
import Login from '@/components/Login'

const AUTH_STORAGE_KEY = 'graphrag_authenticated_user'
const SESSION_DURATION_MS = 24 * 60 * 60 * 1000 // 24 hours in milliseconds

interface AuthData {
  username: string
  loginTimestamp: number
}

export default function Home() {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false)
  const [authenticatedUser, setAuthenticatedUser] = useState<string | null>(null)
  const [activeOption, setActiveOption] = useState<MenuOption>('chat')
  const [isChatProcessing, setIsChatProcessing] = useState(false)

  // Check for existing authentication on mount
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const storedAuth = localStorage.getItem(AUTH_STORAGE_KEY)
      if (storedAuth) {
        try {
          const authData: AuthData = JSON.parse(storedAuth)
          const now = Date.now()
          const timeSinceLogin = now - authData.loginTimestamp

          // Check if session is still valid (less than 24 hours old)
          if (timeSinceLogin < SESSION_DURATION_MS) {
            setAuthenticatedUser(authData.username)
            setIsAuthenticated(true)
          } else {
            // Session expired, clear it
            localStorage.removeItem(AUTH_STORAGE_KEY)
          }
        } catch (error) {
          // Invalid stored data, clear it
          localStorage.removeItem(AUTH_STORAGE_KEY)
        }
      }
    }
  }, [])

  const handleLogin = (username: string) => {
    if (typeof window !== 'undefined') {
      const authData: AuthData = {
        username,
        loginTimestamp: Date.now(),
      }
      localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(authData))
    }
    setAuthenticatedUser(username)
    setIsAuthenticated(true)
  }

  const handleLogout = () => {
    if (typeof window !== 'undefined') {
      localStorage.removeItem(AUTH_STORAGE_KEY)
    }
    setAuthenticatedUser(null)
    setIsAuthenticated(false)
  }

  // Show login screen if not authenticated
  if (!isAuthenticated) {
    return <Login onLogin={handleLogin} />
  }

  return (
    <main className="flex h-screen bg-slate-50 overflow-hidden">
      <Sidebar
        activeOption={activeOption}
        onOptionChange={setActiveOption}
        loggedInUser={authenticatedUser}
        onLogout={handleLogout}
      />

      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {activeOption === 'chat' && (
          <div className="flex-1 flex flex-col min-h-0 overflow-hidden p-6">
            <ChatInterface
              selectedUser={authenticatedUser}
              isUserSelectionReady={!!authenticatedUser}
              userLoadError={null}
              onProcessingChange={setIsChatProcessing}
            />
          </div>
        )}

        {activeOption === 'knowledge-base' && (
          <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
            <KnowledgeBase selectedTester={authenticatedUser} />
          </div>
        )}

        {activeOption === 'favorites' && (
          <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
            <FavoritesView
              selectedUser={authenticatedUser}
              isUserSelectionReady={!!authenticatedUser}
            />
          </div>
        )}

        {activeOption === 'graph-info' && (
          <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
            <GraphInfo />
          </div>
        )}

        {activeOption !== 'chat' &&
          activeOption !== 'knowledge-base' &&
          activeOption !== 'favorites' &&
          activeOption !== 'graph-info' && (
          <div className="flex-1 flex flex-col items-center justify-center bg-slate-50/50">
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 flex items-center justify-center mb-4 shadow-lg shadow-indigo-200/50">
              <span className="text-white text-xl font-bold">?</span>
            </div>
            <p className="text-gray-700 font-medium">Coming soon</p>
            <p className="text-sm text-gray-400 mt-1">This feature is under development.</p>
          </div>
        )}
      </div>
    </main>
  )
}

