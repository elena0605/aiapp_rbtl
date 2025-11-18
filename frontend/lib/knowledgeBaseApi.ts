const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export interface Category {
  category_name: string
  category_description: string
}

export interface QueryExample {
  question: string
  cypher: string
  added_at?: string
}

export async function getCategories(): Promise<Category[]> {
  const response = await fetch(`${API_URL}/api/knowledge-base/categories`)
  if (!response.ok) {
    throw new Error('Failed to fetch categories')
  }
  const data = await response.json()
  return data.categories
}

export async function getQueriesByCategory(categoryName: string): Promise<QueryExample[]> {
  const response = await fetch(
    `${API_URL}/api/knowledge-base/queries?category=${encodeURIComponent(categoryName)}`
  )
  if (!response.ok) {
    throw new Error('Failed to fetch queries')
  }
  const data = await response.json()
  return data.queries || []
}

export async function addQueryExample(
  categoryName: string,
  question: string,
  cypher: string
): Promise<void> {
  const response = await fetch(`${API_URL}/api/knowledge-base/queries`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      category_name: categoryName,
      question,
      cypher,
    }),
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Failed to add query' }))
    throw new Error(error.detail || 'Failed to add query')
  }
}

export async function updateQueryExample(
  categoryName: string,
  oldQuestion: string,
  oldCypher: string,
  newQuestion: string,
  newCypher: string
): Promise<void> {
  const params = new URLSearchParams({
    category: categoryName,
  })
  
  const response = await fetch(`${API_URL}/api/knowledge-base/queries?${params.toString()}`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      old_question: oldQuestion,
      old_cypher: oldCypher,
      new_question: newQuestion,
      new_cypher: newCypher,
    }),
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Failed to update query' }))
    throw new Error(error.detail || 'Failed to update query')
  }
}

export async function deleteQueryExample(
  categoryName: string,
  question: string,
  cypher: string
): Promise<void> {
  const params = new URLSearchParams({
    category: categoryName,
    question: question,
    cypher: cypher,
  })
  
  const response = await fetch(`${API_URL}/api/knowledge-base/queries?${params.toString()}`, {
    method: 'DELETE',
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Failed to delete query' }))
    throw new Error(error.detail || 'Failed to delete query')
  }
}

export async function createCategory(
  categoryName: string,
  categoryDescription: string
): Promise<Category> {
  const response = await fetch(`${API_URL}/api/knowledge-base/categories`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      category_name: categoryName,
      category_description: categoryDescription,
    }),
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Failed to create category' }))
    throw new Error(error.detail || 'Failed to create category')
  }
  
  const data = await response.json()
  return data.category
}

export async function updateCategory(
  oldCategoryName: string,
  updates: { category_name?: string; category_description?: string }
): Promise<Category> {
  const response = await fetch(`${API_URL}/api/knowledge-base/categories/${encodeURIComponent(oldCategoryName)}`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(updates),
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Failed to update category' }))
    throw new Error(error.detail || 'Failed to update category')
  }
  
  const data = await response.json()
  return data.category
}

export async function deleteCategory(
  categoryName: string,
  deleteQueries: boolean = false
): Promise<void> {
  const params = new URLSearchParams({
    delete_queries: deleteQueries.toString(),
  })
  
  const response = await fetch(
    `${API_URL}/api/knowledge-base/categories/${encodeURIComponent(categoryName)}?${params.toString()}`,
    {
      method: 'DELETE',
    }
  )

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Failed to delete category' }))
    throw new Error(error.detail || 'Failed to delete category')
  }
}

