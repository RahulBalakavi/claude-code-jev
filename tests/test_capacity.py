import pytest

from jev_auto_mode.capacity import project_capacity


def test_capacity_projection_separates_gate_speed_from_agent_speed() -> None:
    projection = project_capacity(
        baseline_latency_ms=4000,
        candidate_latency_ms=660,
        tool_calls_per_day=500,
        productive_tokens_per_second=25,
        non_classifier_minutes_per_day=480,
    )

    assert projection.latency_reduction_percent == pytest.approx(83.5)
    assert projection.minutes_saved_per_day == pytest.approx(27.8333, rel=1e-4)
    assert projection.extra_token_capacity_per_day == pytest.approx(41_750)
    assert projection.extra_token_capacity_per_month == pytest.approx(918_500)
    assert projection.end_to_end_duration_reduction_percent == pytest.approx(
        5.425, rel=1e-3
    )
    assert projection.throughput_increase_percent == pytest.approx(5.736, rel=1e-3)
