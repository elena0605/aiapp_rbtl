'use client'

import { Message } from './ChatInterface'
import CypherViewer from './CypherViewer'
import ResultsTable from './ResultsTable'

interface MessageListProps {
  messages: Message[]
}

export default function MessageList({ messages }: MessageListProps) {
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
      {messages.map((message) => (
        <div
          key={message.id}
          className={`flex ${
            message.role === 'user' ? 'justify-end' : 'justify-start'
          }`}
        >
          <div
            className={`max-w-[80%] rounded-lg p-4 break-words overflow-hidden ${
              message.role === 'user'
                ? 'bg-blue-500 text-white'
                : 'bg-gray-100 text-gray-900'
            }`}
          >
            <div className="text-sm font-semibold mb-1">
              {message.role === 'user' ? 'You' : 'Assistant'}
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
      ))}
    </div>
  )
}

