'use client'

import { useEffect, useState } from 'react'
import { BookmarkMinus } from 'lucide-react'
import {
  fetchFavorites,
  toggleFavoriteMessage,
  FavoritesResponse,
} from '@/lib/api'

interface FavoritesViewProps {
  selectedUser: string | null
  isUserSelectionReady: boolean
}

export default function FavoritesView({
  selectedUser,
  isUserSelectionReady,
}: FavoritesViewProps) {
  const [favorites, setFavorites] = useState<FavoritesResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [removingId, setRemovingId] = useState<string | null>(null)

  useEffect(() => {
    const loadFavorites = async () => {
      if (!selectedUser || !isUserSelectionReady) {
        setFavorites(null)
        return
      }
      setLoading(true)
      setError(null)
      try {
        const data = await fetchFavorites(selectedUser)
        setFavorites(data)
      } catch (err) {
        setError(
          `Unable to load favorites${
            err instanceof Error ? `: ${err.message}` : ''
          }`
        )
      } finally {
        setLoading(false)
      }
    }
    loadFavorites()
  }, [selectedUser, isUserSelectionReady])

  const handleRemove = async (messageId: string) => {
    if (!selectedUser) return
    setRemovingId(messageId)
    try {
      await toggleFavoriteMessage(selectedUser, messageId, false)
      setFavorites((prev) =>
        prev
          ? {
              ...prev,
              favorites: prev.favorites.filter(
                (fav) => fav.message.id !== messageId
              ),
            }
          : prev
      )
    } catch (err) {
      setError(
        `Failed to remove favorite${
          err instanceof Error ? `: ${err.message}` : ''
        }`
      )
    } finally {
      setRemovingId(null)
    }
  }

  if (!selectedUser) {
    return (
      <div className="flex h-full items-center justify-center text-gray-500">
        Select a tester account from the sidebar to view favorites.
      </div>
    )
  }

  if (loading) {
    return (
      <div className="flex h-full flex-col items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900 mb-4"></div>
        <p className="text-gray-600">Loading favorites...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex h-full flex-col items-center justify-center text-red-600">
        <p className="mb-2">{error}</p>
      </div>
    )
  }

  const favItems = favorites?.favorites ?? []

  if (favItems.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center text-gray-500">
        <BookmarkMinus className="mb-3" size={32} />
        <p>No favorites yet.</p>
        <p className="text-sm mt-1">
          Mark interesting assistant responses as favorites to see them here.
        </p>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col p-6 overflow-hidden">
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">Favorites</h1>
        <p className="text-gray-600">
          Saved user questions and assistant responses for {selectedUser}.
        </p>
      </div>

      <div className="flex-1 overflow-y-auto space-y-4">
        {favItems.map((fav) => (
          <div
            key={fav.message.id}
            className="border border-gray-200 rounded-lg bg-white shadow-sm p-4 space-y-3"
          >
            {fav.question && (
              <div>
                <div className="text-sm font-semibold text-gray-700 mb-1">
                  Question
                </div>
                <p className="text-gray-900 whitespace-pre-wrap">
                  {fav.question}
                </p>
              </div>
            )}
            <div>
              <div className="text-sm font-semibold text-gray-700 mb-1">
                Assistant Response
              </div>
              <p className="text-gray-900 whitespace-pre-wrap">
                {fav.message.content}
              </p>
            </div>
            {fav.message.cypher && (
              <div className="text-xs text-gray-500">
                <span className="font-semibold">Cypher:</span>{' '}
                <code>{fav.message.cypher}</code>
              </div>
            )}
            <div className="flex justify-between items-center text-xs text-gray-500">
              <span>
                Saved:{' '}
                {new Date(fav.message.timestamp).toLocaleString(undefined, {
                  dateStyle: 'medium',
                  timeStyle: 'short',
                })}
              </span>
              <button
                onClick={() => handleRemove(fav.message.id)}
                className="text-red-500 hover:text-red-600 text-sm font-medium"
                disabled={removingId === fav.message.id}
              >
                {removingId === fav.message.id ? 'Removing...' : 'Remove'}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

