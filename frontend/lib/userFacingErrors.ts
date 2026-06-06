const INTERNAL_MARKERS = [
  'cypher query syntax validation failed',
  'syntax validation error',
  'cypher query validation failed',
  'cypher validation failed',
  'stage 2 cypher validation failed',
  'neo.clienterror',
  'read-only violation',
  'validation_details',
  'type mismatch:',
]

export function isInternalErrorMessage(error?: string | null): boolean {
  if (!error?.trim()) return false
  const lower = error.trim().toLowerCase()
  return INTERNAL_MARKERS.some((marker) => lower.includes(marker))
}

const QUERY_FAILURE =
  "We couldn't answer that question right now. " +
  "Try rephrasing it or broadening the area or topic you're asking about."

const TIMEOUT_FAILURE =
  'The request took too long to complete. Try a simpler question or try again in a moment.'

export function isTimeoutErrorMessage(error?: string | null): boolean {
  if (!error?.trim()) return false
  const lower = error.trim().toLowerCase()
  return lower.includes('timeout') || lower.includes('timed out')
}

export function resolveAssistantContent(
  content: string,
  error?: string | null,
  summary?: string | null
): { content: string; hasError: boolean } {
  if (error?.trim() && isTimeoutErrorMessage(error)) {
    return { content: TIMEOUT_FAILURE, hasError: false }
  }
  if (error?.trim() && !isInternalErrorMessage(error)) {
    return { content: error.trim(), hasError: true }
  }
  if (summary?.trim()) {
    return { content: summary.trim(), hasError: false }
  }
  if (content?.trim() && !isInternalErrorMessage(content)) {
    return { content: content.trim(), hasError: false }
  }
  if (content?.trim() && isInternalErrorMessage(content)) {
    return { content: QUERY_FAILURE, hasError: false }
  }
  return { content: 'Query executed successfully', hasError: false }
}
