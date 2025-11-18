'use client'

import { useState } from 'react'
import { QueryExample } from './KnowledgeBase'
import CypherViewer from './CypherViewer'
import { Trash2, Edit2 } from 'lucide-react'

interface CategoryDetailProps {
  queries: QueryExample[]
  categoryName: string
  onDelete: (question: string, cypher: string) => Promise<void>
  onEdit: (query: QueryExample) => void
}

export default function CategoryDetail({ queries, categoryName, onDelete, onEdit }: CategoryDetailProps) {
  const [deletingIndex, setDeletingIndex] = useState<number | null>(null)

  const handleDelete = async (query: QueryExample, index: number) => {
    if (!confirm('Are you sure you want to delete this query?')) {
      return
    }

    setDeletingIndex(index)
    try {
      await onDelete(query.question, query.cypher)
    } catch (error) {
      alert(`Failed to delete query: ${error instanceof Error ? error.message : 'Unknown error'}`)
    } finally {
      setDeletingIndex(null)
    }
  }
  if (queries.length === 0) {
    return (
      <div className="text-center py-12 text-gray-500">
        <p>No queries found in this category.</p>
        <p className="text-sm mt-2">Click "Add Query" to add the first one.</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="text-sm text-gray-600 mb-4">
        {queries.length} query{queries.length !== 1 ? 'ies' : 'y'} in this category
      </div>
      {queries.map((query, index) => (
        <div
          key={index}
          className="bg-white border border-gray-300 rounded-lg p-4 shadow-sm relative group"
        >
          <div className="absolute top-4 right-4 flex space-x-2">
            <button
              onClick={() => onEdit(query)}
              className="p-2 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded transition-colors"
              aria-label="Edit query"
              title="Edit query"
            >
              <Edit2 size={18} />
            </button>
            <button
              onClick={() => handleDelete(query, index)}
              disabled={deletingIndex === index}
              className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              aria-label="Delete query"
              title="Delete query"
            >
              {deletingIndex === index ? (
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-red-600"></div>
              ) : (
                <Trash2 size={18} />
              )}
            </button>
          </div>
          <div className="mb-3 pr-20">
            <div className="text-sm font-semibold text-gray-700 mb-1">Question:</div>
            <div className="text-gray-900">{query.question}</div>
          </div>
          <div className="mb-2">
            <CypherViewer cypher={query.cypher} />
          </div>
          {query.added_at && (
            <div className="text-xs text-gray-500 mt-2">
              Added: {new Date(query.added_at).toLocaleString()}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

