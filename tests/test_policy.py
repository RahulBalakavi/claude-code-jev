import pytest

from jev_auto_mode.models import Decision
from jev_auto_mode.policy import apply_confidence_gate, validate_threshold


@pytest.mark.parametrize(
    ("decision", "confidence", "expected"),
    [
        (Decision.ALLOW, 0.95, Decision.ALLOW),
        (Decision.BLOCK, 0.92, Decision.BLOCK),
        (Decision.ALLOW, 0.60, Decision.ASK),
        (Decision.BLOCK, 0.84, Decision.ASK),
        (Decision.ASK, 0.99, Decision.ASK),
    ],
)
def test_confidence_gate_escalates_uncertain_decisions(
    decision: Decision, confidence: float, expected: Decision
) -> None:
    assert (
        apply_confidence_gate(
            decision=decision,
            confidence=confidence,
            threshold=0.85,
        )
        is expected
    )


def test_threshold_rejects_unsafe_range() -> None:
    with pytest.raises(ValueError, match="between 0.5 and 1.0"):
        validate_threshold(0.2)
