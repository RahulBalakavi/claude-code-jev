from __future__ import annotations

import json
import logging
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from jev_auto_mode.models import BenchmarkCase, Decision, ToolAction, Verdict
from jev_auto_mode.providers import Classifier

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BenchmarkSummary:
    provider: str
    model: str | None
    case_count: int
    correct_count: int
    accuracy_percent: float
    ask_rate_percent: float
    p50_latency_ms: float
    p95_latency_ms: float
    mean_latency_ms: float
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float


def load_cases(path: Path) -> list[BenchmarkCase]:
    cases: list[BenchmarkCase] = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                logger.debug("Skipping blank fixture line %s", line_number)
                continue
            raw = json.loads(line)
            cases.append(_parse_case(raw, line_number=line_number))
    if not cases:
        raise ValueError(f"no benchmark cases found in {path}")
    return cases


def run_benchmark(
    *, classifier: Classifier, provider_name: str, cases: list[BenchmarkCase]
) -> tuple[BenchmarkSummary, list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    verdicts: list[Verdict] = []
    for case in cases:
        verdict = classifier.classify(case.action)
        verdicts.append(verdict)
        results.append(
            {
                "case_id": case.case_id,
                "expected": case.expected.value,
                "actual": verdict.decision.value,
                "correct": verdict.decision is case.expected,
                "note": case.note,
                **asdict(verdict),
                "decision": verdict.decision.value,
            }
        )
    latencies = sorted(item.latency_ms for item in verdicts)
    correct_count = sum(
        verdict.decision is case.expected
        for verdict, case in zip(verdicts, cases, strict=True)
    )
    summary = BenchmarkSummary(
        provider=provider_name,
        model=verdicts[0].model,
        case_count=len(cases),
        correct_count=correct_count,
        accuracy_percent=correct_count / len(cases) * 100,
        ask_rate_percent=(
            sum(item.decision is Decision.ASK for item in verdicts)
            / len(verdicts)
            * 100
        ),
        p50_latency_ms=statistics.median(latencies),
        p95_latency_ms=_percentile(latencies, 0.95),
        mean_latency_ms=statistics.fmean(latencies),
        total_input_tokens=sum(item.input_tokens or 0 for item in verdicts),
        total_output_tokens=sum(item.output_tokens or 0 for item in verdicts),
        total_cost_usd=sum(item.cost_usd or 0 for item in verdicts),
    )
    return summary, results


def write_results(
    *, path: Path, summary: BenchmarkSummary, results: list[dict[str, Any]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"summary": asdict(summary), "results": results}
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n")


def _parse_case(raw: Any, *, line_number: int) -> BenchmarkCase:
    if not isinstance(raw, dict):
        raise ValueError(f"fixture line {line_number} must be a JSON object")
    try:
        user_messages = tuple(str(item) for item in raw["user_messages"])
        tool_input = raw["tool_input"]
        if not isinstance(tool_input, dict):
            raise TypeError("tool_input must be an object")
        action = ToolAction(
            user_messages=user_messages,
            tool_name=str(raw["tool_name"]),
            tool_input=tool_input,
            cwd=str(raw.get("cwd", "/workspace/project")),
        )
        return BenchmarkCase(
            case_id=str(raw["id"]),
            action=action,
            expected=Decision(raw["expected"]),
            note=str(raw.get("note", "")),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"invalid fixture line {line_number}: {error}") from error


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    index = max(0, min(len(values) - 1, round(percentile * len(values) + 0.5) - 1))
    return values[index]
