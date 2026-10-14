"""Ask Your Data orchestration: detect -> clarify -> generate -> guard -> execute."""

from datetime import date

from sqlalchemy.exc import SQLAlchemyError

from app.ask import glossary, planner
from app.ask.executor import Executor
from app.ask.llm import (
    LLMClient, LLMError, analyze_prompt, generate_prompt, structured, system_prompt,
)
from app.ask.periods import parse_period
from app.ask.schemas import AskRequest, AskResponse, LLMAmbiguities, LLMSql
from app.ask.sql_guard import UnsafeSQL


class AskEngine:
    def __init__(self, executor: Executor, as_of: date, llm: LLMClient | None = None):
        self.executor, self.as_of, self.llm = executor, as_of, llm

    @property
    def generator(self) -> str:
        return self.llm.name if self.llm else "offline"

    def ask(self, req: AskRequest) -> AskResponse:
        base = {"question": req.question, "generator": self.generator}
        try:
            return self._ask(req, base)
        except UnsafeSQL as e:
            return AskResponse(status="rejected", detail=str(e), **base)
        except planner.Unsupported as e:
            return AskResponse(status="unsupported", detail=str(e), **base)
        except (LLMError, SQLAlchemyError) as e:
            return AskResponse(status="error", detail=str(e).splitlines()[0][:300], **base)

    def _ask(self, req: AskRequest, base: dict) -> AskResponse:
        q = req.question
        detected = glossary.detect(q, has_period=parse_period(q, self.as_of) is not None)
        chosen = {c.term: c for c in req.clarifications}

        # interpretation: term id -> option id (planner) and term id -> definition (LLM prompt)
        option_ids: dict[str, str] = {}
        definitions: dict[str, str] = {}
        assumptions: list[str] = []

        if req.mode == "engine":
            pending = [t.to_clarification() for t in detected if t.id not in chosen]
            if self.llm and not req.clarifications:
                already = [t.id for t in detected]
                extra = structured(self.llm, system_prompt(self.as_of), analyze_prompt(q, already), LLMAmbiguities)
                pending += [c.model_copy(update={"source": "llm"}) for c in extra.ambiguities if c.term not in already]
            if pending:
                return AskResponse(status="needs_clarification", clarifications=pending, **base)

            for c in req.clarifications:
                term = glossary.TERMS_BY_ID.get(c.term)
                if term:
                    opt = term.option(c.option_id)
                    if opt is None:
                        return AskResponse(status="rejected", detail=f"Unknown option {c.option_id!r} for {c.term}.",
                                           **base)
                    option_ids[c.term], definitions[c.term] = opt.id, opt.definition
                    assumptions.append(f"{c.term}: {opt.label} — {opt.definition} (your choice)")
                elif c.definition:
                    option_ids[c.term], definitions[c.term] = c.option_id, c.definition
                    assumptions.append(f"{c.term}: {c.definition} (your choice)")
        elif not self.llm:
            # Direct mode, offline: silently apply each ambiguous term's default.
            for t in detected:
                opt = t.option(t.default)
                option_ids[t.id] = opt.id
                assumptions.append(f"{t.id}: {opt.label} — {opt.definition} (assumed)")

        if self.llm:
            interp = definitions if req.mode == "engine" else None
            out = structured(self.llm, system_prompt(self.as_of), generate_prompt(q, interp), LLMSql)
            sql, assumptions = out.sql, assumptions + out.assumptions
        else:
            p = planner.plan(q, self.as_of, option_ids)
            sql, assumptions = p.sql, assumptions + p.assumptions

        result = self.executor.run(sql)
        return AskResponse(
            status="answered", sql=sql, columns=result.columns, rows=result.rows, row_count=len(result.rows),
            truncated=result.truncated, assumptions=assumptions, interpretation=option_ids, **base,
        )
