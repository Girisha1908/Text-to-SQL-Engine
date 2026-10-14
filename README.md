# Ask Your Data

**Text-to-SQL that asks what you mean before it answers.**

Live demo: https://ask-your-data-sigma.vercel.app/

Ask an e-commerce database a question in plain English and get the answer — but when the question can be
read more than one way, the system stops and asks which meaning you want *before* it writes any SQL.

> "Show me last month's best customer."
>
> Best by what? **Highest spend** (C-WHALE, R$ 18,295), **most orders** (C-MANY, 14) or **came back most
> often** (C-FREQ, 10 different days)? Three readings, three different customers. A system that guesses is
> confidently wrong for two out of three people asking.

## Results

On 30 labelled questions (16 clear, 14 ambiguous), with the offline generator:

| | Without clarification | With clarification engine |
|---|---|---|
| All questions | 21/30 (70%) | **30/30 (100%)** |
| Ambiguous questions | 5/14 (36%) | **14/14 (100%)** |
| Clear questions | 16/16 | 16/16 |

- Asked on 14/14 ambiguous questions, **0/16** clear ones (no over-asking).
- Every ambiguous case is checked to be *discriminating*: the other readings really return a different answer.
- Offline, both arms share one rule-based generator, so this isolates the effect of asking vs. guessing.
  `python scripts/eval_ask.py --provider groq` runs the same experiment with an LLM.

Full report: [docs/eval-results.md](docs/eval-results.md).

## How it works

```text
question ─► glossary scan ─► ambiguous? ──yes──► ask: "What does 'best customer' mean?" ─► user picks
                                 │no                                                            │
                                 ▼                                                              ▼
                          generate SQL ◄────────────────────────────────────── question + chosen meaning
                                 │
                          SQL guard (one SELECT only) ─► read-only transaction, 5 s timeout ─► rows + assumptions
```

- **Business glossary (semantic layer).** Seven phrases that genuinely mean different things —
  *best customer, best product, best category, new customers, recent, big orders, active customers* — each
  with plain-language options. It doesn't ask when the question already settles it
  ("top 5 customers **by total spend**").
- **Governed defaults.** Things with one approved meaning are applied and shown, not asked:
  revenue excludes canceled orders, "last month" is the previous calendar month.
- **Two generators, one interface.** An offline rule-based planner (default, free, no network) and optional
  Groq / Gemini free-tier LLMs with JSON output validated by Pydantic, plus one repair retry.
- **Safe by construction.** Only a single `SELECT`/`WITH` passes the guard, and it runs inside
  `SET TRANSACTION READ ONLY` with a statement timeout and row cap, then rolls back.
- **Stateless API.** The client re-sends the question with the chosen options; no sessions.

Design decisions, API contract and risks: [docs/PRD.md](docs/PRD.md) · build plan: [docs/PLAN.md](docs/PLAN.md)
· UI design system: [docs/DESIGN.md](docs/DESIGN.md).

## Stack

Python · FastAPI · Pydantic · SQLAlchemy · PostgreSQL · React · TypeScript · Tailwind · Groq/Gemini (optional).
Cost: ₹0.

## Run locally

Requires Python 3.12+, Node 20+, Docker.

```bash
docker compose up -d                       # Postgres on localhost:5433
cp .env.example .env
python -m venv .venv
.venv/Scripts/activate                     # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
python scripts/seed_ask_demo.py            # demo store data
uvicorn app.main:app --app-dir backend --port 8001
```

In a second terminal:

```bash
cd frontend
npm install
npm run dev                                # http://localhost:5173
```

## Deployment

One Vercel project serves both halves (`vercel.json`, Vercel Services): `/api/*` goes to the FastAPI backend
(`backend/`, a Python function) and everything else to the Vite build (`frontend/`). The database is a free
Neon Postgres. Environment variables on Vercel:

| Variable | Value |
|---|---|
| `DATABASE_URL` | Neon connection string (pooled) |
| `ASK_AS_OF_DATE` | `2026-10-13` (the demo data's "today") |
| `ASK_LLM_PROVIDER` | `offline` (or `groq` / `gemini` with the matching key) |

Seed the hosted database once: `DATABASE_URL=<neon url> python scripts/seed_ask_demo.py`.
`GET /api/health` is the uptime-monitor endpoint; it does not touch the database.

## Tests and evaluation

```bash
pytest                                     # 88 unit tests
ASK_TEST_DATABASE_URL=postgresql+psycopg://askdata:askdata@localhost:5433/askdata pytest   # + Postgres integration
python scripts/eval_ask.py                 # rewrites docs/eval-results.md
```

## API

```http
POST /api/ask
{"question": "Show me last month's best customer."}
→ {"status": "needs_clarification", "clarifications": [{"term": "best_customer", "options": [...]}]}

POST /api/ask
{"question": "Show me last month's best customer.",
 "clarifications": [{"term": "best_customer", "option_id": "orders"}]}
→ {"status": "answered", "sql": "SELECT ...", "columns": [...], "rows": [["C-MANY", 14]], "assumptions": [...]}
```

## Project layout

```text
backend/app/ask/      engine, glossary, planner, LLM clients, SQL guard, executor
backend/app/api/      POST /api/ask
backend/tests/        unit + integration tests
scripts/              seed data, evaluation harness
eval/cases.json       30 labelled questions with gold SQL
sql/schema.sql        demo schema
frontend/             React UI
docs/                 PRD, plan, design system, evaluation results
```

## License

MIT
