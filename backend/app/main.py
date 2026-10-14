"""Ask Your Data API entrypoint."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import ask

app = FastAPI(
    title="Ask Your Data",
    description="Text-to-SQL that asks before it guesses.",
    version="1.0.0",
)

# The deployed frontend is same-origin; this only matters for local dev on another port.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])

app.include_router(ask.router, prefix="/api/ask", tags=["ask"])


@app.get("/api/health", tags=["system"])
def health() -> dict:
    """Liveness probe for uptime monitors. Does not touch the database."""
    return {"status": "ok"}
