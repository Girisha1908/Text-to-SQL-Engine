"""Optional LLM providers (free tiers) with Pydantic-validated JSON output.

Both use plain httpx (already a project dependency) instead of vendor SDKs.
Model names change often; override with ASK_LLM_MODEL.
"""

import json
from datetime import date
from typing import Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.ask.config import AskSettings
from app.ask.glossary import GOVERNED_DEFAULTS

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


def _pick(r: httpx.Response, path) -> str:
    try:
        return path(r.json())
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise LLMError(f"Unexpected LLM response shape: {r.text[:300]}") from e


class LLMClient(Protocol):
    name: str

    def complete_json(self, system: str, user: str) -> str: ...


class GroqClient:
    name = "groq"
    URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, api_key: str, model: str | None = None, http: httpx.Client | None = None):
        self.api_key, self.model = api_key, model or "llama-3.3-70b-versatile"
        self.http = http or httpx.Client(timeout=60)

    def complete_json(self, system: str, user: str) -> str:
        r = self.http.post(self.URL, headers={"Authorization": f"Bearer {self.api_key}"}, json={
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        })
        if r.status_code != 200:
            raise LLMError(f"Groq returned {r.status_code}: {r.text[:300]}")
        return _pick(r, lambda b: b["choices"][0]["message"]["content"])


class GeminiClient:
    name = "gemini"

    def __init__(self, api_key: str, model: str | None = None, http: httpx.Client | None = None):
        self.api_key, self.model = api_key, model or "gemini-2.5-flash"
        self.http = http or httpx.Client(timeout=60)

    def complete_json(self, system: str, user: str) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        r = self.http.post(url, headers={"x-goog-api-key": self.api_key}, json={
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        })
        if r.status_code != 200:
            raise LLMError(f"Gemini returned {r.status_code}: {r.text[:300]}")
        return _pick(r, lambda b: b["candidates"][0]["content"]["parts"][0]["text"])


def make_llm(s: AskSettings) -> LLMClient | None:
    if s.ASK_LLM_PROVIDER == "groq":
        if not s.GROQ_API_KEY:
            raise LLMError("ASK_LLM_PROVIDER=groq but GROQ_API_KEY is not set.")
        return GroqClient(s.GROQ_API_KEY, s.ASK_LLM_MODEL)
    if s.ASK_LLM_PROVIDER == "gemini":
        if not s.GEMINI_API_KEY:
            raise LLMError("ASK_LLM_PROVIDER=gemini but GEMINI_API_KEY is not set.")
        return GeminiClient(s.GEMINI_API_KEY, s.ASK_LLM_MODEL)
    return None


def structured(client: LLMClient, system: str, user: str, model: type[T]) -> T:
    """Call the LLM and validate its JSON against `model`, with one repair attempt."""
    schema = json.dumps(model.model_json_schema())
    prompt = f"{user}\n\nReply with a single JSON object matching this JSON Schema:\n{schema}"
    raw = client.complete_json(system, prompt)
    try:
        return model.model_validate_json(raw)
    except ValidationError as e:
        retry = f"{prompt}\n\nYour previous reply was invalid:\n{raw[:1000]}\nErrors: {e}\nReturn corrected JSON only."
        try:
            return model.model_validate_json(client.complete_json(system, retry))
        except ValidationError as e2:
            raise LLMError(f"LLM output failed validation twice: {e2}") from e2


SCHEMA_DOC = """\
PostgreSQL tables (search_path is already set; use unqualified names):

customers(customer_id varchar PK, customer_unique_id varchar, customer_city varchar, customer_state varchar,
          customer_country varchar, created_at timestamptz  -- sign-up date)
orders(order_id varchar PK, customer_id varchar FK customers, order_date timestamptz,
       order_status varchar  -- 'delivered' | 'shipped' | 'processing' | 'canceled',
       order_value numeric  -- total of the order)
order_items(order_id varchar FK orders, product_id varchar FK products, customer_id varchar, quantity int,
            unit_price numeric, discount numeric  -- absolute amount off the line;
            line value = quantity * unit_price - discount)
products(product_id varchar PK, product_name varchar, category varchar, brand varchar, price numeric,
         cost numeric, created_at timestamptz)
payments(order_id varchar FK orders, payment_sequential int, payment_type varchar
         -- 'credit_card' | 'debit_card' | 'boleto' | 'voucher', payment_installments int, payment_value numeric)
"""


def system_prompt(as_of: date) -> str:
    rules = "\n".join(f"- {r}" for r in GOVERNED_DEFAULTS)
    return (
        "You are a careful analytics engineer who turns business questions into PostgreSQL.\n\n"
        f"{SCHEMA_DOC}\n"
        f"Today is {as_of.isoformat()}. Always write dates as literals, e.g. DATE '{as_of.isoformat()}'; "
        "never use CURRENT_DATE, NOW() or CURRENT_TIMESTAMP.\n\n"
        f"Company metric definitions (always apply):\n{rules}\n\n"
        "Write exactly one read-only SELECT (or WITH ... SELECT). No comments, no semicolons. "
        "Return identifiers plus the metric the question is about. Break ties deterministically."
    )


def analyze_prompt(question: str, already: list[str]) -> str:
    return (
        f"Question: {question}\n\n"
        f"Ambiguities already detected (do not repeat): {', '.join(already) or 'none'}.\n\n"
        "List any OTHER ambiguity in this question: a phrase with two or more plausible business meanings "
        "that would produce materially different query results, and that the company metric definitions "
        "above do not already settle. Be conservative: most questions are clear, and asking unnecessary "
        "questions annoys users. For each ambiguity give a snake_case term, a short question to the user, "
        "and 2-4 options with id, label and a precise definition. "
        'Return {"ambiguities": []} when the question is clear.'
    )


def generate_prompt(question: str, interpretation: dict[str, str] | None) -> str:
    if interpretation is None:
        guidance = "If any part of the question is ambiguous, choose the most reasonable interpretation."
    elif interpretation:
        chosen = "\n".join(f"- {term}: {definition}" for term, definition in interpretation.items())
        guidance = f"The user clarified what they mean. Follow these definitions exactly:\n{chosen}"
    else:
        guidance = "The question has been checked and is unambiguous."
    return (
        f"Question: {question}\n\n{guidance}\n\n"
        'Return {"sql": "...", "explanation": "one sentence", "assumptions": ["..."]}.'
    )
