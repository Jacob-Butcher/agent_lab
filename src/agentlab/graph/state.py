from typing import TypedDict


class AgentState(TypedDict, total=False):
    query: str
    session_id: str
    history: list[dict]
    retrieved: list[dict]
    citations: list[dict]
    context: str
    answer: str
    error: str | None
