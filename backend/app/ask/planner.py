"""Offline SQL generator: rule-based intent matching -> SQL templates.

Runs with no network and no API key (the team contract's "no paid APIs, runs
locally" rule). It covers the question shapes in the evaluation set and the
common business questions around customers, orders, products and payments.
Anything else returns Unsupported; configure an LLM provider for open-ended
questions.
"""

import re
from dataclasses import dataclass, field
from datetime import date

from app.ask.periods import Period, last_n_days, parse_period


class Unsupported(ValueError):
    pass


@dataclass
class Plan:
    sql: str
    assumptions: list[str] = field(default_factory=list)


VALID = "o.order_status <> 'canceled'"
LINE_VALUE = "oi.quantity * oi.unit_price - oi.discount"
_WINDOWS = {"last_7_days": 7, "last_30_days": 30, "last_90_days": 90,
            "active_30": 30, "active_90": 90, "active_365": 365}


def _where(*conds: str) -> str:
    conds = [c for c in conds if c]
    return f"WHERE {' AND '.join(conds)}" if conds else ""


def _between(col: str, p: Period | None) -> str:
    if p is None:
        return ""
    return f"{col} >= DATE '{p.start.isoformat()}' AND {col} < DATE '{p.end.isoformat()}'"


def _limit(q: str, plural: bool) -> int:
    if m := re.search(r"\btop\s+(\d+)\b|\b(\d+)\s+(?:best|top|biggest)\b", q):
        return int(m.group(1) or m.group(2))
    return 10 if plural else 1


def _has(q: str, pattern: str) -> bool:
    return re.search(pattern, q) is not None


def plan(question: str, as_of: date, interpretation: dict[str, str]) -> Plan:
    """Build SQL for the question. `interpretation` maps glossary term id -> option id."""
    q = question.lower()
    period = parse_period(q, as_of)
    for term in ("recent", "active_customers"):
        if term in interpretation and period is None:
            period = last_n_days(as_of, _WINDOWS[interpretation[term]])

    assumptions = [f"Period: {period.describe()}" if period else "Period: all time"]
    between = _between("o.order_date", period)

    def done(sql: str, *extra: str) -> Plan:
        return Plan(sql, assumptions + list(extra))

    # --- cancellations -------------------------------------------------------
    if _has(q, r"cancel"):
        canceled = "o.order_status = 'canceled'"
        return done(f"SELECT COUNT(*) AS canceled_orders FROM orders o {_where(canceled, between)}")

    excl = "Canceled orders are excluded."

    # --- payment methods -------------------------------------------------------
    if _has(q, r"payment (?:method|type)s?|paid (?:with|by)"):
        limit = " LIMIT 1" if _has(q, r"\bmost\b|\btop\b|\bbiggest\b|\bhighest\b") else ""
        return done(
            f"SELECT p.payment_type, SUM(p.payment_value) AS amount, COUNT(DISTINCT p.order_id) AS orders "
            f"FROM payments p JOIN orders o ON o.order_id = p.order_id {_where(VALID, between)} "
            f"GROUP BY p.payment_type ORDER BY amount DESC{limit}", excl)

    # --- customer ranking ---------------------------------------------------------
    about_customers = _has(q, r"\bcustomers?\b|\bbuyers?\b|\bshoppers?\b|\bclients?\b|\bwho\b")
    ranked = _has(q, r"\b(?:best|top|most|highest|biggest|number one|#1|leading)\b")
    if "best_customer" in interpretation or (about_customers and ranked and not _has(q, r"\bstates?\b|\bcit(?:y|ies)\b")):
        metric = interpretation.get("best_customer")
        if metric is None:
            if _has(q, r"most orders|number of orders|by orders|order count"):
                metric = "orders"
            elif _has(q, r"spen[dt]|revenue|money|sales|by value"):
                metric = "revenue"
            elif _has(q, r"came back|visits|most often|frequen"):
                metric = "frequency"
        if metric:
            expr, alias = {"revenue": ("SUM(o.order_value)", "revenue"),
                           "orders": ("COUNT(*)", "orders"),
                           "frequency": ("COUNT(DISTINCT CAST(o.order_date AS DATE))", "order_days")}[metric]
            n = _limit(q, plural=_has(q, r"\b(?:customers|buyers|shoppers|clients)\b"))
            return done(f"SELECT o.customer_id, {expr} AS {alias} FROM orders o {_where(VALID, between)} "
                        f"GROUP BY o.customer_id ORDER BY {alias} DESC, o.customer_id LIMIT {n}",
                        excl, "Ties are broken by customer_id.")

    # --- product / category ranking --------------------------------------------------
    is_category = _has(q, r"\bcategor(?:y|ies)\b")
    about_products = is_category or _has(q, r"\bproducts?\b|\bitems?\b|\bskus?\b")
    if about_products and (ranked or _has(q, r"\bsold\b|\bselling\b|\bby category\b|\bper category\b")):
        term = "best_category" if is_category else "best_product"
        metric = interpretation.get(term)
        if metric is None:
            metric = "units" if _has(q, r"\bunits?\b|\bquantity\b|sold the most|most sold") else "revenue"
        expr, alias = (f"SUM({LINE_VALUE})", "revenue") if metric == "revenue" else ("SUM(oi.quantity)", "units")
        key = "p.category" if is_category else "p.product_name"
        grouped = _has(q, r"\bby category\b|\bper category\b|\beach category\b")
        limit = "" if grouped else f" LIMIT {_limit(q, plural=_has(q, r'\b(?:products|items|categories)\b'))}"
        return done(f"SELECT {key}, {expr} AS {alias} FROM order_items oi "
                    f"JOIN orders o ON o.order_id = oi.order_id JOIN products p ON p.product_id = oi.product_id "
                    f"{_where(VALID, between)} GROUP BY {key} ORDER BY {alias} DESC, {key}{limit}", excl)

    # --- revenue by month -------------------------------------------------------------------
    if _has(q, r"monthly|by month|per month|each month|month by month"):
        return done(f"SELECT CAST(date_trunc('month', o.order_date) AS DATE) AS month, SUM(o.order_value) AS revenue "
                    f"FROM orders o {_where(VALID, between)} GROUP BY 1 ORDER BY 1", excl)

    # --- geography -----------------------------------------------------------------------
    if _has(q, r"\bstates?\b"):
        return done("SELECT c.customer_state, COUNT(*) AS customers FROM customers c "
                    "GROUP BY c.customer_state ORDER BY customers DESC, c.customer_state"
                    + (" LIMIT 1" if ranked else ""))

    # --- new customers ---------------------------------------------------------------------
    signed_up = _has(q, r"sign(?:ed)?[- ]?ups?|register|joined")
    if "new_customers" in interpretation or signed_up:
        if interpretation.get("new_customers", "signup") == "signup" and not _has(q, r"first (?:order|purchase)"):
            return done(f"SELECT COUNT(*) AS new_customers FROM customers c "
                        f"{_where(_between('c.created_at', period))}", "New customer = account created in the period.")
        return done(f"WITH firsts AS (SELECT o.customer_id, MIN(o.order_date) AS first_order FROM orders o "
                    f"WHERE {VALID} GROUP BY o.customer_id) "
                    f"SELECT COUNT(*) AS new_customers FROM firsts {_where(_between('first_order', period))}",
                    "New customer = first non-canceled order in the period.")

    # --- big orders -------------------------------------------------------------------------
    if "large_order" in interpretation:
        if interpretation["large_order"] == "top_10pct":
            return done(f"WITH t AS (SELECT percentile_cont(0.9) WITHIN GROUP (ORDER BY o.order_value) AS p90 "
                        f"FROM orders o WHERE {VALID}) SELECT COUNT(*) AS big_orders FROM orders o, t "
                        f"{_where(VALID, between, 'o.order_value >= t.p90')}", excl)
        return done(f"SELECT COUNT(*) AS big_orders FROM orders o {_where(VALID, between, 'o.order_value > 1000')}",
                    excl)

    # --- customers who ordered / active customers ------------------------------------------------
    if about_customers and ("active_customers" in interpretation
                            or _has(q, r"\b(?:placed|ordered|bought|purchased|made|active)\b")):
        return done(f"SELECT COUNT(DISTINCT o.customer_id) AS customers FROM orders o {_where(VALID, between)}", excl)

    # --- headline metrics --------------------------------------------------------------------------
    if _has(q, r"average order value|\baov\b|average order|avg order"):
        return done(f"SELECT ROUND(AVG(o.order_value), 2) AS average_order_value FROM orders o "
                    f"{_where(VALID, between)}", excl)
    if _has(q, r"revenue|sales|earn|income|turnover|how much money"):
        return done(f"SELECT SUM(o.order_value) AS revenue FROM orders o {_where(VALID, between)}", excl)
    if _has(q, r"\borders?\b"):
        return done(f"SELECT COUNT(*) AS orders FROM orders o {_where(VALID, between)}", excl)
    if about_customers and _has(q, r"how many|number of|count|total"):
        return done("SELECT COUNT(*) AS customers FROM customers c")

    raise Unsupported(
        "The offline engine can't answer this question shape yet. "
        "Set ASK_LLM_PROVIDER=groq or gemini for open-ended questions."
    )
