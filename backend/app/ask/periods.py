"""Turn time phrases ("last month", "in August 2026", "last 7 days") into [start, end) dates.

Governed defaults (see docs/PRD.md §7):
  last month   -> previous calendar month
  this month   -> first of month .. today (inclusive)
  last N days  -> the N full days before today
"""

import re
from dataclasses import dataclass
from datetime import date, timedelta

MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]


@dataclass(frozen=True)
class Period:
    start: date
    end: date  # exclusive
    label: str

    def describe(self) -> str:
        return f"{self.label} ({self.start.isoformat()} to {(self.end - timedelta(days=1)).isoformat()})"


def _add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def last_n_days(as_of: date, n: int) -> Period:
    return Period(as_of - timedelta(days=n), as_of, f"last {n} days")


def parse_period(question: str, as_of: date) -> Period | None:
    """Return the period mentioned in the question, or None if there is none."""
    q = question.lower()
    tomorrow = as_of + timedelta(days=1)
    month_start = as_of.replace(day=1)
    quarter_start = date(as_of.year, 3 * ((as_of.month - 1) // 3) + 1, 1)

    if m := re.search(r"\b(?:last|past|previous)\s+(\d+)\s+days?\b", q):
        return last_n_days(as_of, int(m.group(1)))
    if m := re.search(r"\b(?:last|past|previous)\s+(\d+)\s+weeks?\b", q):
        return Period(as_of - timedelta(weeks=int(m.group(1))), as_of, f"last {m.group(1)} weeks")
    if m := re.search(r"\b(?:last|past|previous)\s+(\d+)\s+months?\b", q):
        n = int(m.group(1))
        return Period(_add_months(month_start, -n), month_start, f"previous {n} calendar months")
    if re.search(r"\byesterday\b", q):
        return Period(as_of - timedelta(days=1), as_of, "yesterday")
    if re.search(r"\btoday\b", q):
        return Period(as_of, tomorrow, "today")
    if re.search(r"\b(?:last|previous)\s+week'?s?\b", q):
        monday = as_of - timedelta(days=as_of.weekday())
        return Period(monday - timedelta(days=7), monday, "previous week (Mon-Sun)")
    if re.search(r"\bthis\s+week\b", q):
        return Period(as_of - timedelta(days=as_of.weekday()), tomorrow, "this week to date")
    if re.search(r"\b(?:last|previous)\s+month'?s?\b", q):
        return Period(_add_months(month_start, -1), month_start, "previous calendar month")
    if re.search(r"\bthis\s+month\b|\bmonth to date\b|\bmtd\b", q):
        return Period(month_start, tomorrow, "this month to date")
    if re.search(r"\b(?:last|previous)\s+quarter'?s?\b", q):
        return Period(_add_months(quarter_start, -3), quarter_start, "previous calendar quarter")
    if re.search(r"\bthis\s+quarter\b", q):
        return Period(quarter_start, tomorrow, "this quarter to date")
    if re.search(r"\b(?:last|previous)\s+year'?s?\b", q):
        return Period(date(as_of.year - 1, 1, 1), date(as_of.year, 1, 1), "previous calendar year")
    if re.search(r"\bthis\s+year\b|\byear to date\b|\bytd\b", q):
        return Period(date(as_of.year, 1, 1), tomorrow, "this year to date")
    if m := re.search(rf"\b({'|'.join(MONTHS)})\s+(20\d\d)\b", q):
        start = date(int(m.group(2)), MONTHS.index(m.group(1)) + 1, 1)
        return Period(start, _add_months(start, 1), f"{m.group(1).title()} {m.group(2)}")
    if m := re.search(r"\b(20\d\d)\b", q):
        y = int(m.group(1))
        return Period(date(y, 1, 1), date(y + 1, 1, 1), f"year {y}")
    return None
