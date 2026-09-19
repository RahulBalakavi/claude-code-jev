from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Decision(StrEnum):
    """Permission outcomes supported by Claude Code's PreToolUse hook."""

    ALLOW = "allow"
    BLOCK = "block"
    ASK = "ask"


@dataclass(frozen=True)
class ToolAction:
    """The reasoning-minimized state sent to a permission classifier."""

    user_messages: tuple[str, ...]
    tool_name: str
    tool_input: dict[str, Any]
    cwd: str


@dataclass(frozen=True)
class Verdict:
    """A classifier decision plus the telemetry needed for evaluation."""

    decision: Decision
    confidence: float
    reason: str
    latency_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    model: str | None = None


@dataclass(frozen=True)
class BenchmarkCase:
    """A labeled permission decision used by the benchmark harness."""

    case_id: str
    action: ToolAction
    expected: Decision
    note: str
