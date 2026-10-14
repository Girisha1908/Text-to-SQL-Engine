# Build Plan — Ask Your Data (Text-to-SQL + Clarification Engine)

Spec: `docs/PRD.md`.
Each phase ends with its tests passing before the next one starts.

**Status (2026-10-14):** Phases A–F done. 159 backend tests pass (+1 Postgres integration test, run with
`ASK_TEST_DATABASE_URL`). Frontend builds. Phase G open: live LLM eval needs a free Groq/Gemini key.

## Phase A — Data foundation

| # | Ticket | Files | Done when |
|---|---|---|---|
| A1 | Demo schema DDL (customers, orders, order_items, products, payments) in schema `ask_demo`, canonical column names | `sql/schema.sql` | DDL applies cleanly on Postgres 16 |
| A2 | Deterministic seed with planted cases (top spender ≠ most orders ≠ most visits last month) | `scripts/seed_ask_demo.py` | Re-running gives identical data |

## Phase B — Safety and execution

| # | Ticket | Files | Done when |
|---|---|---|---|
| B1 | SQL guard: one SELECT/WITH, no comments, write/admin keyword denylist | `backend/app/ask/sql_guard.py` | Unit tests cover accept + reject cases |
| B2 | Executor: read-only txn, `statement_timeout`, `search_path`, UTC, row cap, always rollback | `backend/app/ask/executor.py` | Runs against seeded DB; write attempt fails |
| B3 | Settings (`ASK_*` env) | `backend/app/ask/config.py`, `.env.example` | Defaults work with no env |

## Phase C — Understanding the question

| # | Ticket | Files | Done when |
|---|---|---|---|
| C1 | Period parser (last month, this year, last N days, in Aug 2026, …) | `backend/app/ask/periods.py` | Unit tests per phrase |
| C2 | Glossary: ambiguous terms (+ skip rules) and governed defaults | `backend/app/ask/glossary.py` | Detects the 7 terms; no hit on disambiguated phrasings |
| C3 | Pydantic schemas: API request/response, LLM structured outputs | `backend/app/ask/schemas.py` | Imported by engine + API |

## Phase D — SQL generation

| # | Ticket | Files | Done when |
|---|---|---|---|
| D1 | Offline planner: intents (counts, revenue, AOV, top-N, by category/month/state/payment) → SQL | `backend/app/ask/planner.py` | Every eval question produces SQL |
| D2 | LLM providers (Groq OpenAI-compatible, Gemini) via httpx, JSON mode, Pydantic validation, one repair retry | `backend/app/ask/llm.py` | Mock-transport tests pass |
| D3 | Engine orchestration: detect → clarify → generate → guard → execute; `engine` vs `direct` mode | `backend/app/ask/engine.py` | Engine tests with fake executor pass |

## Phase E — API and UI

| # | Ticket | Files | Done when |
|---|---|---|---|
| E1 | `POST /api/ask`, router registration, docs | `backend/app/api/ask.py`, `backend/app/main.py` | TestClient flow: ask → clarify → answer |
| E2 | `/ask` page: question box, clarification options, result table, SQL behind "View technical details", clarify on/off toggle | `frontend/src/pages/Ask.tsx`, `frontend/src/services/askApi.ts` | `npm run build` passes; works against API |

## Phase F — Measurement

| # | Ticket | Files | Done when |
|---|---|---|---|
| F1 | 30 labelled cases with intended interpretation + gold SQL | `eval/cases.json` | Gold SQL runs; ambiguous cases pass the discrimination check |
| F2 | Harness: simulated user, execution match, direct vs engine, writes report | `scripts/eval_ask.py` | `docs/eval-results.md` generated |
| F3 | Optional DB integration test (skipped without `ASK_TEST_DATABASE_URL`) | `backend/tests/test_ask.py` | Passes when DB available |

## Phase G — Ship checks

- Full `pytest` run (existing suites must still pass).
- Security pass on the SQL path (guard + executor).
- Over-engineering pass (delete what isn't needed).
- Live LLM eval once a free Groq/Gemini key is set: `python scripts/eval_ask.py --provider groq`.
