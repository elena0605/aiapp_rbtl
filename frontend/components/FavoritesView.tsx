'use client'

import { useEffect, useState } from 'react'
import { BookmarkMinus, Star, Users, AlertCircle, RefreshCw } from 'lucide-react'
import CypherViewer from './CypherViewer'
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

  useEffect(() => {
    loadFavorites()
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      <div className="flex h-full flex-col items-center justify-center bg-slate-50/50 px-6">
        <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 flex items-center justify-center mb-4 shadow-lg shadow-indigo-200/50">
          <Users size={24} className="text-white" />
        </div>
        <p className="text-gray-700 font-medium text-center">No account selected</p>
        <p className="text-sm text-gray-400 mt-1.5 text-center max-w-xs">
          Select a tester account from the sidebar to view saved favorites.
        </p>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="flex h-full flex-col items-center justify-center bg-slate-50/50">
        <div className="animate-spin rounded-full h-8 w-8 border-2 border-indigo-200 border-t-indigo-500 mb-4"></div>
        <p className="text-gray-500 text-sm">Loading favorites&hellip;</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex h-full flex-col items-center justify-center bg-slate-50/50 px-6">
        <div className="bg-rose-50 border border-rose-100 rounded-2xl p-6 max-w-md text-center">
          <div className="w-12 h-12 rounded-xl bg-rose-100 flex items-center justify-center mx-auto mb-3">
            <AlertCircle size={22} className="text-rose-500" />
          </div>
          <p className="text-rose-700 text-sm font-medium mb-4">{error}</p>
          <button
            onClick={loadFavorites}
            className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-500 text-white text-sm font-medium rounded-xl hover:bg-indigo-600 transition-colors shadow-sm"
          >
            <RefreshCw size={15} />
            Retry
          </button>
        </div>
      </div>
    )
  }

  const favItems = favorites?.favorites ?? []

  if (favItems.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center bg-slate-50/50 px-6">
        <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 flex items-center justify-center mb-4 shadow-lg shadow-indigo-200/50">
          <BookmarkMinus size={24} className="text-white" />
        </div>
        <p className="text-gray-700 font-medium">No favorites yet</p>
        <p className="text-sm text-gray-400 mt-1.5 text-center max-w-xs">
          Mark interesting assistant responses as favorites to collect them here.
        </p>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col p-6 md:p-8 overflow-hidden bg-slate-50/30">
      <div className="mb-8 flex-shrink-0">
        <p className="text-xs font-semibold uppercase tracking-wider text-indigo-500 mb-1">Saved</p>
        <h1 className="text-3xl font-bold text-gray-900 tracking-tight mb-2">Favorites</h1>
        <p className="text-gray-500 max-w-xl leading-relaxed">
          Saved questions and assistant responses for {selectedUser}.
        </p>
      </div>

      <div className="flex-1 overflow-y-auto space-y-4 pr-1">
        {favItems.map((fav) => (
          <div
            key={fav.message.id}
            className="bg-white border border-gray-100 rounded-2xl p-5 shadow-sm hover:shadow-md hover:border-indigo-100/80 transition-all duration-300 group"
          >
            {fav.question && (
              <div className="mb-3">
                <div className="text-[10px] font-semibold uppercase tracking-wider text-indigo-500 mb-1.5">
                  Question
                </div>
                <p className="text-gray-800 text-sm leading-relaxed whitespace-pre-wrap">
                  {fav.question}
                </p>
              </div>
            )}

            <div className="mb-2">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-emerald-600 mb-1.5">
                Assistant Response
              </div>
              <p className="text-gray-800 text-sm leading-relaxed whitespace-pre-wrap">
                {fav.message.content}
              </p>
            </div>

            {fav.message.cypher && (
              <div className="mt-3">
                <CypherViewer cypher={fav.message.cypher} />
              </div>
            )}

            <div className="flex justify-between items-center text-xs text-gray-400 mt-3 pt-3 border-t border-gray-100">
              <span className="flex items-center gap-1.5">
                <Star size={12} className="text-amber-400 fill-amber-400" />
                Saved{' '}
                {new Date(fav.message.timestamp).toLocaleString(undefined, {
                  dateStyle: 'medium',
                  timeStyle: 'short',
                })}
              </span>
              <button
                onClick={() => handleRemove(fav.message.id)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-rose-500 hover:text-rose-600 hover:bg-rose-50 rounded-lg text-xs font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                disabled={removingId === fav.message.id}
              >
                {removingId === fav.message.id ? (
                  <>
                    <div className="animate-spin rounded-full h-3.5 w-3.5 border-2 border-rose-200 border-t-rose-500"></div>
                    Removing&hellip;
                  </>
                ) : (
                  <>
                    <BookmarkMinus size={14} />
                    Remove
                  </>
                )}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
