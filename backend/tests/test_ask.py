"""Tests for Ask Your Data (text-to-SQL with clarification).

Unit tests need no database. The integration test at the bottom runs only when
ASK_TEST_DATABASE_URL points at a Postgres you don't mind being reseeded.
"""

import json
import os
from datetime import date
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.ask import get_engine
from app.main import app
from app.ask import glossary, planner
from app.ask.engine import AskEngine
from app.ask.executor import QueryResult
from app.ask.llm import GeminiClient, GroqClient, LLMError, structured
from app.ask.periods import parse_period
from app.ask.schemas import AskRequest, LLMSql, ResolvedTerm
from app.ask.sql_guard import UnsafeSQL, check_sql

AS_OF = date(2026, 10, 13)
CASES = json.loads((Path(__file__).resolve().parents[2] / "eval" / "cases.json")
                   .read_text(encoding="utf-8"))["cases"]


class FakeExecutor:
    def __init__(self):
        self.sql: list[str] = []

    def run(self, sql: str) -> QueryResult:
        self.sql.append(check_sql(sql))
        return QueryResult(columns=["x"], rows=[[1]], truncated=False)


# --- SQL guard ----------------------------------------------------------------


@pytest.mark.parametrize("sql", [
    "SELECT 1",
    "select count(*) from orders;",
    "WITH t AS (SELECT 1 AS a) SELECT a FROM t",
    "SELECT * FROM orders WHERE order_status = 'canceled'",
    "SELECT 'drop table x; -- not code' AS s",
])
def test_guard_accepts_reads(sql):
    assert check_sql(sql)


@pytest.mark.parametrize("sql", [
    "DELETE FROM orders",
    "SELECT 1; DROP TABLE orders",
    "WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d",
    "SELECT 1 -- sneaky",
    "SELECT /* x */ 1",
    "SELECT pg_sleep(10)",
    "SELECT set_config('search_path', 'public', false)",
    "UPDATE orders SET order_value = 0",
    "EXPLAIN ANALYZE SELECT 1",
    "",
])
def test_guard_rejects_everything_else(sql):
    with pytest.raises(UnsafeSQL):
        check_sql(sql)


# --- periods -------------------------------------------------------------------


@pytest.mark.parametrize("phrase,start,end", [
    ("last month", date(2026, 9, 1), date(2026, 10, 1)),
    ("last month's best customer", date(2026, 9, 1), date(2026, 10, 1)),
    ("this month", date(2026, 10, 1), date(2026, 10, 14)),
    ("last 7 days", date(2026, 10, 6), date(2026, 10, 13)),
    ("this year", date(2026, 1, 1), date(2026, 10, 14)),
    ("last year", date(2025, 1, 1), date(2026, 1, 1)),
    ("in August 2026", date(2026, 8, 1), date(2026, 9, 1)),
    ("for 2025", date(2025, 1, 1), date(2026, 1, 1)),
    ("last quarter", date(2026, 7, 1), date(2026, 10, 1)),
    ("last week", date(2026, 10, 5), date(2026, 10, 12)),
])
def test_parse_period(phrase, start, end):
    p = parse_period(phrase, AS_OF)
    assert (p.start, p.end) == (start, end)


def test_no_period_means_none():
    assert parse_period("Who is our best customer?", AS_OF) is None


# --- glossary detection ---------------------------------------------------------


def _detected(q: str) -> list[str]:
    return [t.id for t in glossary.detect(q, has_period=parse_period(q, AS_OF) is not None)]


@pytest.mark.parametrize("q,terms", [
    ("Show me last month's best customer.", ["best_customer"]),
    ("Who is our number one customer?", ["best_customer"]),
    ("What was our best-selling product last month?", ["best_product"]),
    ("Which category performed best last month?", ["best_category"]),
    ("How many new customers did we get last month?", ["new_customers"]),
    ("How many orders came in recently?", ["recent"]),
    ("How many big orders did we have last month?", ["large_order"]),
    ("How many active customers do we have?", ["active_customers"]),
])
def test_detects_ambiguous_terms(q, terms):
    assert _detected(q) == terms


@pytest.mark.parametrize("q", [
    "Top 5 customers by total spend last month",
    "How many new customers signed up last month?",
    "Which product sold the most units last month?",
    "How many active customers did we have last month?",
    "How many orders came in recently, in the last 7 days?",
    "How many big orders over 1000 last month?",
    "What was our total revenue last month?",
])
def test_disambiguated_questions_are_not_flagged(q):
    assert _detected(q) == []


def test_eval_labels_agree_with_glossary():
    for case in CASES:
        expected = sorted(case.get("intent", {}))
        assert sorted(_detected(case["question"])) == expected, case["id"]


# --- offline planner -------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_planner_covers_every_eval_question(case):
    plan = planner.plan(case["question"], AS_OF, case.get("intent", {}))
    check_sql(plan.sql)


def test_planner_uses_the_chosen_meaning():
    q = "Show me last month's best customer."
    by = {opt: planner.plan(q, AS_OF, {"best_customer": opt}).sql for opt in ("revenue", "orders", "frequency")}
    assert "SUM(o.order_value)" in by["revenue"]
    assert "COUNT(*) AS orders" in by["orders"]
    assert "COUNT(DISTINCT CAST(o.order_date AS DATE))" in by["frequency"]
    assert all("DATE '2026-09-01'" in s and "DATE '2026-10-01'" in s for s in by.values())


def test_planner_unsupported():
    with pytest.raises(planner.Unsupported):
        planner.plan("What is the weather in Recife?", AS_OF, {})


# --- engine (offline) -------------------------------------------------------------


def test_engine_asks_before_answering_ambiguous_question():
    ex = FakeExecutor()
    resp = AskEngine(ex, AS_OF).ask(AskRequest(question="Show me last month's best customer."))
    assert resp.status == "needs_clarification"
    assert [o.id for o in resp.clarifications[0].options] == ["revenue", "orders", "frequency"]
    assert ex.sql == []  # nothing ran


def test_engine_answers_after_clarification():
    ex = FakeExecutor()
    resp = AskEngine(ex, AS_OF).ask(AskRequest(
        question="Show me last month's best customer.",
        clarifications=[ResolvedTerm(term="best_customer", option_id="orders")],
    ))
    assert resp.status == "answered"
    assert resp.interpretation == {"best_customer": "orders"}
    assert "COUNT(*) AS orders" in resp.sql
    assert any("your choice" in a for a in resp.assumptions)


def test_engine_answers_clear_question_without_asking():
    resp = AskEngine(FakeExecutor(), AS_OF).ask(AskRequest(question="How many new customers signed up last month?"))
    assert resp.status == "answered"
    assert "c.created_at" in resp.sql


def test_direct_mode_guesses_and_says_so():
    resp = AskEngine(FakeExecutor(), AS_OF).ask(
        AskRequest(question="Show me last month's best customer.", mode="direct"))
    assert resp.status == "answered"
    assert resp.interpretation == {"best_customer": "revenue"}
    assert any("(assumed)" in a for a in resp.assumptions)


def test_engine_rejects_unknown_option():
    resp = AskEngine(FakeExecutor(), AS_OF).ask(AskRequest(
        question="Show me last month's best customer.",
        clarifications=[ResolvedTerm(term="best_customer", option_id="vibes")],
    ))
    assert resp.status == "rejected"


# --- engine (LLM, faked) -------------------------------------------------------------


class FakeLLM:
    name = "fake"

    def __init__(self, replies: list[str]):
        self.replies, self.prompts = replies, []

    def complete_json(self, system: str, user: str) -> str:
        self.prompts.append(user)
        return self.replies.pop(0)


def test_llm_can_add_an_ambiguity_the_glossary_missed():
    extra = {"ambiguities": [{"term": "loyal", "prompt": "Loyal how?", "options": [
        {"id": "repeat", "label": "Repeat buyers", "definition": "2+ orders"},
        {"id": "long", "label": "Long-time", "definition": "Customer for 1+ year"}]}]}
    llm = FakeLLM([json.dumps(extra)])
    resp = AskEngine(FakeExecutor(), AS_OF, llm).ask(AskRequest(question="How many loyal customers do we have?"))
    assert resp.status == "needs_clarification"
    assert resp.clarifications[0].source == "llm"


def test_llm_generation_receives_the_users_definition():
    llm = FakeLLM([json.dumps({"sql": "SELECT 1 AS x", "assumptions": []})])
    resp = AskEngine(FakeExecutor(), AS_OF, llm).ask(AskRequest(
        question="Show me last month's best customer.",
        clarifications=[ResolvedTerm(term="best_customer", option_id="frequency")],
    ))
    assert resp.status == "answered" and resp.generator == "fake"
    assert "most distinct days" in llm.prompts[-1]


def test_llm_unsafe_sql_is_rejected():
    llm = FakeLLM([json.dumps({"ambiguities": []}), json.dumps({"sql": "DROP TABLE orders"})])
    resp = AskEngine(FakeExecutor(), AS_OF, llm).ask(AskRequest(question="How many orders were placed last month?"))
    assert resp.status == "rejected"


def test_structured_retries_once_then_validates():
    llm = FakeLLM(["not json", json.dumps({"sql": "SELECT 1"})])
    assert structured(llm, "sys", "q", LLMSql).sql == "SELECT 1"
    assert "previous reply was invalid" in llm.prompts[-1]


def test_structured_gives_up_after_two_bad_replies():
    with pytest.raises(LLMError):
        structured(FakeLLM(["{}", "{}"]), "sys", "q", LLMSql)


def test_groq_and_gemini_request_shapes():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if "groq" in request.url.host:
            seen["groq"] = (request.headers["authorization"], body["response_format"])
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"sql": "SELECT 1"}'}}]})
        seen["gemini"] = (request.headers["x-goog-api-key"], body["generationConfig"]["responseMimeType"])
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": '{"sql": "SELECT 2"}'}]}}]})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    assert GroqClient("k1", http=http).complete_json("s", "u") == '{"sql": "SELECT 1"}'
    assert GeminiClient("k2", http=http).complete_json("s", "u") == '{"sql": "SELECT 2"}'
    assert seen == {"groq": ("Bearer k1", {"type": "json_object"}), "gemini": ("k2", "application/json")}


def test_llm_http_error_becomes_error_status():
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429, text="rate limited")))
    resp = AskEngine(FakeExecutor(), AS_OF, GroqClient("k", http=http)).ask(
        AskRequest(question="How many orders were placed last month?"))
    assert resp.status == "error" and "429" in resp.detail


# --- API ---------------------------------------------------------------------------


@pytest.fixture
def client():
    app.dependency_overrides[get_engine] = lambda: AskEngine(FakeExecutor(), AS_OF)
    yield TestClient(app)
    app.dependency_overrides.pop(get_engine, None)


def test_api_clarify_then_answer(client):
    q = "Show me last month's best customer."
    first = client.post("/api/ask", json={"question": q}).json()
    assert first["status"] == "needs_clarification"
    term = first["clarifications"][0]
    second = client.post("/api/ask", json={
        "question": q, "clarifications": [{"term": term["term"], "option_id": term["options"][1]["id"]}],
    }).json()
    assert second["status"] == "answered"
    assert second["rows"] == [[1]]


def test_api_validates_input(client):
    assert client.post("/api/ask", json={"question": ""}).status_code == 422
    assert client.post("/api/ask", json={"question": "x" * 501}).status_code == 422


# --- integration (real Postgres) -----------------------------------------------------

DB_URL = os.getenv("ASK_TEST_DATABASE_URL")


@pytest.mark.skipif(not DB_URL, reason="set ASK_TEST_DATABASE_URL to run against Postgres")
def test_eval_end_to_end_on_postgres():
    from sqlalchemy import create_engine
    from sqlalchemy.exc import OperationalError

    from app.ask.executor import PostgresExecutor
    from scripts.eval_ask import results_match, run_engine
    from scripts.seed_ask_demo import seed

    seed(DB_URL)
    ex = PostgresExecutor(create_engine(DB_URL), "ask_demo", 1000, 10000)
    engine = AskEngine(ex, AS_OF)
    direct_ok = engine_ok = 0
    for case in CASES:
        gold = ex.run(case["gold_sql"])
        d = engine.ask(AskRequest(question=case["question"], mode="direct"))
        e, _, unexpected = run_engine(engine, case)
        direct_ok += results_match(gold, d.columns, d.rows, case.get("match_columns"))
        engine_ok += results_match(gold, e.columns, e.rows, case.get("match_columns"))
        assert not unexpected
    assert engine_ok == len(CASES)
    assert direct_ok < engine_ok

    slow = PostgresExecutor(create_engine(DB_URL), "ask_demo", 10, 50)
    with pytest.raises(OperationalError):
        slow.run("SELECT COUNT(*) FROM generate_series(1, 200000000)")
