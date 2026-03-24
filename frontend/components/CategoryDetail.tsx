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
      <div className="text-center py-16 px-4 rounded-2xl border border-dashed border-gray-200 bg-white/60">
        <p className="text-gray-600 font-medium">No queries in &quot;{categoryName}&quot; yet</p>
        <p className="text-sm text-gray-400 mt-2">Use &quot;Add Query&quot; to create the first example.</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="text-xs font-medium text-gray-400 uppercase tracking-wide">
        {queries.length} quer{queries.length !== 1 ? 'ies' : 'y'} in this category
      </div>
      {queries.map((query, index) => (
        <div
          key={index}
          className="bg-white border border-gray-100 rounded-2xl p-5 shadow-sm hover:shadow-md hover:border-indigo-100/80 transition-all duration-300 relative group"
        >
          <div className="absolute top-4 right-4 flex gap-1.5 z-50 pointer-events-auto">
            <button
              onClick={(e) => {
                e.stopPropagation()
                e.preventDefault()
                onEdit(query)
              }}
              type="button"
              className="p-2 text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors bg-white shadow-sm border border-gray-100 cursor-pointer"
              aria-label="Edit query"
              title="Edit query"
              style={{ pointerEvents: 'auto' }}
            >
              <Edit2 size={17} />
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation()
                e.preventDefault()
                handleDelete(query, index)
              }}
              type="button"
              disabled={deletingIndex === index}
              className="p-2 text-gray-400 hover:text-rose-600 hover:bg-rose-50 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed bg-white shadow-sm border border-gray-100 cursor-pointer"
              aria-label="Delete query"
              title="Delete query"
              style={{ pointerEvents: 'auto' }}
            >
              {deletingIndex === index ? (
                <div className="animate-spin rounded-full h-4 w-4 border-2 border-rose-200 border-t-rose-600"></div>
              ) : (
                <Trash2 size={17} />
              )}
            </button>
          </div>
          <div className="mb-3 pr-24">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-indigo-500 mb-1.5">Question</div>
            <div className="text-gray-800 text-sm leading-relaxed">{query.question}</div>
          </div>
          <div className="mb-2">
            <CypherViewer cypher={query.cypher} />
          </div>
          {(query.added_at || query.created_by) && (
            <div className="text-xs text-gray-400 mt-3 pt-3 border-t border-gray-100 flex flex-wrap gap-4">
              {query.added_at && (
                <span>Added {new Date(query.added_at).toLocaleString()}</span>
              )}
              {query.created_by && (
                <span>By {query.created_by}</span>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
