"""Run a guarded query read-only, time-limited and row-capped."""

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any, Protocol

from sqlalchemy import Engine, create_engine

from app.ask.config import get_ask_settings
from app.ask.sql_guard import check_sql


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool


class Executor(Protocol):
    def run(self, sql: str) -> QueryResult: ...


def _jsonable(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


class PostgresExecutor:
    def __init__(self, engine: Engine, schema: str, max_rows: int, timeout_ms: int):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
            raise ValueError(f"Invalid schema name: {schema!r}")
        self.engine, self.schema, self.max_rows, self.timeout_ms = engine, schema, max_rows, int(timeout_ms)

    def run(self, sql: str) -> QueryResult:
        sql = check_sql(sql)
        with self.engine.connect() as conn:
            try:
                conn.exec_driver_sql("SET TRANSACTION READ ONLY")
                conn.exec_driver_sql(f"SET LOCAL statement_timeout = {self.timeout_ms}")
                conn.exec_driver_sql(f"SET LOCAL search_path TO {self.schema}")
                conn.exec_driver_sql("SET LOCAL TIME ZONE 'UTC'")
                # exec_driver_sql: no bind-param parsing, so ':' and '%' in SQL stay literal.
                result = conn.exec_driver_sql(sql)
                rows = result.fetchmany(self.max_rows + 1)
                columns = list(result.keys())
            finally:
                conn.rollback()
        return QueryResult(
            columns=columns,
            rows=[[_jsonable(v) for v in r] for r in rows[: self.max_rows]],
            truncated=len(rows) > self.max_rows,
        )


@lru_cache
def get_executor() -> Executor:
    s = get_ask_settings()
    engine = create_engine(s.database_url, pool_pre_ping=True)
    return PostgresExecutor(engine, s.ASK_DB_SCHEMA, s.ASK_MAX_ROWS, s.ASK_STATEMENT_TIMEOUT_MS)
