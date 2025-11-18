'use client'

import { useState, useEffect } from 'react'
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
}

export default function KnowledgeBase() {
  const [categories, setCategories] = useState<Category[]>([])
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [queries, setQueries] = useState<QueryExample[]>([])
  const [showAddForm, setShowAddForm] = useState(false)
  const [showCategoryForm, setShowCategoryForm] = useState(false)
  const [editingCategory, setEditingCategory] = useState<Category | null>(null)
  const [editingQuery, setEditingQuery] = useState<QueryExample | null>(null)
  const [deletingCategory, setDeletingCategory] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadCategories()
  }, [])

  useEffect(() => {
    if (selectedCategory) {
      loadQueries(selectedCategory)
    }
  }, [selectedCategory])

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

    try {
      await addQueryExample(selectedCategory, question, cypher)
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
    setEditingQuery(query)
    setShowAddForm(true)
  }

  const handleUpdateQuery = async (question: string, cypher: string) => {
    if (!selectedCategory || !editingQuery) return
    
    try {
      await updateQueryExample(
        selectedCategory,
        editingQuery.question,
        editingQuery.cypher,
        question,
        cypher
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
      <div className="flex flex-col items-center justify-center h-full">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900 mb-4"></div>
        <p className="text-gray-600">Loading categories...</p>
      </div>
    )
  }

  if (categories.length === 0 && !loading) {
    return (
      <div className="flex flex-col items-center justify-center h-full">
        <p className="text-gray-600 mb-2">No categories found.</p>
        <p className="text-sm text-gray-500">Please ensure the backend is running and the knowledge base API is available.</p>
        <button
          onClick={loadCategories}
          className="mt-4 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600"
        >
          Retry
        </button>
      </div>
    )
  }

  if (selectedCategory) {
  return (
    <div className="flex flex-col h-full p-6 overflow-hidden">
        <div className="mb-4 flex items-center justify-between flex-shrink-0">
          <div className="flex items-center space-x-3">
            <button
              onClick={handleBackToCategories}
              className="flex items-center space-x-2 px-3 py-2 border border-gray-300 bg-white text-gray-700 rounded-lg hover:bg-gray-50 hover:border-gray-400 transition-colors"
              aria-label="Back to categories"
            >
              <ArrowLeft size={18} />
              <span className="text-sm font-medium">Back</span>
            </button>
            <div>
              <h2 className="text-2xl font-bold text-gray-900">{selectedCategory}</h2>
              <p className="text-sm text-gray-600 mt-1">
                {categories.find(c => c.category_name === selectedCategory)?.category_description}
              </p>
            </div>
          </div>
          <button
            onClick={() => {
              setEditingQuery(null)
              setShowAddForm(!showAddForm)
            }}
            className="flex items-center space-x-2 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors"
          >
            <Plus size={20} />
            <span>Add Query</span>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto min-h-0">
          {showAddForm && (
            <div className="mb-6">
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
    <div className="flex flex-col h-full p-6 overflow-hidden">
      <div className="mb-6 flex-shrink-0">
        <div className="flex items-center justify-between mb-2">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 mb-2">Knowledge Base</h1>
            <p className="text-gray-600">
              Browse and manage query examples organized by category
            </p>
          </div>
          <button
            onClick={() => {
              setEditingCategory(null)
              setShowCategoryForm(true)
            }}
            className="flex items-center space-x-2 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors"
          >
            <Plus size={20} />
            <span>Add Category</span>
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto min-h-0">
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

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {categories.map((category) => (
            <div
              key={category.category_name}
              className="relative group bg-white border border-gray-300 rounded-lg shadow-sm hover:shadow-md hover:border-blue-500 transition-all"
            >
              <button
                onClick={() => handleCategoryClick(category.category_name)}
                className="text-left p-6 w-full"
              >
                <div className="flex items-start space-x-3 mb-3">
                  <BookOpen className="text-blue-500 flex-shrink-0 mt-1" size={24} />
                  <div className="flex-1">
                    <h3 className="text-lg font-semibold text-gray-900 mb-2">
                      {category.category_name}
                    </h3>
                    <p className="text-sm text-gray-600 line-clamp-3">
                      {category.category_description}
                    </p>
                  </div>
                </div>
              </button>
              
              {/* Edit and Delete buttons */}
              <div className="absolute top-4 right-4 flex space-x-2 opacity-0 group-hover:opacity-100 transition-opacity">
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    setEditingCategory(category)
                    setShowCategoryForm(true)
                  }}
                  className="p-2 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded transition-colors"
                  aria-label="Edit category"
                  title="Edit category"
                >
                  <Edit2 size={18} />
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
                  className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded transition-colors disabled:opacity-50"
                  aria-label="Delete category"
                  title="Delete category"
                >
                  {deletingCategory === category.category_name ? (
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-red-600"></div>
                  ) : (
                    <Trash2 size={18} />
                  )}
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

