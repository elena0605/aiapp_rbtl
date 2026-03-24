'use client'

import { useState } from 'react'
import { X } from 'lucide-react'

interface CategoryFormProps {
  onSubmit: (categoryName: string, categoryDescription: string) => Promise<void>
  onCancel: () => void
  initialName?: string
  initialDescription?: string
  title?: string
}

export default function CategoryForm({
  onSubmit,
  onCancel,
  initialName = '',
  initialDescription = '',
  title = 'Add Category'
}: CategoryFormProps) {
  const [categoryName, setCategoryName] = useState(initialName)
  const [categoryDescription, setCategoryDescription] = useState(initialDescription)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    if (!categoryName.trim() || !categoryDescription.trim()) {
      setError('Both category name and description are required')
      return
    }

    setIsSubmitting(true)
    try {
      await onSubmit(categoryName.trim(), categoryDescription.trim())
      setCategoryName('')
      setCategoryDescription('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save category')
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
          <label htmlFor="categoryName" className="block text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
            Category name
          </label>
          <input
            id="categoryName"
            type="text"
            value={categoryName}
            onChange={(e) => setCategoryName(e.target.value)}
            className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-gray-900 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400 bg-gray-50/50 focus:bg-white transition-all"
            placeholder="e.g., Content exposure by theme and topic"
            required
            disabled={isSubmitting}
          />
        </div>

        <div>
          <label htmlFor="categoryDescription" className="block text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
            Description
          </label>
          <textarea
            id="categoryDescription"
            value={categoryDescription}
            onChange={(e) => setCategoryDescription(e.target.value)}
            className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-gray-900 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400 bg-gray-50/50 focus:bg-white transition-all resize-y min-h-[100px]"
            rows={4}
            placeholder="Describe what types of queries belong in this category…"
            required
            disabled={isSubmitting}
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
            {isSubmitting ? 'Saving…' : 'Save category'}
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
