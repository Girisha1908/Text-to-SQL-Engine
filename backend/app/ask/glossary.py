"""Business glossary: which phrases are ambiguous, and which have a governed default.

This is the semantic layer of Ask Your Data. Ambiguous terms are asked about;
governed defaults are applied and reported as assumptions. Adding a term here is
a business decision — keep definitions short and in plain language.
"""

import re
from dataclasses import dataclass

from app.ask.schemas import Clarification, ClarificationOption


@dataclass(frozen=True)
class Term:
    id: str
    prompt: str
    trigger: re.Pattern
    options: tuple[ClarificationOption, ...]
    default: str  # option used when clarification is off (mode=direct)
    skip: re.Pattern | None = None  # question already disambiguates the term
    only_without_period: bool = False  # an explicit time period resolves the term

    def option(self, option_id: str) -> ClarificationOption | None:
        return next((o for o in self.options if o.id == option_id), None)

    def to_clarification(self) -> Clarification:
        return Clarification(term=self.id, prompt=self.prompt, options=list(self.options), source="glossary")


def _re(p: str) -> re.Pattern:
    return re.compile(p, re.IGNORECASE)


def _opt(id: str, label: str, definition: str) -> ClarificationOption:
    return ClarificationOption(id=id, label=label, definition=definition)


_RANKED = r"(?:best|top|biggest|most valuable|number one|no\.? ?1|#1|star|leading)"
_SELLING = r"(?:best|top|best[- ]selling|top[- ]selling|most popular|number one|#1|leading|strongest)"
_PRODUCT_METRIC = r"\bby\s+(?:revenue|sales|units|quantity|volume)\b|\bunits\b|\bquantity\b|\bmost money\b"

TERMS: tuple[Term, ...] = (
    Term(
        id="best_customer",
        prompt="What does 'best customer' mean here?",
        trigger=_re(rf"\b{_RANKED}\s+(?:\d+\s+)?(?:customer|buyer|shopper|client)s?\b"),
        skip=_re(r"\bby\s+(?:total\s+)?(?:revenue|spend|spending|sales|value|amount|orders|number of orders|"
                 r"order count|visits|frequency)\b|\bspent\b|\bmost orders\b|\bmost money\b|\bhighest spend"),
        options=(
            _opt("revenue", "Highest spend", "Customer with the highest total value of non-canceled orders"),
            _opt("orders", "Most orders", "Customer who placed the most non-canceled orders"),
            _opt("frequency", "Came back most often",
                 "Customer with the most distinct days on which they placed a non-canceled order"),
        ),
        default="revenue",
    ),
    Term(
        id="best_product",
        prompt="What does 'best product' mean here?",
        trigger=_re(rf"\b{_SELLING}\s+(?:\d+\s+)?(?:products?|items?|skus?)\b"),
        skip=_re(_PRODUCT_METRIC),
        options=(
            _opt("revenue", "Most revenue", "Product with the highest sales value (quantity x price - discount)"),
            _opt("units", "Most units sold", "Product with the most units sold"),
        ),
        default="units",
    ),
    Term(
        id="best_category",
        prompt="What does 'best category' mean here?",
        trigger=_re(rf"\b{_SELLING}\s+(?:\d+\s+)?categor(?:y|ies)\b|"
                    r"\bcategor(?:y|ies)\s+(?:performed|did|was|were|is|are|sold)\s+(?:the\s+)?(?:best|most)\b"),
        skip=_re(_PRODUCT_METRIC),
        options=(
            _opt("revenue", "Most revenue", "Category with the highest sales value"),
            _opt("units", "Most units sold", "Category with the most units sold"),
        ),
        default="revenue",
    ),
    Term(
        id="new_customers",
        prompt="How should we count 'new customers'?",
        trigger=_re(r"\bnew\s+(?:customers?|buyers?|users?|shoppers?|clients?)\b"),
        skip=_re(r"\bsign(?:ed)?[- ]?ups?\b|\bregister(?:ed)?\b|\bjoined\b|\bfirst (?:order|purchase)\b"),
        options=(
            _opt("signup", "Signed up", "Customers whose account was created in the period"),
            _opt("first_order", "First purchase", "Customers whose first-ever non-canceled order was in the period"),
        ),
        default="first_order",
    ),
    Term(
        id="recent",
        prompt="How far back does 'recent' go?",
        trigger=_re(r"\brecent(?:ly)?\b|\blately\b"),
        only_without_period=True,
        options=(
            _opt("last_7_days", "Last 7 days", "The 7 full days before today"),
            _opt("last_30_days", "Last 30 days", "The 30 full days before today"),
            _opt("last_90_days", "Last 90 days", "The 90 full days before today"),
        ),
        default="last_30_days",
    ),
    Term(
        id="large_order",
        prompt="What counts as a 'big order'?",
        trigger=_re(r"\b(?:big|large|huge|high[- ]value)\s+orders?\b"),
        skip=_re(r"\b(?:over|above|more than|greater than|at least)\s*(?:r\$|\$|₹|rs\.?)?\s*\d"),
        options=(
            _opt("over_1000", "Over 1,000", "Orders with a value above 1,000"),
            _opt("top_10pct", "Top 10% by value",
                 "Orders at or above the 90th percentile of all non-canceled order values (all time)"),
        ),
        default="over_1000",
    ),
    Term(
        id="active_customers",
        prompt="What counts as an 'active customer'?",
        trigger=_re(r"\bactive\s+(?:customers?|users?|buyers?|shoppers?)\b"),
        only_without_period=True,
        options=(
            _opt("active_30", "Ordered in last 30 days", "Placed a non-canceled order in the 30 days before today"),
            _opt("active_90", "Ordered in last 90 days", "Placed a non-canceled order in the 90 days before today"),
            _opt("active_365", "Ordered in last 365 days",
                 "Placed a non-canceled order in the 365 days before today"),
        ),
        default="active_30",
    ),
)

TERMS_BY_ID = {t.id: t for t in TERMS}

GOVERNED_DEFAULTS: tuple[str, ...] = (
    "Revenue = sum of order_value for non-canceled orders.",
    "Canceled orders (order_status = 'canceled') are excluded from every metric unless the question "
    "is about cancellations.",
    "'Last month' = previous calendar month; 'this month/year' = start of the period up to and including today.",
    "'Last N days' = the N full days before today (today excluded).",
    "No period mentioned = all time.",
)


def detect(question: str, has_period: bool) -> list[Term]:
    """Ambiguous glossary terms present in the question and not already resolved by it."""
    found = []
    for term in TERMS:
        if not term.trigger.search(question):
            continue
        if term.skip and term.skip.search(question):
            continue
        if term.only_without_period and has_period:
            continue
        found.append(term)
    return found
