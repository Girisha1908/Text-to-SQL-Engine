import { apiFetch } from './api'

export interface ClarificationOption {
  id: string
  label: string
  definition: string
}

export interface Clarification {
  term: string
  prompt: string
  options: ClarificationOption[]
  source: 'glossary' | 'llm'
}

export interface ResolvedTerm {
  term: string
  option_id: string
  definition?: string
}

export interface AskResponse {
  status: 'needs_clarification' | 'answered' | 'unsupported' | 'rejected' | 'error'
  question: string
  clarifications: Clarification[]
  sql: string | null
  columns: string[]
  rows: unknown[][]
  row_count: number
  truncated: boolean
  assumptions: string[]
  interpretation: Record<string, string>
  generator: string | null
  detail: string | null
}

export function ask(
  question: string,
  mode: 'engine' | 'direct',
  clarifications: ResolvedTerm[] = [],
): Promise<AskResponse> {
  return apiFetch<AskResponse>('/ask', {
    method: 'POST',
    body: JSON.stringify({ question, mode, clarifications }),
  })
}
