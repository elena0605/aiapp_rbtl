import axios from 'axios'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export interface ChatRequest {
  question: string
  execute_cypher?: boolean
  output_mode?: 'json' | 'chat' | 'both'
}

export interface ChatResponse {
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

export async function sendMessage(
  question: string,
  executeCypher: boolean = true,
  outputMode: 'json' | 'chat' | 'both' = 'chat'
): Promise<ChatResponse> {
  const response = await axios.post<ChatResponse>(
    `${API_URL}/api/chat`,
    {
      question,
      execute_cypher: executeCypher,
      output_mode: outputMode,
    }
  )
  return response.data
}

export async function healthCheck(): Promise<{ status: string; service: string }> {
  const response = await axios.get(`${API_URL}/api/health`)
  return response.data
}

