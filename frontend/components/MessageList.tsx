'use client'

import { useState } from 'react'
import { Message } from './ChatInterface'
import CypherViewer from './CypherViewer'
import ResultsTable from './ResultsTable'
import VisualizationRenderer from './VisualizationRenderer'
import { Trash2, Star, ThumbsUp, ThumbsDown, Send } from 'lucide-react'

function formatDateSeparator(date: Date): string {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const messageDate = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  const yesterday = new Date(today)
  yesterday.setDate(yesterday.getDate() - 1)
  
  const messageDateOnly = new Date(messageDate.getFullYear(), messageDate.getMonth(), messageDate.getDate())
  const yesterdayOnly = new Date(yesterday.getFullYear(), yesterday.getMonth(), yesterday.getDate())
  const todayOnly = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  
  if (messageDateOnly.getTime() === todayOnly.getTime()) {
    return 'Today'
  } else if (messageDateOnly.getTime() === yesterdayOnly.getTime()) {
    return 'Yesterday'
  } else {
    return date.toLocaleDateString('en-US', { day: 'numeric', month: 'long', year: 'numeric' })
  }
}

function getDateKey(date: Date): string {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).toISOString()
}

interface MessageListProps {
  messages: Message[]
  onDeleteMessage?: (id: string) => void
  deletingMessageId?: string | null
  onToggleFavorite?: (id: string, nextState: boolean) => void
  favoriteUpdatingId?: string | null
  onSubmitFeedback?: (messageId: string, rating: 'up' | 'down', comment?: string) => void
}

function FeedbackWidget({
  message,
  onSubmitFeedback,
}: {
  message: Message
  onSubmitFeedback: (messageId: string, rating: 'up' | 'down', comment?: string) => void
}) {
  const [pendingRating, setPendingRating] = useState<'up' | 'down' | null>(null)
  const [comment, setComment] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  const alreadyRated = !!message.feedback

  const handleThumbClick = async (rating: 'up' | 'down') => {
    if (alreadyRated) return
    setPendingRating(rating)
  }

  const handleSubmit = async () => {
    if (!pendingRating || isSubmitting) return
    setIsSubmitting(true)
    try {
      await onSubmitFeedback(message.id, pendingRating, comment.trim() || undefined)
      setPendingRating(null)
      setComment('')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleSkipComment = async () => {
    if (!pendingRating || isSubmitting) return
    setIsSubmitting(true)
    try {
      await onSubmitFeedback(message.id, pendingRating, undefined)
      setPendingRating(null)
      setComment('')
    } finally {
      setIsSubmitting(false)
    }
  }

  if (alreadyRated) {
    return (
      <div className="mt-3 pt-2 border-t border-gray-200 flex items-center gap-2 text-xs text-gray-500">
        <span>Feedback submitted</span>
        {message.feedback === 'up' ? (
          <ThumbsUp size={12} className="text-green-600" fill="currentColor" />
        ) : (
          <ThumbsDown size={12} className="text-red-500" fill="currentColor" />
        )}
      </div>
    )
  }

  return (
    <div className="mt-3 pt-2 border-t border-gray-200">
      <div className="flex items-center gap-3">
        <span className="text-xs text-gray-500">Was this helpful?</span>
        <button
          onClick={() => handleThumbClick('up')}
          className={`p-1.5 rounded-full transition-colors ${
            pendingRating === 'up'
              ? 'bg-green-100 text-green-600'
              : 'text-gray-400 hover:bg-gray-200 hover:text-green-600'
          }`}
          title="Helpful"
        >
          <ThumbsUp size={14} fill={pendingRating === 'up' ? 'currentColor' : 'none'} />
        </button>
        <button
          onClick={() => handleThumbClick('down')}
          className={`p-1.5 rounded-full transition-colors ${
            pendingRating === 'down'
              ? 'bg-red-100 text-red-500'
              : 'text-gray-400 hover:bg-gray-200 hover:text-red-500'
          }`}
          title="Not helpful"
        >
          <ThumbsDown size={14} fill={pendingRating === 'down' ? 'currentColor' : 'none'} />
        </button>
      </div>

      {pendingRating && (
        <div className="mt-2 space-y-2">
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Add a comment (optional)..."
            className="w-full text-sm border border-gray-300 rounded-md p-2 resize-none focus:outline-none focus:ring-1 focus:ring-blue-400 focus:border-blue-400"
            rows={2}
            disabled={isSubmitting}
          />
          <div className="flex items-center gap-2">
            <button
              onClick={handleSubmit}
              disabled={isSubmitting}
              className="flex items-center gap-1 px-3 py-1 text-xs font-medium text-white bg-blue-500 rounded-md hover:bg-blue-600 disabled:opacity-50 transition-colors"
            >
              {isSubmitting ? (
                <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-white"></div>
              ) : (
                <Send size={12} />
              )}
              Send Feedback
            </button>
            <button
              onClick={handleSkipComment}
              disabled={isSubmitting}
              className="px-3 py-1 text-xs text-gray-500 hover:text-gray-700 transition-colors"
            >
              Skip
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default function MessageList({
  messages,
  onDeleteMessage,
  deletingMessageId,
  onToggleFavorite,
  favoriteUpdatingId,
  onSubmitFeedback,
}: MessageListProps) {
  if (messages.length === 0) {
    return (
      <div className="text-center text-gray-500 py-8">
        <p>Start a conversation by asking a question about your data.</p>
        <p className="text-sm mt-2">Example: &quot;How many TikTok users have over 1 million followers?&quot;</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {messages.map((message, index) => {
        const showDateSeparator = index === 0 || 
          getDateKey(message.timestamp) !== getDateKey(messages[index - 1].timestamp)
        
        return (
          <div key={message.id}>
            {showDateSeparator && (
              <div className="flex items-center justify-center my-4">
                <div className="bg-gray-200 text-gray-600 text-xs px-3 py-1 rounded-full">
                  {formatDateSeparator(message.timestamp)}
                </div>
              </div>
            )}
            <div
              className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
          <div
            className={`relative max-w-[80%] rounded-lg p-4 break-words overflow-hidden ${
              message.role === 'user'
                ? 'bg-blue-500 text-white'
                : 'bg-gray-100 text-gray-900'
            }`}
          >
            <div className="flex items-center justify-between mb-1 gap-2">
              <div className="text-sm font-semibold">
                {message.role === 'user' ? 'You' : 'Assistant'}
              </div>
              <div className="flex items-center gap-2">
                <span className={`text-xs ${
                  message.role === 'user' 
                    ? 'text-white/80' 
                    : 'text-gray-500'
                }`}>
                  {message.timestamp.toLocaleTimeString('en-US', {
                    hour: '2-digit',
                    minute: '2-digit',
                  })}
                </span>
                {message.role === 'assistant' && onToggleFavorite && message.id && (
                  <button
                    onClick={() => onToggleFavorite(message.id, !message.isFavorite)}
                    className={`p-1 rounded-full transition-colors text-gray-500 hover:bg-gray-200 ${
                      message.isFavorite ? 'text-yellow-400' : ''
                    }`}
                    disabled={favoriteUpdatingId === message.id}
                    title={message.isFavorite ? 'Remove from favorites' : 'Add to favorites'}
                  >
                    {favoriteUpdatingId === message.id ? (
                      <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-current"></div>
                    ) : (
                      <Star size={14} fill={message.isFavorite ? 'currentColor' : 'none'} />
                    )}
                  </button>
                )}
                {onDeleteMessage && message.id && (
                  <button
                    onClick={() => onDeleteMessage(message.id)}
                    className={`p-1 rounded-full transition-colors ${
                      message.role === 'user'
                        ? 'text-white hover:bg-white/20'
                        : 'text-gray-500 hover:bg-gray-200'
                    }`}
                    disabled={deletingMessageId === message.id}
                    title="Delete message"
                  >
                    {deletingMessageId === message.id ? (
                      <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-current"></div>
                    ) : (
                      <Trash2 size={14} />
                    )}
                  </button>
                )}
              </div>
            </div>
            {message.error ? (
              <div className="whitespace-pre-wrap break-words overflow-wrap-anywhere text-red-600 font-medium">
                {message.content}
              </div>
            ) : !message.visualization ? (
              <div className="whitespace-pre-wrap break-words overflow-wrap-anywhere">{message.content}</div>
            ) : null}
            
            {message.cypher && (
              <div className="mt-3 max-w-full overflow-x-auto">
                <CypherViewer cypher={message.cypher} />
              </div>
            )}
            
            {message.examples && message.examples.length > 0 && (
              <div className="mt-3 text-xs">
                <div className="font-semibold mb-1">Similar examples used:</div>
                <ul className="list-disc list-inside space-y-1">
                  {message.examples.slice(0, 3).map((ex, idx) => (
                    <li key={idx}>
                      {ex.question} (similarity: {ex.similarity?.toFixed(3)})
                    </li>
                  ))}
                </ul>
              </div>
            )}
            
            {message.timings && message.role === 'assistant' && Object.keys(message.timings).length > 0 && (
              <div className="mt-3 text-xs">
                <div className="font-semibold mb-1">Query timings:</div>
                <ul className="space-y-1">
                  {Object.entries(message.timings)
                    .filter(([key]) => !['correction_attempts', 'retry_count'].includes(key))
                    .map(([key, value]) => (
                    <li key={key} className="flex justify-between items-center">
                      <span className="text-gray-600">
                        {key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}:
                      </span>
                      <span className="font-mono text-gray-800 ml-2">
                        {typeof value === 'number' ? `${value.toFixed(2)}s` : value}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            
            {message.results && message.results.length > 0 && !message.visualization && (
              <div className="mt-3 max-w-full overflow-x-auto">
                <ResultsTable results={message.results} />
              </div>
            )}

            {message.visualization && (
              <VisualizationRenderer visualization={message.visualization} />
            )}
            
            {message.error && message.cypher && (
              <div className="mt-3 p-2 bg-red-50 border border-red-200 rounded text-red-700 text-sm">
                <div className="font-semibold mb-1">Validation Details:</div>
                <div className="mt-1 font-mono text-xs bg-red-100 p-2 rounded">
                  Generated Query: {message.cypher}
                </div>
              </div>
            )}

            {message.role === 'assistant' && onSubmitFeedback && message.id && !message.error && (
              <FeedbackWidget message={message} onSubmitFeedback={onSubmitFeedback} />
            )}
          </div>
        </div>
        </div>
      )})}
    </div>
  )
}
