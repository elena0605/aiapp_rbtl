'use client'

import { Message } from './ChatInterface'
import CypherViewer from './CypherViewer'
import ResultsTable from './ResultsTable'
import { Trash2, Star } from 'lucide-react'

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
}

export default function MessageList({
  messages,
  onDeleteMessage,
  deletingMessageId,
  onToggleFavorite,
  favoriteUpdatingId,
}: MessageListProps) {
  if (messages.length === 0) {
    return (
      <div className="text-center text-gray-500 py-8">
        <p>Start a conversation by asking a question about your data.</p>
        <p className="text-sm mt-2">Example: "How many TikTok users have over 1 million followers?"</p>
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
                    className={`p-1 rounded-full transition-colors ${
                      message.role === 'user'
                        ? 'text-white hover:bg-white/20'
                        : 'text-gray-500 hover:bg-gray-200'
                    } ${message.isFavorite ? 'text-yellow-400' : ''}`}
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
            <div className="whitespace-pre-wrap break-words overflow-wrap-anywhere">{message.content}</div>
            
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
            
            {message.timings && message.role === 'assistant' && (
              <div className="mt-3 text-xs">
                <div className="font-semibold mb-1">Query timings:</div>
                <ul className="space-y-1">
                  {Object.entries(message.timings).map(([key, value]) => (
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
            
            {message.results && message.results.length > 0 && (
              <div className="mt-3 max-w-full overflow-x-auto">
                <ResultsTable results={message.results} />
              </div>
            )}
            
            {message.error && (
              <div className="mt-3 text-red-600 text-sm">
                Error: {message.error}
              </div>
            )}
          </div>
        </div>
        </div>
      )})}
    </div>
  )
}

