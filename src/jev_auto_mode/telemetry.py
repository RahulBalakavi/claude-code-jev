from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from jev_auto_mode.models import Verdict

logger = logging.getLogger(__name__)


def append_decision(
    *, path: Path, tool_name: str, action_hash: str, verdict: Verdict
) -> None:
    """Append privacy-minimized decision telemetry for later benchmarking."""
    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "tool_name": tool_name,
        "action_hash": action_hash,
        **asdict(verdict),
        "decision": verdict.decision.value,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(record, separators=(",", ":")) + "\n")
    except OSError:
        # Safe to swallow: metrics are best-effort and must never break permission flow.
        logger.warning("Could not append decision telemetry to %s", path, exc_info=True)
