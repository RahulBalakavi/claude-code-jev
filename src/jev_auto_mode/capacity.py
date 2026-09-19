from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CapacityProjection:
    baseline_latency_ms: float
    candidate_latency_ms: float
    tool_calls_per_day: int
    latency_reduction_percent: float
    minutes_saved_per_day: float
    extra_token_capacity_per_day: float
    extra_token_capacity_per_month: float
    old_total_minutes: float
    new_total_minutes: float
    end_to_end_duration_reduction_percent: float
    throughput_increase_percent: float


def project_capacity(
    *,
    baseline_latency_ms: float,
    candidate_latency_ms: float,
    tool_calls_per_day: int,
    productive_tokens_per_second: float,
    non_classifier_minutes_per_day: float,
    working_days_per_month: int = 22,
) -> CapacityProjection:
    if baseline_latency_ms <= 0:
        raise ValueError("baseline latency must be positive")
    if candidate_latency_ms < 0:
        raise ValueError("candidate latency cannot be negative")
    if tool_calls_per_day < 0:
        raise ValueError("tool calls per day cannot be negative")
    if productive_tokens_per_second < 0:
        raise ValueError("productive tokens per second cannot be negative")
    if non_classifier_minutes_per_day <= 0:
        raise ValueError("non-classifier minutes per day must be positive")
    if working_days_per_month <= 0:
        raise ValueError("working days per month must be positive")

    saved_seconds = (
        (baseline_latency_ms - candidate_latency_ms) * tool_calls_per_day / 1000
    )
    baseline_gate_minutes = baseline_latency_ms * tool_calls_per_day / 60_000
    candidate_gate_minutes = candidate_latency_ms * tool_calls_per_day / 60_000
    old_total = non_classifier_minutes_per_day + baseline_gate_minutes
    new_total = non_classifier_minutes_per_day + candidate_gate_minutes
    duration_reduction = (old_total - new_total) / old_total * 100
    throughput_increase = (old_total / new_total - 1) * 100
    return CapacityProjection(
        baseline_latency_ms=baseline_latency_ms,
        candidate_latency_ms=candidate_latency_ms,
        tool_calls_per_day=tool_calls_per_day,
        latency_reduction_percent=(
            (baseline_latency_ms - candidate_latency_ms) / baseline_latency_ms * 100
        ),
        minutes_saved_per_day=saved_seconds / 60,
        extra_token_capacity_per_day=saved_seconds * productive_tokens_per_second,
        extra_token_capacity_per_month=(
            saved_seconds * productive_tokens_per_second * working_days_per_month
        ),
        old_total_minutes=old_total,
        new_total_minutes=new_total,
        end_to_end_duration_reduction_percent=duration_reduction,
        throughput_increase_percent=throughput_increase,
    )
