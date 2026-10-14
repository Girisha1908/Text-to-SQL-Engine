"""Measure answer accuracy with and without the clarification engine.

For every labelled question:
  direct  : mode=direct — SQL is generated straight away; ambiguity is resolved by guessing.
  engine  : mode=engine — if the engine asks, a simulated user answers with the case's
            intended meaning, then the question is re-sent with the clarifications.
A run is correct when its result matches the gold SQL's result (see `results_match`).

Usage (from the repo root):
  python scripts/eval_ask.py                    # offline planner, no network
  python scripts/eval_ask.py --provider groq    # needs GROQ_API_KEY
  python scripts/eval_ask.py --reseed           # rebuild ask_demo first
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine  # noqa: E402

from app.ask import glossary, planner  # noqa: E402
from app.ask.config import get_ask_settings  # noqa: E402
from app.ask.engine import AskEngine  # noqa: E402
from app.ask.executor import PostgresExecutor, QueryResult  # noqa: E402
from app.ask.llm import make_llm  # noqa: E402
from app.ask.schemas import AskRequest, AskResponse, ResolvedTerm  # noqa: E402

CASES = ROOT / "eval" / "cases.json"
REPORT = ROOT / "docs" / "eval-results.md"
RAW = ROOT / "data" / "ask_eval.json"


def _norm(v):
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float, Decimal)):
        return str(Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    s = str(v)
    try:  # numeric strings (rare) compare as numbers
        return str(Decimal(s).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except InvalidOperation:
        return s[:10] if len(s) >= 10 and s[4] == "-" and s[7] == "-" else s  # ISO dates -> YYYY-MM-DD


def _column(rows: list[list], i: int) -> tuple:
    return tuple(sorted((_norm(r[i]) for r in rows), key=repr))


def results_match(gold: QueryResult, columns: list[str], rows: list[list], match_columns: list[str] | None) -> bool:
    """Same row count, and every gold column's values appear as some predicted column (order-free)."""
    if len(gold.rows) != len(rows):
        return False
    wanted = [gold.columns.index(c) for c in match_columns] if match_columns else range(len(gold.columns))
    predicted = [_column(rows, i) for i in range(len(columns))]
    return all(_column(gold.rows, i) in predicted for i in wanted)


def run_engine(engine: AskEngine, case: dict) -> tuple[AskResponse, list[str], list[str]]:
    """Ask in engine mode, answering clarification questions as the simulated user."""
    asked, unexpected, clar = [], [], []
    resp = engine.ask(AskRequest(question=case["question"], mode="engine"))
    for _ in range(2):
        if resp.status != "needs_clarification":
            break
        for c in resp.clarifications:
            asked.append(c.term)
            option_id = case.get("intent", {}).get(c.term)
            if option_id is None:  # engine asked something the user didn't expect; pick the first option
                unexpected.append(c.term)
                option_id = c.options[0].id
            opt = next((o for o in c.options if o.id == option_id), c.options[0])
            clar.append(ResolvedTerm(term=c.term, option_id=opt.id, definition=opt.definition))
        resp = engine.ask(AskRequest(question=case["question"], mode="engine", clarifications=clar))
    return resp, asked, unexpected


def discriminating(executor: PostgresExecutor, case: dict, gold: QueryResult, as_of: date) -> bool:
    """Do the other readings of the ambiguous term really give a different answer?"""
    for term_id, intended in case["intent"].items():
        for opt in glossary.TERMS_BY_ID[term_id].options:
            if opt.id == intended:
                continue
            alt = executor.run(planner.plan(case["question"], as_of, {term_id: opt.id}).sql)
            if results_match(gold, alt.columns, alt.rows, case.get("match_columns")):
                return False
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["offline", "groq", "gemini"])
    ap.add_argument("--reseed", action="store_true")
    args = ap.parse_args()

    s = get_ask_settings()
    if args.provider:
        s = s.model_copy(update={"ASK_LLM_PROVIDER": args.provider})
    if args.reseed:
        from scripts.seed_ask_demo import seed
        print("Seeded:", seed(s.database_url))

    spec = json.loads(CASES.read_text(encoding="utf-8"))
    as_of = date.fromisoformat(spec["as_of"])
    executor = PostgresExecutor(create_engine(s.database_url), s.ASK_DB_SCHEMA, 1000, 30000)
    engine = AskEngine(executor, as_of, make_llm(s))

    records = []
    for case in spec["cases"]:
        gold = executor.run(case["gold_sql"])
        direct = engine.ask(AskRequest(question=case["question"], mode="direct"))
        clarified, asked, unexpected = run_engine(engine, case)
        mc = case.get("match_columns")
        rec = {
            "id": case["id"], "question": case["question"], "ambiguous": case["ambiguous"],
            "intent": case.get("intent", {}),
            "direct_ok": direct.status == "answered" and results_match(gold, direct.columns, direct.rows, mc),
            "engine_ok": clarified.status == "answered" and results_match(gold, clarified.columns, clarified.rows, mc),
            "asked": asked, "unexpected": unexpected,
            "direct_status": direct.status, "engine_status": clarified.status,
            "direct_sql": direct.sql, "engine_sql": clarified.sql,
            "direct_detail": direct.detail, "engine_detail": clarified.detail,
            "gold_preview": gold.rows[:3],
            "discriminating": discriminating(executor, case, gold, as_of) if case["ambiguous"] else None,
        }
        records.append(rec)
        print(f"{rec['id']}  direct={'OK ' if rec['direct_ok'] else 'BAD'}  engine={'OK ' if rec['engine_ok'] else 'BAD'}"
              f"  asked={','.join(asked) or '-'}")

    write_report(records, engine.generator, as_of)
    RAW.parent.mkdir(parents=True, exist_ok=True)
    RAW.write_text(json.dumps(records, indent=2, default=str), encoding="utf-8")
    print(f"\nReport: {REPORT.relative_to(ROOT)}   Raw: {RAW.relative_to(ROOT)}")


def _pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "n/a"


def write_report(records: list[dict], generator: str, as_of: date) -> None:
    amb = [r for r in records if r["ambiguous"]]
    clear = [r for r in records if not r["ambiguous"]]
    ok = Counter()
    for r in records:
        for arm in ("direct", "engine"):
            ok[(arm, "all")] += r[f"{arm}_ok"]
            ok[(arm, "amb" if r["ambiguous"] else "clear")] += r[f"{arm}_ok"]

    asked_amb = sum(bool(r["asked"]) for r in amb)
    asked_clear = sum(bool(r["asked"]) for r in clear)
    weak = [r["id"] for r in amb if r["discriminating"] is False]
    lines = [
        "# Ask Your Data — Evaluation Results",
        "",
        f"> Generated by `scripts/eval_ask.py` on {datetime.now():%Y-%m-%d %H:%M} · generator: **{generator}** · "
        f"as-of date: {as_of} · cases: {len(records)} ({len(amb)} ambiguous, {len(clear)} clear)",
        "",
        "## Correct answers",
        "",
        "| | Without clarification (`direct`) | With clarification engine (`engine`) |",
        "|---|---|---|",
        f"| **All questions** | {_pct(ok['direct', 'all'], len(records))} | {_pct(ok['engine', 'all'], len(records))} |",
        f"| Ambiguous questions | {_pct(ok['direct', 'amb'], len(amb))} | {_pct(ok['engine', 'amb'], len(amb))} |",
        f"| Clear questions | {_pct(ok['direct', 'clear'], len(clear))} | {_pct(ok['engine', 'clear'], len(clear))} |",
        "",
        "## Clarification behaviour",
        "",
        f"- Asked on ambiguous questions (recall): {_pct(asked_amb, len(amb))}",
        f"- Asked on clear questions (false clarifications): {_pct(asked_clear, len(clear))}",
        f"- Questions asked per ambiguous question: {sum(len(r['asked']) for r in amb) / max(len(amb), 1):.2f}",
        f"- Unexpected questions (term the simulated user had no answer for): "
        f"{sum(len(r['unexpected']) for r in records)}",
        f"- Ambiguous cases where another reading gives the same answer (not discriminating): "
        f"{', '.join(weak) if weak else 'none'}",
        "",
    ]
    if generator == "offline":
        lines += [
            "> **Read this before quoting the numbers.** With the offline generator both arms use the same "
            "rule-based planner, so the difference measures the *clarification policy* (ask vs. guess the "
            "default), not language understanding. Run with `--provider groq` or `--provider gemini` for the "
            "LLM experiment.",
            "",
        ]
    lines += [
        "## Per question",
        "",
        "| id | question | intended meaning | direct | engine | asked |",
        "|---|---|---|---|---|---|",
    ]
    for r in records:
        intent = ", ".join(f"{k}={v}" for k, v in r["intent"].items()) or "—"
        mark = lambda b, st: "✅" if b else f"❌ {'' if st == 'answered' else st}".strip()  # noqa: E731
        lines.append(f"| {r['id']} | {r['question']} | {intent} | {mark(r['direct_ok'], r['direct_status'])} | "
                     f"{mark(r['engine_ok'], r['engine_status'])} | {', '.join(r['asked']) or '—'} |")
    lines += ["", "Raw SQL for every run: `data/ask_eval.json` (git-ignored)."]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
