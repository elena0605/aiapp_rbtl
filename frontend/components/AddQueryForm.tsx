'use client'

import { useState, useEffect } from 'react'
import { X } from 'lucide-react'

interface AddQueryFormProps {
  onSubmit: (question: string, cypher: string) => Promise<void>
  onCancel: () => void
  initialQuestion?: string
  initialCypher?: string
  title?: string
}

export default function AddQueryForm({ 
  onSubmit, 
  onCancel, 
  initialQuestion = '', 
  initialCypher = '',
  title = 'Add New Query'
}: AddQueryFormProps) {
  const [question, setQuestion] = useState(initialQuestion)
  const [cypher, setCypher] = useState(initialCypher)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Update form fields when initial values change (e.g., when switching to edit mode)
  useEffect(() => {
    setQuestion(initialQuestion)
    setCypher(initialCypher)
  }, [initialQuestion, initialCypher])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    if (!question.trim() || !cypher.trim()) {
      setError('Both question and Cypher query are required')
      return
    }
    setIsSubmitting(true)
    try {
      await onSubmit(question.trim(), cypher.trim())
      // Only clear if it's a new query (not editing)
      if (!initialQuestion && !initialCypher) {
        setQuestion('')
        setCypher('')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save query')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="bg-white border border-gray-300 rounded-lg p-6 shadow-md">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-gray-900">{title}</h3>
        <button
          onClick={onCancel}
          className="p-1 hover:bg-gray-200 rounded transition-colors"
          aria-label="Close"
        >
          <X size={20} />
        </button>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="question" className="block text-sm font-medium text-gray-700 mb-1">
            Question
          </label>
          <textarea
            id="question"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-4 py-2 text-black focus:outline-none focus:ring-2 focus:ring-blue-500"
            rows={2}
            placeholder="Enter the user question..."
            required
          />
        </div>

        <div>
          <label htmlFor="cypher" className="block text-sm font-medium text-gray-700 mb-1">
            Cypher Query
          </label>
          <textarea
            id="cypher"
            value={cypher}
            onChange={(e) => setCypher(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-4 py-2 text-black font-mono text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            rows={6}
            placeholder="MATCH (n) RETURN n LIMIT 10"
            required
          />
        </div>

        {error && (
          <div className="text-red-600 text-sm">{error}</div>
        )}

        <div className="flex space-x-3">
          <button
            type="submit"
            disabled={isSubmitting}
            className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
          >
            {isSubmitting ? 'Saving...' : (initialQuestion ? 'Update Query' : 'Add Query')}
          </button>
          <button
            type="button"
            onClick={onCancel}
            disabled={isSubmitting}
            className="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300 disabled:bg-gray-100 disabled:cursor-not-allowed transition-colors"
          >
            Cancel
          </button>
        </div>
      </form>
    </div>
  )
}

