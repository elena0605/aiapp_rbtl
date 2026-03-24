'use client'

import { useState, useEffect, useRef } from 'react'
import { BookOpen, Plus, ArrowLeft, Edit2, Trash2 } from 'lucide-react'
import CategoryDetail from './CategoryDetail'
import AddQueryForm from './AddQueryForm'
import CategoryForm from './CategoryForm'
import { 
  getCategories, 
  getQueriesByCategory, 
  addQueryExample,
  updateQueryExample,
  deleteQueryExample,
  createCategory,
  updateCategory,
  deleteCategory
} from '@/lib/knowledgeBaseApi'

export interface Category {
  category_name: string
  category_description: string
}

export interface QueryExample {
  question: string
  cypher: string
  added_at?: string
  created_by?: string
}

interface KnowledgeBaseProps {
  selectedTester?: string | null
}

export default function KnowledgeBase({ selectedTester }: KnowledgeBaseProps) {
  const [categories, setCategories] = useState<Category[]>([])
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [queries, setQueries] = useState<QueryExample[]>([])
  const [showAddForm, setShowAddForm] = useState(false)
  const [showCategoryForm, setShowCategoryForm] = useState(false)
  const [editingCategory, setEditingCategory] = useState<Category | null>(null)
  const [editingQuery, setEditingQuery] = useState<QueryExample | null>(null)
  const [deletingCategory, setDeletingCategory] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const currentTester = selectedTester?.trim() || 'bojan'
  const formRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    loadCategories()
  }, [])

  useEffect(() => {
    if (selectedCategory) {
      loadQueries(selectedCategory)
    }
  }, [selectedCategory])

  // Scroll to form when it opens
  useEffect(() => {
    if (showAddForm && formRef.current) {
      // Small delay to ensure form is rendered
      setTimeout(() => {
        formRef.current?.scrollIntoView({ 
          behavior: 'smooth', 
          block: 'start',
          inline: 'nearest'
        })
      }, 100)
    }
  }, [showAddForm])

  const loadCategories = async () => {
    try {
      const data = await getCategories()
      setCategories(data)
      if (data.length === 0) {
        console.warn('No categories found')
      }
    } catch (error) {
      console.error('Failed to load categories:', error)
      // Show error to user
      alert(`Failed to load categories: ${error instanceof Error ? error.message : 'Unknown error'}. Please ensure the backend is running and restart it if needed.`)
    } finally {
      setLoading(false)
    }
  }

  const loadQueries = async (categoryName: string) => {
    try {
      const data = await getQueriesByCategory(categoryName)
      setQueries(data)
    } catch (error) {
      console.error('Failed to load queries:', error)
    }
  }

  const handleCategoryClick = (categoryName: string) => {
    setSelectedCategory(categoryName)
    setShowAddForm(false)
  }

  const handleBackToCategories = () => {
    setSelectedCategory(null)
    setShowAddForm(false)
    setEditingQuery(null)
    setQueries([])
  }

  const handleAddQuery = async (question: string, cypher: string) => {
    if (!selectedCategory) return
    const creator = selectedTester?.trim() || 'bojan'

    try {
      await addQueryExample(selectedCategory, question, cypher, creator)
      // Reload queries for the category
      await loadQueries(selectedCategory)
      setShowAddForm(false)
      setEditingQuery(null)
    } catch (error) {
      console.error('Failed to add query:', error)
      throw error
    }
  }

  const handleDeleteQuery = async (question: string, cypher: string) => {
    if (!selectedCategory) return

    try {
      await deleteQueryExample(selectedCategory, question, cypher)
      // Reload queries for the category
      await loadQueries(selectedCategory)
    } catch (error) {
      console.error('Failed to delete query:', error)
      throw error
    }
  }

  const handleEditQuery = (query: QueryExample) => {
    console.log('handleEditQuery called with:', query)
    // Close form first if it's open, then open it with new query
    // This ensures React re-renders the form with new initial values
    if (showAddForm) {
      setShowAddForm(false)
      setEditingQuery(null)
      // Use setTimeout to ensure state updates are processed before opening again
      setTimeout(() => {
        setEditingQuery(query)
        setShowAddForm(true)
        console.log('Form reopened with new query')
      }, 0)
    } else {
      setEditingQuery(query)
      setShowAddForm(true)
      console.log('Form opened with query')
    }
  }

  const handleUpdateQuery = async (question: string, cypher: string) => {
    if (!selectedCategory || !editingQuery) return
    const creator = selectedTester?.trim() || editingQuery.created_by || 'bojan'
    
    try {
      await updateQueryExample(
        selectedCategory,
        editingQuery.question,
        editingQuery.cypher,
        question,
        cypher,
        creator
      )
      await loadQueries(selectedCategory)
      setEditingQuery(null)
      setShowAddForm(false)
    } catch (error) {
      console.error('Failed to update query:', error)
      throw error
    }
  }

  const handleCreateCategory = async (categoryName: string, categoryDescription: string) => {
    try {
      await createCategory(categoryName, categoryDescription)
      await loadCategories()
      // Clear form state and ensure we're showing categories overview
      setShowCategoryForm(false)
      setEditingCategory(null)
      setSelectedCategory(null)
    } catch (error) {
      console.error('Failed to create category:', error)
      throw error
    }
  }

  const handleUpdateCategory = async (categoryName: string, categoryDescription: string) => {
    if (!editingCategory) return

    try {
      await updateCategory(editingCategory.category_name, {
        category_name: categoryName,
        category_description: categoryDescription
      })
      await loadCategories()
      setEditingCategory(null)
      setShowCategoryForm(false)
      
      // If we're viewing this category, update selected category name if it changed
      if (selectedCategory === editingCategory.category_name && categoryName !== editingCategory.category_name) {
        setSelectedCategory(categoryName)
        await loadQueries(categoryName)
      }
    } catch (error) {
      console.error('Failed to update category:', error)
      throw error
    }
  }

  const handleDeleteCategory = async (categoryName: string) => {
    if (!confirm(`Are you sure you want to delete the category "${categoryName}"? This will also delete all queries in this category.`)) {
      return
    }

    try {
      await deleteCategory(categoryName, true) // Delete queries too
      await loadCategories()
      
      // If we were viewing this category, go back to list
      if (selectedCategory === categoryName) {
        handleBackToCategories()
      }
    } catch (error) {
      console.error('Failed to delete category:', error)
      alert(`Failed to delete category: ${error instanceof Error ? error.message : 'Unknown error'}`)
    } finally {
      setDeletingCategory(null)
    }
  }

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-full bg-slate-50/50">
        <div className="animate-spin rounded-full h-9 w-9 border-2 border-indigo-200 border-t-indigo-500 mb-4"></div>
        <p className="text-sm text-gray-500 font-medium">Loading categories…</p>
      </div>
    )
  }

  if (categories.length === 0 && !loading) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-8 text-center bg-slate-50/50">
        <div className="w-14 h-14 rounded-2xl bg-indigo-100 flex items-center justify-center mb-4">
          <BookOpen className="text-indigo-500" size={28} />
        </div>
        <p className="text-gray-700 font-medium mb-1">No categories found</p>
        <p className="text-sm text-gray-500 max-w-md">Ensure the backend is running and the knowledge base API is available.</p>
        <button
          onClick={loadCategories}
          className="mt-6 px-5 py-2.5 bg-indigo-500 text-white text-sm font-medium rounded-xl hover:bg-indigo-600 transition-all shadow-sm hover:shadow-md"
        >
          Retry
        </button>
      </div>
    )
  }

  const categoryAccentClasses = [
    'from-indigo-500 to-violet-500',
    'from-sky-500 to-cyan-500',
    'from-teal-500 to-emerald-500',
    'from-amber-500 to-orange-500',
    'from-rose-500 to-pink-500',
    'from-fuchsia-500 to-purple-500',
  ]

  if (selectedCategory) {
  return (
    <div className="flex flex-col h-full p-6 md:p-8 overflow-hidden bg-slate-50/30">
        <div className="mb-6 flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4 flex-shrink-0">
          <div className="flex items-start gap-3 min-w-0">
            <button
              onClick={handleBackToCategories}
              className="flex items-center gap-2 px-3.5 py-2 border border-gray-200 bg-white text-gray-600 rounded-xl hover:bg-gray-50 hover:border-gray-300 transition-all shadow-sm shrink-0"
              aria-label="Back to categories"
            >
              <ArrowLeft size={18} />
              <span className="text-sm font-medium">Back</span>
            </button>
            <div className="min-w-0">
              <h2 className="text-2xl font-bold text-gray-900 tracking-tight">{selectedCategory}</h2>
              <p className="text-sm text-gray-500 mt-1 leading-relaxed line-clamp-2">
                {categories.find(c => c.category_name === selectedCategory)?.category_description}
              </p>
            </div>
          </div>
          <button
            onClick={() => {
              setEditingQuery(null)
              setShowAddForm(!showAddForm)
            }}
            className="flex items-center justify-center gap-2 px-5 py-2.5 bg-indigo-500 text-white text-sm font-medium rounded-xl hover:bg-indigo-600 transition-all shadow-sm hover:shadow-md hover:shadow-indigo-200/50 shrink-0"
          >
            <Plus size={18} />
            <span>Add Query</span>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto min-h-0">
          {showAddForm && (
            <div ref={formRef} className="mb-6" key={editingQuery ? `edit-${editingQuery.question}-${editingQuery.cypher}` : 'add-new'}>
              <AddQueryForm
                onSubmit={editingQuery ? handleUpdateQuery : handleAddQuery}
                onCancel={() => {
                  setShowAddForm(false)
                  setEditingQuery(null)
                }}
                initialQuestion={editingQuery?.question}
                initialCypher={editingQuery?.cypher}
                title={editingQuery ? 'Edit Query' : 'Add New Query'}
              />
            </div>
          )}
          <CategoryDetail 
            queries={queries} 
            categoryName={selectedCategory}
            onDelete={handleDeleteQuery}
            onEdit={handleEditQuery}
          />
        </div>
    </div>
  )
  }

  return (
    <div className="flex flex-col h-full p-6 md:p-8 overflow-hidden bg-slate-50/30">
      <div className="mb-8 flex-shrink-0">
        <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-indigo-500 mb-1">Examples</p>
            <h1 className="text-3xl font-bold text-gray-900 tracking-tight mb-2">Knowledge Base</h1>
            <p className="text-gray-500 max-w-xl leading-relaxed">
              Browse and manage query examples organized by category
            </p>
          </div>
          <button
            onClick={() => {
              setEditingCategory(null)
              setShowCategoryForm(true)
            }}
            className="flex items-center justify-center gap-2 px-5 py-2.5 bg-indigo-500 text-white text-sm font-medium rounded-xl hover:bg-indigo-600 transition-all shadow-sm hover:shadow-md hover:shadow-indigo-200/50 shrink-0"
          >
            <Plus size={18} />
            <span>Add Category</span>
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto min-h-0 pr-1">
        {showCategoryForm && (
          <div className="mb-6">
            <CategoryForm
              onSubmit={editingCategory ? handleUpdateCategory : handleCreateCategory}
              onCancel={() => {
                setShowCategoryForm(false)
                setEditingCategory(null)
              }}
              initialName={editingCategory?.category_name || ''}
              initialDescription={editingCategory?.category_description || ''}
              title={editingCategory ? 'Edit Category' : 'Add Category'}
            />
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {categories.map((category, idx) => {
            const accent = categoryAccentClasses[idx % categoryAccentClasses.length]
            return (
            <div
              key={category.category_name}
              className="relative group bg-white border border-gray-100 rounded-2xl shadow-sm hover:shadow-lg hover:shadow-indigo-100/50 hover:border-indigo-100 transition-all duration-300 overflow-hidden"
            >
              <div className={`h-1 bg-gradient-to-r ${accent}`} aria-hidden />
              <button
                onClick={() => handleCategoryClick(category.category_name)}
                className="text-left p-6 w-full pt-5"
              >
                <div className="flex items-start gap-4">
                  <div className={`flex-shrink-0 w-11 h-11 rounded-xl bg-gradient-to-br ${accent} flex items-center justify-center shadow-sm`}>
                    <BookOpen className="text-white" size={20} />
                  </div>
                  <div className="flex-1 min-w-0 pr-10">
                    <h3 className="text-base font-semibold text-gray-900 mb-2 leading-snug group-hover:text-indigo-700 transition-colors">
                      {category.category_name}
                    </h3>
                    <p className="text-sm text-gray-500 line-clamp-3 leading-relaxed">
                      {category.category_description}
                    </p>
                  </div>
                </div>
              </button>
              
              <div className="absolute top-5 right-4 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    setEditingCategory(category)
                    setShowCategoryForm(true)
                  }}
                  className="p-2 text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors"
                  aria-label="Edit category"
                  title="Edit category"
                >
                  <Edit2 size={17} />
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    if (confirm(`Delete category "${category.category_name}" and all its queries?`)) {
                      setDeletingCategory(category.category_name)
                      handleDeleteCategory(category.category_name)
                    }
                  }}
                  disabled={deletingCategory === category.category_name}
                  className="p-2 text-gray-400 hover:text-rose-600 hover:bg-rose-50 rounded-lg transition-colors disabled:opacity-50"
                  aria-label="Delete category"
                  title="Delete category"
                >
                  {deletingCategory === category.category_name ? (
                    <div className="animate-spin rounded-full h-4 w-4 border-2 border-rose-200 border-t-rose-600"></div>
                  ) : (
                    <Trash2 size={17} />
                  )}
                </button>
              </div>
            </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

