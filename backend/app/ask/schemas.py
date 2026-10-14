"""Pydantic models for the Ask API and for LLM structured outputs."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Status = Literal["needs_clarification", "answered", "unsupported", "rejected", "error"]


class ClarificationOption(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=120)
    definition: str = Field(min_length=1, max_length=400)


class Clarification(BaseModel):
    term: str = Field(min_length=1, max_length=64)
    prompt: str = Field(min_length=1, max_length=300)
    options: list[ClarificationOption] = Field(min_length=2, max_length=6)
    source: Literal["glossary", "llm"] = "llm"


class ResolvedTerm(BaseModel):
    term: str = Field(min_length=1, max_length=64)
    option_id: str = Field(min_length=1, max_length=64)
    definition: Optional[str] = Field(default=None, max_length=400)  # needed for LLM-proposed terms


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    mode: Literal["engine", "direct"] = "engine"
    clarifications: list[ResolvedTerm] = Field(default_factory=list, max_length=10)


class AskResponse(BaseModel):
    status: Status
    question: str
    clarifications: list[Clarification] = Field(default_factory=list)
    sql: Optional[str] = None
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    assumptions: list[str] = Field(default_factory=list)
    interpretation: dict[str, str] = Field(default_factory=dict)
    generator: Optional[str] = None
    detail: Optional[str] = None


# --- LLM structured outputs -------------------------------------------------


class LLMAmbiguities(BaseModel):
    ambiguities: list[Clarification] = Field(default_factory=list)


class LLMSql(BaseModel):
    sql: str = Field(min_length=1)
    explanation: str = ""
    assumptions: list[str] = Field(default_factory=list)
