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
    <div className="bg-white border border-gray-100 rounded-2xl p-6 md:p-7 shadow-lg shadow-indigo-100/40 ring-1 ring-indigo-50">
      <div className="flex items-center justify-between mb-5">
        <h3 className="text-lg font-semibold text-gray-900">{title}</h3>
        <button
          onClick={onCancel}
          className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
          aria-label="Close"
        >
          <X size={20} />
        </button>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="question" className="block text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
            Question
          </label>
          <textarea
            id="question"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-gray-900 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400 bg-gray-50/50 focus:bg-white transition-all resize-y"
            rows={2}
            placeholder="Enter the user question…"
            required
          />
        </div>

        <div>
          <label htmlFor="cypher" className="block text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
            Cypher query
          </label>
          <textarea
            id="cypher"
            value={cypher}
            onChange={(e) => setCypher(e.target.value)}
            className="w-full border border-gray-200 rounded-xl px-4 py-2.5 font-mono text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400 bg-slate-50 focus:bg-white transition-all resize-y"
            rows={6}
            placeholder="MATCH (n) RETURN n LIMIT 10"
            required
          />
        </div>

        {error && (
          <div className="text-rose-600 text-sm bg-rose-50 border border-rose-100 rounded-lg px-3 py-2">{error}</div>
        )}

        <div className="flex flex-wrap gap-3 pt-1">
          <button
            type="submit"
            disabled={isSubmitting}
            className="px-5 py-2.5 bg-indigo-500 text-white text-sm font-medium rounded-xl hover:bg-indigo-600 disabled:bg-gray-200 disabled:text-gray-400 disabled:cursor-not-allowed transition-all shadow-sm hover:shadow"
          >
            {isSubmitting ? 'Saving…' : (initialQuestion ? 'Update query' : 'Add query')}
          </button>
          <button
            type="button"
            onClick={onCancel}
            disabled={isSubmitting}
            className="px-5 py-2.5 bg-gray-100 text-gray-700 text-sm font-medium rounded-xl hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Cancel
          </button>
        </div>
      </form>
    </div>
  )
}
