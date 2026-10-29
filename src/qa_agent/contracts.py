from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Action:
    name: str
    arguments: dict[str, Any]
    reason: str  # Short decision summary, not a chain-of-thought transcript.


@dataclass
class State:
    question: str
    history: list[dict[str, str]]
    observations: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, dict[str, Any]] = field(default_factory=dict)


class DecisionBackend(Protocol):
    """A real model adapter can implement this boundary without changing tools."""

    name: str
    is_mock: bool

    def decide(self, state: State) -> Action:
        ...


STATUSES = {
    "answered", "needs_clarification", "insufficient_evidence",
    "tool_failed", "incomplete",
}


def validate_action(action: Action) -> None:
    if not isinstance(action, Action):
        raise ValueError("Decision must be an Action object")
    if action.name not in {"search_documents", "read_document", "finish"}:
        raise ValueError("Unsupported action")
    if not isinstance(action.arguments, dict):
        raise ValueError("Action arguments must be an object")
    if not isinstance(action.reason, str) or not 1 <= len(action.reason) <= 300:
        raise ValueError("A decision summary of 1–300 characters is required")
