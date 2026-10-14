"""Reject anything that is not a single read-only query.

This is a fast first filter with clear error messages. The real control is the
executor's READ ONLY transaction; this guard only keeps obviously bad SQL from
reaching the database at all.
"""

import re


class UnsafeSQL(ValueError):
    pass


_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|copy|call|do|"
    r"execute|prepare|vacuum|reindex|cluster|lock|listen|notify|set|reset|refresh|comment|"
    r"security|pg_sleep|pg_read_file|pg_read_binary_file|pg_ls_dir|lo_import|lo_export|"
    r"dblink|set_config|pg_terminate_backend|pg_cancel_backend)\b",
    re.IGNORECASE,
)
_STRINGS = re.compile(r"'(?:[^']|'')*'")


def check_sql(sql: str) -> str:
    """Return the cleaned statement, or raise UnsafeSQL."""
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        raise UnsafeSQL("Empty query.")
    # Inspect the query with string literals blanked, so 'canceled' or 'delete me' in a
    # WHERE clause doesn't trip the checks below.
    code = _STRINGS.sub("''", cleaned)
    if "--" in code or "/*" in code:
        raise UnsafeSQL("SQL comments are not allowed.")
    if ";" in code:
        raise UnsafeSQL("Only one statement is allowed.")
    if not re.match(r"^(select|with)\b", code, re.IGNORECASE):
        raise UnsafeSQL("Only SELECT queries are allowed.")
    if m := _FORBIDDEN.search(code):
        raise UnsafeSQL(f"Keyword not allowed in a read-only query: {m.group(0).upper()}")
    return cleaned
