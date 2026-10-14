import { FormEvent, useState } from 'react'
import { ApiError, ask, AskResponse, Clarification, ResolvedTerm } from '../services/askApi'

// Design: docs/DESIGN.md (teal #0F766E = teal-700, wash #F0FDFA = teal-50, canvas #FAFAF9 = stone-50).

const REPO = 'https://github.com/Girisha1908/ask-your-data'

const SANS = "font-['Geist',ui-sans-serif,system-ui,sans-serif]"
const MONO = "font-['Geist_Mono',ui-monospace,monospace]"
const EYEBROW = 'text-[11px] font-medium uppercase tracking-[0.08em] text-zinc-500'

const EXAMPLES = [
  "Show me last month's best customer.",
  'How many new customers signed up last month?',
  'What was our best-selling product last month?',
  'How many active customers do we have?',
  'Which payment method brought in the most money last month?',
]

const TRY_MORE = [
  'Top 5 customers by total spend last month',
  'What was revenue by category last month?',
  'How many orders were canceled last month?',
  'Show monthly revenue for 2026.',
]

const KNOWS = [
  ['Customers', 'city, state, sign-up date'],
  ['Orders', 'date, status, value'],
  ['Order items', 'quantity, price, discount'],
  ['Products', 'name, category, brand, price'],
  ['Payments', 'method, installments, amount'],
]

type Tag = 'your choice' | 'assumed' | 'default'

const human = (s: string) => {
  const t = s.replace(/_/g, ' ')
  return t.charAt(0).toUpperCase() + t.slice(1)
}

const isNum = (v: unknown): v is number => typeof v === 'number'

function fmt(v: unknown): string {
  if (isNum(v)) return v.toLocaleString('en-US', { maximumFractionDigits: 2 })
  if (v === null || v === undefined) return '—'
  return String(v)
}

/** Backend assumptions end in "(your choice)" / "(assumed)"; glossary ones start with "term: Label — definition". */
function parseAssumption(a: string): { text: string; detail?: string; tag: Tag } {
  const tag: Tag = a.endsWith('(your choice)') ? 'your choice' : a.endsWith('(assumed)') ? 'assumed' : 'default'
  const body = a.replace(/\s*\((your choice|assumed)\)$/, '')
  const m = body.match(/^([a-z_]+): (.+?) — (.+)$/)
  if (m) return { text: `${human(m[1])} = ${m[2].toLowerCase()}`, detail: m[3], tag }
  const plain = body.match(/^([a-z_]+): (.+)$/)
  if (plain) return { text: `${human(plain[1])} = ${plain[2]}`, tag }
  return { text: body, tag }
}

const TAG_STYLE: Record<Tag, string> = {
  'your choice': 'bg-teal-50 text-teal-800 ring-teal-200',
  assumed: 'bg-amber-100 text-amber-900 ring-amber-200',
  default: 'bg-zinc-100 text-zinc-600 ring-zinc-200',
}

// ---------------------------------------------------------------------------

function TopBar() {
  return (
    <header className="border-b border-zinc-200 bg-white">
      <div className="mx-auto flex h-16 max-w-[1200px] items-center justify-between gap-4 px-4 sm:px-6">
        <a href="/" className="text-lg font-semibold tracking-tight text-zinc-900">
          Ask Your Data
        </a>
        <nav className="flex items-center gap-1 text-sm">
          <a href={`${REPO}/blob/main/docs/eval-results.md`} className="hidden rounded-lg px-3 py-2 text-zinc-600 hover:text-zinc-900 sm:inline">
            Evaluation
          </a>
          <a href={REPO} className="rounded-lg px-3 py-2 text-zinc-600 hover:text-zinc-900">
            GitHub
          </a>
        </nav>
      </div>
    </header>
  )
}

function Switch({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-4 rounded-xl bg-zinc-100/70 px-4 py-3">
      <span>
        <span className="block text-sm font-medium text-zinc-900">Ask me when a question is ambiguous</span>
        <span className="block text-xs text-zinc-500">Turn off to see what a guess-first system answers.</span>
      </span>
      <input type="checkbox" className="peer sr-only" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span
        aria-hidden
        className="relative h-7 w-12 shrink-0 rounded-full bg-zinc-300 transition-colors peer-checked:bg-teal-700 peer-focus-visible:ring-2 peer-focus-visible:ring-teal-700 peer-focus-visible:ring-offset-2 after:absolute after:left-1 after:top-1 after:h-5 after:w-5 after:rounded-full after:bg-white after:shadow after:transition-transform peer-checked:after:translate-x-5"
      />
    </label>
  )
}

function ClarificationPanel({
  items,
  picked,
  onPick,
  onSubmit,
  busy,
}: {
  items: Clarification[]
  picked: Record<string, ResolvedTerm>
  onPick: (r: ResolvedTerm) => void
  onSubmit: () => void
  busy: boolean
}) {
  const ready = items.every((c) => picked[c.term])
  return (
    <section className="ask-rise overflow-hidden rounded-[20px] border border-zinc-200 bg-white shadow-[0_1px_2px_rgba(24,24,27,0.04),0_8px_24px_rgba(24,24,27,0.04)]">
      <div className="border-b border-teal-100 bg-teal-50 px-6 py-4">
        <p className="font-medium text-teal-900">Before I answer — this question can mean more than one thing.</p>
      </div>
      <div className="space-y-6 p-6">
        {items.map((c) => (
          <div key={c.term}>
            <p id={`q-${c.term}`} className="font-medium text-zinc-900">
              {c.prompt}
            </p>
            <div role="radiogroup" aria-labelledby={`q-${c.term}`} className="mt-3 grid gap-3 md:grid-cols-3">
              {c.options.map((o, i) => {
                const on = picked[c.term]?.option_id === o.id
                return (
                  <button
                    key={o.id}
                    type="button"
                    role="radio"
                    aria-checked={on}
                    onClick={() => onPick({ term: c.term, option_id: o.id, definition: o.definition })}
                    style={{ animationDelay: `${i * 40}ms` }}
                    className={`ask-rise relative min-h-[44px] rounded-2xl border p-4 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-700 ${
                      on ? 'border-2 border-teal-700 bg-teal-50' : 'border-zinc-200 bg-white hover:border-teal-300'
                    }`}
                  >
                    {on && (
                      <span className="absolute right-3 top-3 grid h-5 w-5 place-items-center rounded-full bg-teal-700 text-white">
                        <svg viewBox="0 0 16 16" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="2.5">
                          <path d="M3.5 8.5l3 3 6-7" />
                        </svg>
                      </span>
                    )}
                    <span className="block pr-6 font-semibold text-zinc-900">{o.label}</span>
                    <span className="mt-1 block text-sm leading-snug text-zinc-500">{o.definition}</span>
                  </button>
                )
              })}
            </div>
          </div>
        ))}
        <div className="flex flex-wrap items-center gap-4">
          <button
            type="button"
            disabled={!ready || busy}
            onClick={onSubmit}
            className="min-h-[44px] rounded-xl bg-teal-700 px-5 font-medium text-white transition hover:bg-teal-800 active:translate-y-px disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? 'Answering…' : 'Answer with this meaning'}
          </button>
          <span className="text-sm text-zinc-500">No query has run yet.</span>
        </div>
      </div>
    </section>
  )
}

function Headline({ res }: { res: AskResponse }) {
  const [row] = res.rows
  if (res.rows.length === 1 && res.columns.length === 1) {
    return (
      <p className="text-2xl font-semibold tracking-tight text-zinc-900 sm:text-3xl">
        <span className={MONO}>{fmt(row[0])}</span>{' '}
        <span className="text-zinc-500">{human(res.columns[0]).toLowerCase()}</span>
      </p>
    )
  }
  if (res.rows.length === 1 && res.columns.length >= 2 && !isNum(row[0])) {
    return (
      <p className="text-2xl font-semibold tracking-tight text-zinc-900 sm:text-3xl">
        <span className="text-teal-700">{fmt(row[0])}</span>
        <span className="text-zinc-400"> — </span>
        {human(res.columns[1]).toLowerCase()} <span className={MONO}>{fmt(row[1])}</span>
      </p>
    )
  }
  return (
    <p className="text-2xl font-semibold tracking-tight text-zinc-900 sm:text-3xl">
      {res.row_count} {res.row_count === 1 ? 'row' : 'rows'}
    </p>
  )
}

function AnswerPanel({ res, ms }: { res: AskResponse; ms: number | null }) {
  const assumptions = res.assumptions.map(parseAssumption)
  const guessed = assumptions.filter((a) => a.tag === 'assumed')
  return (
    <section className="ask-rise rounded-[20px] border border-zinc-200 bg-white p-6 shadow-[0_1px_2px_rgba(24,24,27,0.04),0_8px_24px_rgba(24,24,27,0.04)] sm:p-8">
      <div className={`flex flex-wrap items-center justify-between gap-2 ${EYEBROW}`}>
        <span className="flex items-center gap-2">
          <span className="h-1.5 w-1.5 rounded-full bg-teal-700" />
          Read-only query{ms !== null && <span className={`${MONO} normal-case tracking-normal`}>· {(ms / 1000).toFixed(2)}s</span>}
        </span>
        <span>
          {res.row_count} {res.row_count === 1 ? 'row' : 'rows'}
        </span>
      </div>

      {guessed.map((g) => (
        <p key={g.text} className="mt-4 inline-flex rounded-lg bg-amber-100 px-3 py-1.5 text-sm text-amber-900">
          Guessed: {g.text.toLowerCase()} — not asked.
        </p>
      ))}

      <div className="mt-4">
        {res.rows.length === 0 ? (
          <p className="text-zinc-500">No data matched this question for the period.</p>
        ) : (
          <Headline res={res} />
        )}
      </div>

      {res.rows.length > 0 && (
        <div className="mt-6 max-h-[420px] overflow-auto rounded-xl border border-zinc-200">
          <table className="min-w-full text-sm">
            <thead className="sticky top-0 bg-zinc-50">
              <tr>
                {res.columns.map((c, i) => (
                  <th
                    key={c}
                    scope="col"
                    className={`px-4 py-3 ${EYEBROW} ${isNum(res.rows[0][i]) ? 'text-right' : 'text-left'}`}
                  >
                    {human(c)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {res.rows.map((r, i) => (
                <tr key={i} className="ask-rise border-t border-zinc-100" style={{ animationDelay: `${Math.min(i, 10) * 30}ms` }}>
                  {r.map((v, j) => (
                    <td
                      key={j}
                      className={`px-4 py-3 text-zinc-900 ${isNum(v) ? `${MONO} text-right tabular-nums` : ''} ${
                        typeof v === 'string' && !v.includes(' ') ? MONO : ''
                      }`}
                    >
                      {fmt(v)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {res.truncated && <p className="mt-2 text-xs text-zinc-500">Showing the first {res.row_count} rows.</p>}

      {assumptions.length > 0 && (
        <div className="mt-8">
          <h3 className={EYEBROW}>How I read your question</h3>
          <ul className="mt-3 space-y-2.5">
            {assumptions.map((a) => (
              <li key={a.text} className="flex flex-wrap items-start gap-x-3 gap-y-1 text-sm">
                <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-zinc-400" />
                <span className="text-zinc-800">
                  {a.text}
                  {a.detail && <span className="block text-zinc-500">{a.detail}</span>}
                </span>
                <span className={`rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${TAG_STYLE[a.tag]}`}>
                  {a.tag}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <details className="group mt-8 border-t border-zinc-100 pt-4">
        <summary className="cursor-pointer list-none text-sm font-medium text-zinc-600 hover:text-zinc-900">
          <span className="mr-1 inline-block transition-transform group-open:rotate-90">›</span> View technical details
        </summary>
        <div className="relative mt-3">
          <pre
            className={`${MONO} overflow-x-auto whitespace-pre-wrap rounded-xl bg-zinc-800 p-4 pr-16 text-xs leading-relaxed text-zinc-200`}
          >
            {res.sql}
          </pre>
          <button
            type="button"
            onClick={() => void navigator.clipboard?.writeText(res.sql ?? '')}
            className="absolute right-2 top-2 rounded-md bg-zinc-700 px-2 py-1 text-xs text-zinc-200 hover:bg-zinc-600"
          >
            Copy
          </button>
        </div>
        <p className="mt-2 text-xs text-zinc-500">
          Generated by: {res.generator === 'offline' ? 'offline planner' : res.generator}
        </p>
      </details>
    </section>
  )
}

function Skeleton() {
  return (
    <div aria-label="Loading" className="animate-pulse rounded-[20px] border border-zinc-200 bg-white p-8">
      <div className="h-3 w-32 rounded bg-zinc-200" />
      <div className="mt-5 h-7 w-2/3 rounded bg-zinc-200" />
      <div className="mt-6 space-y-3">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-9 rounded bg-zinc-100" />
        ))}
      </div>
    </div>
  )
}

function EmptyState() {
  return (
    <section className="grid gap-6 rounded-[20px] border border-dashed border-zinc-300 p-6 sm:p-8 md:grid-cols-[1fr_auto] md:items-center">
      <p className="max-w-[46ch] text-zinc-600">
        Ask about customers, orders, products and payments. If a question can mean more than one thing, you'll choose
        before any query runs.
      </p>
      <ol className="flex items-center gap-2 text-sm" aria-label="How it works">
        {['Question', 'Clarify', 'Answer'].map((s, i) => (
          <li key={s} className="flex items-center gap-2">
            {i > 0 && <span className="text-zinc-400">→</span>}
            <span
              className={`rounded-lg border px-3 py-1.5 ${
                s === 'Clarify' ? 'border-teal-700 bg-teal-50 text-teal-800' : 'border-zinc-200 bg-white text-zinc-700'
              }`}
            >
              {s}
            </span>
          </li>
        ))}
      </ol>
    </section>
  )
}

function Rail({ onTry }: { onTry: (q: string) => void }) {
  return (
    <aside className="space-y-4">
      <section className="rounded-2xl border border-zinc-200 bg-white p-5">
        <h2 className={EYEBROW}>Questions you can try</h2>
        <ul className="mt-3 space-y-1">
          {TRY_MORE.map((q) => (
            <li key={q}>
              <button
                type="button"
                onClick={() => onTry(q)}
                className="flex min-h-[40px] w-full items-start gap-2 rounded-lg px-2 py-2 text-left text-sm text-zinc-700 hover:bg-zinc-50 hover:text-zinc-900"
              >
                <span className="text-zinc-400">→</span>
                {q}
              </button>
            </li>
          ))}
        </ul>
      </section>
      <section className="rounded-2xl border border-zinc-200 bg-white p-5">
        <h2 className={EYEBROW}>What I know about</h2>
        <ul className="mt-3 space-y-3">
          {KNOWS.map(([name, fields]) => (
            <li key={name} className="flex gap-3">
              <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-teal-700" />
              <span>
                <span className="block text-sm font-medium text-zinc-900">{name}</span>
                <span className="block text-xs text-zinc-500">{fields}</span>
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-4 border-t border-zinc-100 pt-3 text-xs text-zinc-500">
          Queries are read-only and limited to 5 seconds.
        </p>
      </section>
    </aside>
  )
}

// ---------------------------------------------------------------------------

export default function Ask() {
  const [question, setQuestion] = useState('')
  const [clarify, setClarify] = useState(true)
  const [res, setRes] = useState<AskResponse | null>(null)
  const [picked, setPicked] = useState<Record<string, ResolvedTerm>>({})
  const [busy, setBusy] = useState(false)
  const [ms, setMs] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function run(q: string, clarifications: ResolvedTerm[] = []) {
    setBusy(true)
    setError(null)
    const t0 = performance.now()
    try {
      const r = await ask(q, clarify ? 'engine' : 'direct', clarifications)
      setMs(performance.now() - t0)
      setRes(r)
    } catch (e) {
      setRes(null)
      setError(e instanceof ApiError ? e.message : 'Could not reach the API. Is the backend running?')
    } finally {
      setBusy(false)
    }
  }

  function submit(e?: FormEvent, q = question) {
    e?.preventDefault()
    if (q.trim().length < 3) return
    setQuestion(q)
    setPicked({})
    void run(q.trim())
  }

  const failed = res && ['unsupported', 'rejected', 'error'].includes(res.status)

  return (
    <div className={`${SANS} min-h-[100dvh] bg-stone-50 text-zinc-900 antialiased`}>
      <TopBar />
      <div className="mx-auto grid max-w-[1200px] gap-10 px-4 py-10 sm:px-6 xl:grid-cols-[minmax(0,880px)_280px] xl:justify-between">
        <main className="min-w-0">
          <h1 className="text-[clamp(1.75rem,3vw,2.25rem)] font-semibold tracking-[-0.02em]">Ask your data</h1>
          <p className="mt-1 max-w-[65ch] text-zinc-500">
            Plain-English questions about your store. Ambiguous questions get a quick clarifying choice before any
            query runs.
          </p>

          <form onSubmit={submit} className="mt-8">
            <label htmlFor="q" className={EYEBROW}>
              Your question
            </label>
            <div className="mt-2 flex items-center gap-2 rounded-2xl border border-zinc-200 bg-white p-2 pl-4 shadow-sm focus-within:border-teal-700 focus-within:ring-2 focus-within:ring-teal-700/20">
              <svg viewBox="0 0 20 20" className="h-5 w-5 shrink-0 text-zinc-400" fill="none" stroke="currentColor" strokeWidth="1.8">
                <circle cx="9" cy="9" r="6" />
                <path d="M13.5 13.5L17 17" />
              </svg>
              <input
                id="q"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                maxLength={500}
                placeholder="e.g. Show me last month's best customer."
                className="h-10 min-w-0 flex-1 bg-transparent text-base text-zinc-900 placeholder:text-zinc-400 focus:outline-none"
              />
              <button
                type="submit"
                disabled={busy || question.trim().length < 3}
                className="flex min-h-[44px] items-center gap-2 rounded-xl bg-teal-700 px-5 font-medium text-white transition hover:bg-teal-800 active:translate-y-px disabled:cursor-not-allowed disabled:opacity-40"
              >
                {busy ? 'Asking…' : 'Ask'}
                <span aria-hidden>→</span>
              </button>
            </div>
          </form>

          <div className="mt-3 flex flex-wrap gap-2">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                type="button"
                onClick={() => submit(undefined, ex)}
                className="min-h-[32px] rounded-full border border-zinc-200 bg-white px-3 py-1 text-xs text-zinc-600 transition-colors hover:border-teal-300 hover:text-zinc-900"
              >
                {ex}
              </button>
            ))}
          </div>

          <div className="mt-5">
            <Switch checked={clarify} onChange={setClarify} />
          </div>

          <div className="mt-12 space-y-4" aria-live="polite">
            {error && <p className="rounded-xl bg-red-50 p-4 text-sm text-red-700">{error}</p>}
            {busy && res?.status !== 'needs_clarification' && <Skeleton />}
            {!busy && !res && !error && <EmptyState />}
            {res?.status === 'needs_clarification' && (
              <ClarificationPanel
                items={res.clarifications}
                picked={picked}
                onPick={(r) => setPicked((p) => ({ ...p, [r.term]: r }))}
                onSubmit={() => void run(res.question, Object.values(picked))}
                busy={busy}
              />
            )}
            {!busy && res?.status === 'answered' && <AnswerPanel res={res} ms={ms} />}
            {!busy && res && failed && (
              <p className="rounded-xl bg-red-50 p-4 text-sm text-red-700">
                {res.status === 'unsupported'
                  ? "I can't answer this question shape yet. Try rephrasing, or ask about customers, orders, products or payments."
                  : res.detail}
              </p>
            )}
          </div>
        </main>
        <Rail onTry={(q) => submit(undefined, q)} />
      </div>
    </div>
  )
}
