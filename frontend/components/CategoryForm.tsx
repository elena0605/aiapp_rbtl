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
          <label htmlFor="categoryName" className="block text-sm font-medium text-gray-700 mb-1">
            Category Name
          </label>
          <input
            id="categoryName"
            type="text"
            value={categoryName}
            onChange={(e) => setCategoryName(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-4 py-2 text-black focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="e.g., Content exposure by theme and topic"
            required
            disabled={isSubmitting}
          />
        </div>

        <div>
          <label htmlFor="categoryDescription" className="block text-sm font-medium text-gray-700 mb-1">
            Description
          </label>
          <textarea
            id="categoryDescription"
            value={categoryDescription}
            onChange={(e) => setCategoryDescription(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-4 py-2 text-black focus:outline-none focus:ring-2 focus:ring-blue-500"
            rows={4}
            placeholder="Describe what types of queries belong in this category..."
            required
            disabled={isSubmitting}
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
            {isSubmitting ? 'Saving...' : 'Save Category'}
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

