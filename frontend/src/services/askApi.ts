const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '/api'

export class ApiError extends Error {
  constructor(public status: number, detail?: string) {
    super(detail ?? `Request failed with status ${status}`)
  }
}

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
  return fetch(`${API_BASE}/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, mode, clarifications }),
  }).then(async (res) => {
    if (!res.ok) {
      const body = (await res.json().catch(() => ({}))) as { detail?: unknown }
      throw new ApiError(res.status, typeof body.detail === 'string' ? body.detail : undefined)
    }
    return (await res.json()) as AskResponse
  })
}
