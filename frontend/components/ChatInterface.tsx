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
  timings?: Record<string, number>
}

interface ChatInterfaceProps {
  selectedUser: string | null
  isUserSelectionReady: boolean
  userLoadError?: string | null
  onProcessingChange?: (isProcessing: boolean) => void
}

const PROCESS_STEPS = [
  'Getting similar queries',
  'Generating Cypher',
  'Querying knowledge base',
  'Generating final response',
]

const STEP_DURATION_MS = 2500
const STEP_TIMING_KEYS: Array<keyof NonNullable<ChatResponse['timings']>> = [
  'similar_queries',
  'generate_cypher',
  'query_knowledge_base',
  'generate_final_response',
]

export default function ChatInterface({
  selectedUser,
  isUserSelectionReady,
  userLoadError,
  onProcessingChange,
}: ChatInterfaceProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [isLoadingHistory, setIsLoadingHistory] = useState(false)
  const [deletingMessageId, setDeletingMessageId] = useState<string | null>(null)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [favoriteUpdatingId, setFavoriteUpdatingId] = useState<string | null>(null)
  const [processingStepIndex, setProcessingStepIndex] = useState<number | null>(null)
  const [stepDurations, setStepDurations] = useState<number[]>(
    () => PROCESS_STEPS.map(() => 0)
  )
  const [currentStepElapsed, setCurrentStepElapsed] = useState(0)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const processingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const elapsedIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const activeRequestControllerRef = useRef<AbortController | null>(null)
  const stepStartTimeRef = useRef<number | null>(null)
  const previousStepIndexRef = useRef<number | null>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  useEffect(() => {
    if (isLoading) {
      setStepDurations(PROCESS_STEPS.map(() => 0))
      setCurrentStepElapsed(0)
      setProcessingStepIndex(0)
      previousStepIndexRef.current = null
      stepStartTimeRef.current = performance.now()

      if (processingIntervalRef.current) {
        clearInterval(processingIntervalRef.current)
      }
      processingIntervalRef.current = setInterval(() => {
        setProcessingStepIndex((prev) => {
          if (prev === null) return prev
          if (prev >= PROCESS_STEPS.length - 1) {
            return prev
          }
          return prev + 1
        })
      }, STEP_DURATION_MS)

      if (elapsedIntervalRef.current) {
        clearInterval(elapsedIntervalRef.current)
      }
      elapsedIntervalRef.current = setInterval(() => {
        if (stepStartTimeRef.current !== null) {
          setCurrentStepElapsed(
            (performance.now() - stepStartTimeRef.current) / 1000
          )
        }
      }, 200)
    } else {
      if (processingIntervalRef.current) {
        clearInterval(processingIntervalRef.current)
        processingIntervalRef.current = null
      }
      if (elapsedIntervalRef.current) {
        clearInterval(elapsedIntervalRef.current)
        elapsedIntervalRef.current = null
      }
      if (processingStepIndex !== null && stepStartTimeRef.current !== null) {
        const finalDuration =
          (performance.now() - stepStartTimeRef.current) / 1000
        setStepDurations((prev) => {
          const next = [...prev]
          next[processingStepIndex] = finalDuration
          return next
        })
      }
      setProcessingStepIndex(null)
      previousStepIndexRef.current = null
      stepStartTimeRef.current = null
      setCurrentStepElapsed(0)
    }

    return () => {
      if (processingIntervalRef.current) {
        clearInterval(processingIntervalRef.current)
        processingIntervalRef.current = null
      }
      if (elapsedIntervalRef.current) {
        clearInterval(elapsedIntervalRef.current)
        elapsedIntervalRef.current = null
      }
    }
  }, [isLoading])

  useEffect(() => {
    if (!isLoading) return
    if (processingStepIndex === null) return

    const prev = previousStepIndexRef.current
    if (prev !== null && processingStepIndex > prev && stepStartTimeRef.current !== null) {
      const duration =
        (performance.now() - stepStartTimeRef.current) / 1000
      setStepDurations((prevDurations) => {
        const next = [...prevDurations]
        next[prev] = duration
        return next
      })
      stepStartTimeRef.current = performance.now()
      setCurrentStepElapsed(0)
    } else if (prev === null) {
      stepStartTimeRef.current = performance.now()
      setCurrentStepElapsed(0)
    }
    previousStepIndexRef.current = processingStepIndex
  }, [processingStepIndex, isLoading])

  useEffect(() => {
    onProcessingChange?.(isLoading)
  }, [isLoading, onProcessingChange])

  const cancelActiveRequest = (reason?: string) => {
    if (activeRequestControllerRef.current) {
      activeRequestControllerRef.current.abort()
      activeRequestControllerRef.current = null
    }
    if (reason) {
      const cancelMessage: Message = {
        id: (Date.now() + Math.random()).toString(),
        role: 'assistant',
        content: reason,
        timestamp: new Date(),
        isFavorite: false,
      }
      setMessages((prev) => [...prev, cancelMessage])
    }
    setIsLoading(false)
  }

  useEffect(() => {
    if (isLoading) {
      cancelActiveRequest('Request cancelled due to tester change.')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedUser])

  useEffect(() => {
    return () => {
      cancelActiveRequest()
    }
  }, [])


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
    timings: (record as any).timings, // Timings might be stored in the record
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
    if (isLoading) {
      cancelActiveRequest()
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

    const controller = new AbortController()
    activeRequestControllerRef.current = controller

    try {
      const response: ChatResponse = await sendMessage(
        question,
        selectedUser,
        true,
        'chat',
        controller.signal
      )
      
      const assistantMessage: Message = {
        id: response.message_id || (Date.now() + 1).toString(),
        role: 'assistant',
        content: response.summary || 'Query executed successfully',
        cypher: response.cypher,
        results: response.results,
        summary: response.summary,
        examples: response.examples_used,
        error: response.error,
        timestamp: new Date(),
        isFavorite: false,
        timings: response.timings,
      }
      
      setMessages((prev) => [...prev, assistantMessage])

      if (response.timings) {
        const backendDurations = STEP_TIMING_KEYS.map((key) => {
          const value = response.timings?.[key]
          return typeof value === 'number' && isFinite(value) ? value : 0
        })
        setStepDurations(backendDurations)
      }
    } catch (error: any) {
      if (error?.code === 'ERR_CANCELED') {
        // cancellation already handled
        return
      }
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
      if (activeRequestControllerRef.current === controller) {
        activeRequestControllerRef.current = null
      }
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
          <div className="w-full max-w-md bg-gray-50 border border-gray-200 rounded-lg p-4 space-y-3 text-sm text-gray-600">
            <div className="flex items-center space-x-2 font-medium text-gray-700">
              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-700"></div>
              <span>Processing your question...</span>
            </div>
            <ol className="space-y-2">
              {PROCESS_STEPS.map((step, index) => {
                const isComplete =
                  processingStepIndex !== null && index < processingStepIndex
                const isCurrent = processingStepIndex === index
                const statusClass = isComplete
                  ? 'bg-green-500'
                  : isCurrent
                  ? 'bg-blue-500 animate-pulse'
                  : 'bg-gray-300'
                return (
                  <li key={step} className="flex items-center space-x-2">
                    <span
                      className={`h-2.5 w-2.5 rounded-full inline-block ${statusClass}`}
                    ></span>
                    <span
                      className={
                        isComplete
                          ? 'text-gray-700'
                          : isCurrent
                          ? 'text-gray-800'
                          : 'text-gray-400'
                      }
                    >
                      {step}
                    </span>
                  </li>
                )
              })}
            </ol>
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

