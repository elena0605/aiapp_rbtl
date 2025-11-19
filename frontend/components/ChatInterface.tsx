'use client'

import { useState, useRef, useEffect } from 'react'
import MessageList from './MessageList'
import MessageInput from './MessageInput'
import {
  sendMessage,
  fetchChatHistory,
  deleteChatMessage,
  toggleFavoriteMessage,
  ChatResponse,
  ChatHistoryResponse,
  ChatMessageRecord,
} from '@/lib/api'

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  cypher?: string
  results?: any[]
  summary?: string
  examples?: any[]
  error?: string
  timestamp: Date
  isFavorite?: boolean
}

interface ChatInterfaceProps {
  selectedUser: string | null
  isUserSelectionReady: boolean
  userLoadError?: string | null
}

export default function ChatInterface({
  selectedUser,
  isUserSelectionReady,
  userLoadError,
}: ChatInterfaceProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [isLoadingHistory, setIsLoadingHistory] = useState(false)
  const [deletingMessageId, setDeletingMessageId] = useState<string | null>(null)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [favoriteUpdatingId, setFavoriteUpdatingId] = useState<string | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const transformMessageRecord = (record: ChatMessageRecord): Message => ({
    id: record.id || `${record.timestamp}-${record.role}`,
    role: record.role,
    content: record.content,
    cypher: record.cypher,
    results: record.results,
    summary: record.summary,
    examples: record.examples,
    error: record.error,
    timestamp: new Date(record.timestamp),
    isFavorite: record.is_favorite,
  })

  useEffect(() => {
    const loadHistory = async (username: string) => {
      setIsLoadingHistory(true)
      setHistoryError(null)
      try {
        const history: ChatHistoryResponse = await fetchChatHistory(username)
        const formatted = history.messages.map(transformMessageRecord)
        setMessages(formatted)
      } catch (error) {
        setMessages([])
        setHistoryError(
          `Unable to load chat history${
            error instanceof Error ? `: ${error.message}` : ''
          }`
        )
      } finally {
        setIsLoadingHistory(false)
      }
    }

    if (selectedUser) {
      loadHistory(selectedUser)
    } else {
      setMessages([])
      if (isUserSelectionReady && !userLoadError) {
        setHistoryError('Select a tester account from the sidebar to start chatting.')
      } else if (userLoadError) {
        setHistoryError(userLoadError)
      } else {
        setHistoryError(null)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedUser, isUserSelectionReady, userLoadError])

  const handleSendMessage = async (question: string) => {
    if (!selectedUser || !isUserSelectionReady) {
      setHistoryError('Please select a tester account before chatting.')
      return
    }
    // Add user message
    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: question,
      timestamp: new Date(),
      isFavorite: false,
    }
    setMessages((prev) => [...prev, userMessage])
    setIsLoading(true)

    try {
      const response: ChatResponse = await sendMessage(question, selectedUser)
      
      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: response.summary || 'Query executed successfully',
        cypher: response.cypher,
        results: response.results,
        summary: response.summary,
        examples: response.examples_used,
        error: response.error,
        timestamp: new Date(),
        isFavorite: false,
      }
      
      setMessages((prev) => [...prev, assistantMessage])
    } catch (error) {
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: `Error: ${error instanceof Error ? error.message : 'Unknown error'}`,
        error: error instanceof Error ? error.message : 'Unknown error',
        timestamp: new Date(),
        isFavorite: false,
      }
      setMessages((prev) => [...prev, errorMessage])
    } finally {
      setIsLoading(false)
    }
  }

  const handleToggleFavorite = async (messageId: string, nextState: boolean) => {
    if (!selectedUser || !isUserSelectionReady) {
      return
    }
    setFavoriteUpdatingId(messageId)
    try {
      await toggleFavoriteMessage(selectedUser, messageId, nextState)
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === messageId ? { ...msg, isFavorite: nextState } : msg
        )
      )
    } catch (error) {
      setHistoryError(
        `Failed to update favorite${
          error instanceof Error ? `: ${error.message}` : ''
        }`
      )
    } finally {
      setFavoriteUpdatingId(null)
    }
  }

  const handleDeleteMessage = async (messageId: string) => {
    if (!selectedUser || !isUserSelectionReady || !messageId) {
      return
    }
    setDeletingMessageId(messageId)
    try {
      await deleteChatMessage(selectedUser, messageId)
      setMessages((prev) => prev.filter((msg) => msg.id !== messageId))
    } catch (error) {
      setHistoryError(
        `Failed to delete message${
          error instanceof Error ? `: ${error.message}` : ''
        }`
      )
    } finally {
      setDeletingMessageId(null)
    }
  }

  return (
    <div className="flex flex-col h-full border border-gray-300 rounded-lg shadow-lg bg-white overflow-hidden">
      {historyError && (
        <div className="bg-red-50 border-b border-red-200 text-red-700 text-sm px-4 py-2">
          {historyError}
        </div>
      )}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 min-h-0 scroll-smooth relative">
        <MessageList
          messages={messages}
          onDeleteMessage={handleDeleteMessage}
          deletingMessageId={deletingMessageId}
          onToggleFavorite={handleToggleFavorite}
          favoriteUpdatingId={favoriteUpdatingId}
        />
        {isLoading && (
          <div className="flex items-center space-x-2 text-gray-500">
            <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-900"></div>
            <span>Processing...</span>
          </div>
        )}
        {isLoadingHistory && (
          <div className="absolute inset-0 bg-white/70 flex items-center justify-center text-gray-500 text-sm">
            Loading chat history...
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>
      <div className="flex-shrink-0">
        <MessageInput
          onSendMessage={handleSendMessage}
          disabled={isLoading || isLoadingHistory || !selectedUser || !isUserSelectionReady}
        />
      </div>
    </div>
  )
}

