# PRD — Ask Your Data: Text-to-SQL with a Clarification Engine

> Author: Anamala Girisha · Status: v1 implemented · Last updated: 2026-10-15
> Related: `docs/PLAN.md`, `docs/DESIGN.md`, `docs/eval-results.md`

## 1. Problem

A business user wants to ask an e-commerce database questions in plain English:

> "How many new customers signed up last month?"

Generating SQL for that is easy. The hard part is that many business questions are
**underspecified**:

> "Show me last month's best customer."

"Best" can mean highest spend, most orders, or most frequent return visits. All three
give different customers. A typical text-to-SQL demo picks one reading silently and
returns a confident, wrong answer. The user cannot tell it guessed.

## 2. Goal

Build a natural-language query layer that:

1. Detects when a question has more than one reasonable reading that changes the answer.
2. Asks the user which reading they mean, with concrete options, **before** writing SQL.
3. Generates read-only PostgreSQL, runs it safely, and returns the rows plus the
   assumptions it made.
4. Measures, on a fixed test set, how many questions are answered correctly **with**
   the clarification engine versus **without** it.

### Success metrics

| Metric | Target |
|---|---|
| Execution accuracy on ambiguous questions, engine vs. direct | Engine clearly higher (the point of the project) |
| Execution accuracy on clear questions | Engine ≥ direct (asking must not hurt) |
| False clarification rate (asked on a clear question) | ≤ 10% |
| Clarification recall (asked on an ambiguous question) | ≥ 90% |
| Cost | ₹0 — runs fully offline by default; free-tier LLM optional |

## 3. Users

- **Business user** (primary): founder, marketer, ops lead. Knows the business, not SQL.
- **Analyst** (secondary): wants to see the SQL behind an answer and trust it.

## 4. Scope

### In scope (v1)

- `POST /api/ask` endpoint with a two-turn clarification flow (stateless).
- A **business glossary** (semantic layer) that holds:
  - *Ambiguous terms* — must be clarified (e.g. "best customer").
  - *Governed defaults* — terms with one company-approved meaning that are applied
    and stated, not asked (e.g. "revenue excludes canceled orders").
- Two SQL generators behind one interface:
  - **Offline planner** (default, no network, ₹0): deterministic intent → SQL templates.
  - **LLM** (optional): Groq or Gemini free tier, JSON structured output validated by Pydantic.
- SQL safety guard + read-only, time-limited execution.
- Demo dataset (customers, orders, order_items, products, payments) in a separate
  Postgres schema `ask_demo`, seeded deterministically.
- Evaluation harness: 30 labelled questions, simulated user, execution-match scoring,
  results written to `docs/eval-results.md`.
- Minimal React page `/ask` to try the flow.

### Out of scope (v1)

- Multi-turn chat memory beyond one clarification round.
- Charts / visualisation of results.
- Per-user database roles and row-level security (see §10).
- Writing to the database in any form.
- Ingesting arbitrary uploaded datasets (the schema is fixed to the five demo tables).

## 5. User flow

```text
User question
     │
     ▼
Glossary scan ──► ambiguous terms found? ──┐
     │                                      │ (LLM mode: LLM may add more)
     ▼ no                                   ▼ yes
Generate SQL                      Return needs_clarification
     │                            { term, prompt, options[] }
     ▼                                      │
SQL guard                          User picks options
     │                                      │
     ▼                                      ▼
Read-only execution  ◄──────────── Re-send question + clarifications
     │
     ▼
Answer { rows, sql, assumptions, interpretation }
```

### Example

```text
Q: Show me last month's best customer.

A: needs_clarification
   "What does 'best customer' mean here?"
   ( ) Highest spend      — total value of non-canceled orders
   ( ) Most orders        — number of non-canceled orders placed
   ( ) Came back most     — number of distinct days with an order

Q: (same) + best_customer = most_orders

A: answered
   customer_id  orders
   C-MANY       14
   Assumptions:
   • "last month" = previous calendar month (2026-09-01 to 2026-09-30)
   • Canceled orders are excluded
```

## 6. API contract

`POST /api/ask`

Request:

```json
{
  "question": "Show me last month's best customer.",
  "mode": "engine",
  "clarifications": [
    {"term": "best_customer", "option_id": "orders", "definition": "Most orders placed"}
  ]
}
```

- `mode`: `"engine"` (default, clarify first) or `"direct"` (never ask — baseline).
- `clarifications`: the options the user picked in the previous turn.
  `definition` lets LLM-proposed options round-trip without server state.

Response — needs clarification:

```json
{
  "status": "needs_clarification",
  "question": "...",
  "clarifications": [
    {"term": "best_customer", "prompt": "What does 'best customer' mean here?",
     "source": "glossary",
     "options": [{"id": "revenue", "label": "Highest spend", "definition": "..."}]}
  ]
}
```

Response — answered:

```json
{
  "status": "answered",
  "question": "...",
  "sql": "SELECT ...",
  "columns": ["customer_id", "orders"],
  "rows": [["C-MANY", 14]],
  "row_count": 1,
  "truncated": false,
  "assumptions": ["..."],
  "interpretation": {"best_customer": "orders"},
  "generator": "offline"
}
```

Response — cannot answer: `{"status": "unsupported" | "rejected" | "error", "detail": "..."}`
(HTTP 200 for these so the UI can show the message; 422 for malformed requests.)

## 7. Domain glossary

| Term | Meaning in this feature |
|---|---|
| **Ambiguous term** | A phrase with ≥2 plausible readings that give different results and no company default. Must be clarified. |
| **Governed default** | A phrase with one approved meaning. Applied silently and listed in `assumptions`. |
| **Interpretation** | The map `term → chosen option` used to build the SQL. |
| **As-of date** | "Today" for relative dates. `ASK_AS_OF_DATE` env, else the real date. |
| **Valid order** | An order whose status is not `canceled`. |
| **Execution match** | Generated SQL's result equals the gold SQL's result (§9). |

### Ambiguous terms (v1)

| Term id | Triggers on | Options |
|---|---|---|
| `best_customer` | best/top/number one/most valuable customer, buyer, shopper | revenue · orders · frequency (distinct order days) |
| `best_product` | best/top/best-selling/most popular product, item | revenue · units |
| `best_category` | best/top category, category performed best | revenue · units |
| `new_customers` | new customers (unless "signed up/registered/joined") | signup date in period · first order in period |
| `recent` | recent, recently, lately (with no explicit period) | last 7 · 30 · 90 days |
| `large_order` | big/large/huge/high-value orders | value > ₹1,000 · top 10% by value |
| `active_customers` | active customers (with no explicit period) | ordered in last 30 · 90 · 365 days |

A term is **not** asked when the question already disambiguates it
(e.g. "top 5 customers **by total spend**", "new customers who **signed up**").

### Governed defaults (v1)

- Revenue = sum of `order_value` of valid orders.
- Canceled orders are excluded from every metric unless the question is about cancellations.
- "Last month" = previous calendar month. "This month/year" = start of period to as-of date.
- "Last N days" = the N full days before the as-of date.
- No period mentioned = all time.

## 8. Architecture

```text
backend/app/
├── api/ask.py                 POST /api/ask
└── ask/
    ├── config.py              AskSettings (env: ASK_*)
    ├── schemas.py             Pydantic request/response + LLM structured outputs
    ├── glossary.py            ambiguous terms + governed defaults + detection
    ├── periods.py             "last month" → [start, end) dates
    ├── planner.py             offline generator: intent → SQL template
    ├── llm.py                 Groq / Gemini JSON clients (httpx), schema-validated
    ├── sql_guard.py           single SELECT/WITH only, denylist
    ├── executor.py            read-only txn, statement_timeout, search_path, row cap
    └── engine.py              orchestration: detect → clarify → generate → guard → run
sql/schema.sql                 demo schema DDL (ask_demo)
scripts/seed_ask_demo.py       deterministic demo data
scripts/eval_ask.py            evaluation harness → docs/eval-results.md
eval/cases.json                     30 labelled questions + gold SQL
frontend/src/pages/Ask.tsx     UI
```

### Key decisions

1. **Glossary first, LLM second.** Known business ambiguities live in a reviewed
   glossary, the same idea as a dbt/Cube semantic layer. Detection is deterministic,
   testable and free. The LLM only *adds* ambiguities the glossary misses. Reason:
   an LLM asked "is this ambiguous?" is inconsistent run to run; a company's metric
   definitions should not depend on sampling temperature.
2. **Governed defaults instead of asking everything.** Asking about "revenue" on every
   question makes the tool unusable. Terms with an approved definition are applied and
   shown as assumptions.
3. **Stateless clarification.** The client re-sends the question plus chosen options.
   No session store, nothing to expire.
4. **Offline generator is the default.** The project must cost ₹0, run without paid APIs
   and work fully locally. Groq/Gemini free tiers are opt-in via env.
5. **Read-only by construction.** Guard rejects anything but one SELECT/WITH; the
   executor also runs inside `SET TRANSACTION READ ONLY` with a 5 s timeout and a row
   cap, then rolls back. The guard is a convenience; the transaction is the control.
6. **Separate `ask_demo` schema.** Demo data lives in its own schema so the same database
   can hold real data later; point `ASK_DB_SCHEMA` at another schema with the same tables.
7. **Fair baseline.** "Without clarification" (`mode=direct`) uses the same glossary
   defaults and the same generator; it only skips the asking step and lets the
   generator choose. This isolates the effect of clarification.

## 9. Evaluation

- 30 questions: 16 clear, 14 ambiguous. Several ambiguous questions appear more than
  once with different intended meanings — exactly the case where a single guess
  cannot be right for every user.
- Each case stores the **intended interpretation** (what the simulated user picks when
  asked) and a hand-written **gold SQL**.
- **Execution match**: run gold and generated SQL; correct when row counts match and
  every gold column's values (as a multiset, numbers rounded to 2 dp) appear as some
  column of the generated result. Extra columns are allowed.
- **Sanity check**: for each ambiguous case, the harness confirms the other readings
  really give different results, so the case is discriminating.
- Reported: accuracy (overall / ambiguous / clear) for direct vs. engine, clarification
  recall, false clarification rate, average questions asked.
- Run: `python scripts/eval_ask.py` (offline) or `--provider groq|gemini`.

**Caveat, stated plainly:** in offline mode both arms use the same rule-based planner,
so offline numbers measure the clarification *policy*, not language understanding.
The LLM run is the real experiment.

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| LLM writes destructive SQL | Guard + read-only transaction + timeout + rollback |
| LLM reads other schemas (`public`, `pg_catalog`) | Acceptable for a local single-user tool. Before multi-user: dedicated read-only role with `USAGE` on `ask_demo` only |
| Over-asking annoys users | Governed defaults; skip when the question already disambiguates; false-clarification rate tracked |
| Glossary misses a phrasing | LLM mode adds ambiguities; eval includes paraphrases |
| Free-tier rate limits / model renames | Model name is configurable (`ASK_LLM_MODEL`); offline fallback always works |
| Eval overfits to the glossary | Gold SQL written independently of planner templates; caveat in §9 |

## 11. Open questions

- Should a user's clarification be remembered as their personal default ("for me, best
  customer always means revenue")? Not in v1.
- Should the glossary move to a YAML file editable by non-developers? Python for now;
  move when someone other than a developer needs to edit it.
