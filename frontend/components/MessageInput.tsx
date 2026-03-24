'use client'

import { useState, KeyboardEvent } from 'react'
import { Send } from 'lucide-react'

interface MessageInputProps {
  onSendMessage: (message: string) => void
  disabled?: boolean
}

export default function MessageInput({ onSendMessage, disabled }: MessageInputProps) {
  const [input, setInput] = useState('')

  const handleSend = () => {
    if (input.trim() && !disabled) {
      onSendMessage(input.trim())
      setInput('')
    }
  }

  const handleKeyPress = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="border-t border-gray-200 p-4 bg-white/80 backdrop-blur-sm">
      <div className="flex items-end gap-3">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyPress={handleKeyPress}
          placeholder="Ask a question about your data..."
          className="flex-1 resize-none border border-gray-200 rounded-xl px-4 py-3 text-sm text-gray-900 bg-gray-50/50 focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400 focus:bg-white placeholder:text-gray-400 transition-all"
          rows={2}
          disabled={disabled}
        />
        <button
          onClick={handleSend}
          disabled={disabled || !input.trim()}
          className="px-5 py-3 bg-indigo-500 text-white rounded-xl hover:bg-indigo-600 disabled:bg-gray-200 disabled:text-gray-400 disabled:cursor-not-allowed flex items-center gap-2 font-medium text-sm transition-all duration-200 shadow-sm hover:shadow-md hover:shadow-indigo-200/50 active:scale-[0.98]"
        >
          <Send size={16} />
          <span>Send</span>
        </button>
      </div>
    </div>
  )
}
