"""Ask Your Data API: POST /api/ask."""

from fastapi import APIRouter, Depends

from app.ask.config import get_ask_settings
from app.ask.engine import AskEngine
from app.ask.executor import get_executor
from app.ask.llm import make_llm
from app.ask.schemas import AskRequest, AskResponse

router = APIRouter()


def get_engine() -> AskEngine:
    s = get_ask_settings()
    return AskEngine(get_executor(), s.as_of, make_llm(s))


@router.post("", response_model=AskResponse)
def ask(req: AskRequest, engine: AskEngine = Depends(get_engine)) -> AskResponse:
    """Answer a business question, asking for clarification first when it is ambiguous.

    Send the same question again with `clarifications` filled in to get the answer.
    """
    return engine.ask(req)
