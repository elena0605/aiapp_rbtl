import axios from 'axios'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export interface ChatResponse {
  username: string
  question: string
  cypher?: string
  results?: any[]
  summary?: string
  examples_used?: Array<{
    question: string
    cypher: string
    similarity?: number
  }>
  error?: string
}

export interface ChatMessageRecord {
  id: string
  role: 'user' | 'assistant'
  content: string
  cypher?: string
  results?: any[]
  summary?: string
  examples?: any[]
  error?: string
  timestamp: string
  is_favorite?: boolean
}

export interface ChatHistoryResponse {
  username: string
  messages: ChatMessageRecord[]
}

export interface FavoriteItem {
  message: ChatMessageRecord
  question?: string | null
  question_id?: string | null
}

export interface FavoritesResponse {
  username: string
  favorites: FavoriteItem[]
}

export interface GraphNodeInfo {
  label: string
  properties: Array<{ property: string; type: string }>
  description?: string
}

export interface GraphRelationshipInfo {
  start: string
  type: string
  end: string
  description?: string
}

export interface GraphInfoResponse {
  schema_text: string
  terminology_text: string
  nodes: GraphNodeInfo[]
  relationships: GraphRelationshipInfo[]
  graph_ready: boolean
  summary: string
}

export async function deleteChatMessage(
  username: string,
  messageId: string
): Promise<void> {
  const response = await axios.delete(
    `${API_URL}/api/chat/history/${encodeURIComponent(username)}/${encodeURIComponent(messageId)}`
  )
  if (response.status !== 200) {
    throw new Error('Failed to delete message')
  }
}

export async function sendMessage(
  question: string,
  username: string,
  executeCypher: boolean = true,
  outputMode: 'json' | 'chat' | 'both' = 'chat'
): Promise<ChatResponse> {
  const response = await axios.post<ChatResponse>(`${API_URL}/api/chat`, {
    username,
    question,
    execute_cypher: executeCypher,
    output_mode: outputMode,
  })
  return response.data
}

export async function healthCheck(): Promise<{ status: string; service: string }> {
  const response = await axios.get(`${API_URL}/api/health`)
  return response.data
}

export async function fetchChatUsers(): Promise<string[]> {
  const response = await axios.get<{ users: string[] }>(`${API_URL}/api/chat/users`)
  return response.data.users
}

export async function fetchChatHistory(username: string): Promise<ChatHistoryResponse> {
  const response = await axios.get<ChatHistoryResponse>(
    `${API_URL}/api/chat/history/${username}`
  )
  return response.data
}

export async function fetchFavorites(username: string): Promise<FavoritesResponse> {
  const response = await axios.get<FavoritesResponse>(
    `${API_URL}/api/chat/favorites/${username}`
  )
  return response.data
}

export async function toggleFavoriteMessage(
  username: string,
  messageId: string,
  isFavorite: boolean
): Promise<void> {
  await axios.post(
    `${API_URL}/api/chat/favorites/${encodeURIComponent(username)}/${encodeURIComponent(messageId)}`,
    { is_favorite: isFavorite }
  )
}

export async function fetchGraphInfo(): Promise<GraphInfoResponse> {
  const response = await axios.get<GraphInfoResponse>(`${API_URL}/api/graph-info`)
  return response.data
}

