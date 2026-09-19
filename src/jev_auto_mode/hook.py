from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, TextIO

from jev_auto_mode.models import Decision, ToolAction, Verdict
from jev_auto_mode.policy import validate_threshold
from jev_auto_mode.providers import OpenRouterJevClassifier, ProviderError
from jev_auto_mode.telemetry import append_decision
from jev_auto_mode.transcript import load_user_messages

logger = logging.getLogger(__name__)


def run_hook(*, input_stream: TextIO, output_stream: TextIO) -> int:
    """Classify one Claude Code PreToolUse event."""
    try:
        event = json.load(input_stream)
        action = _action_from_event(event)
        verdict = _classifier_from_environment().classify(action)
    except (
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        OSError,
        ProviderError,
    ) as error:
        # Safe to swallow: ASK is the fail-safe and preserves normal human review.
        logger.error(
            "Permission classification failed; escalating to user", exc_info=True
        )
        verdict = Verdict(
            decision=Decision.ASK,
            confidence=0.0,
            reason=f"Jev classifier unavailable: {error}",
            latency_ms=0.0,
        )
        action = _best_effort_action(locals().get("event"))
    _write_hook_output(output_stream=output_stream, verdict=verdict)
    append_decision(
        path=_log_path(),
        tool_name=action.tool_name,
        action_hash=_action_hash(action),
        verdict=verdict,
    )
    return 0


def _classifier_from_environment() -> OpenRouterJevClassifier:
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY is not set")
    threshold = float(os.environ.get("JEV_AUTO_MODE_CONFIDENCE", "0.85"))
    validate_threshold(threshold)
    timeout = float(os.environ.get("JEV_AUTO_MODE_TIMEOUT_SECONDS", "3"))
    if timeout <= 0:
        raise ValueError("JEV_AUTO_MODE_TIMEOUT_SECONDS must be positive")
    return OpenRouterJevClassifier(
        api_key=api_key,
        confidence_threshold=threshold,
        timeout=timeout,
        model=os.environ.get("JEV_OPENROUTER_MODEL", "typesafe/jev-1.13"),
        decisions_url=os.environ.get(
            "OPENROUTER_DECISIONS_URL",
            "https://openrouter.ai/api/alpha/decisions",
        ),
    )


def _action_from_event(event: Any) -> ToolAction:
    if not isinstance(event, dict):
        raise TypeError("hook input must be a JSON object")
    tool_name = event["tool_name"]
    tool_input = event["tool_input"]
    cwd = event["cwd"]
    if not isinstance(tool_name, str) or not isinstance(cwd, str):
        raise TypeError("tool_name and cwd must be strings")
    if not isinstance(tool_input, dict):
        raise TypeError("tool_input must be an object")
    transcript_path = event.get("transcript_path")
    user_messages = (
        load_user_messages(Path(transcript_path))
        if isinstance(transcript_path, str)
        else ()
    )
    if not user_messages:
        logger.warning("No human-authored messages were found for this tool call")
    return ToolAction(
        user_messages=user_messages,
        tool_name=tool_name,
        tool_input=tool_input,
        cwd=cwd,
    )


def _best_effort_action(event: Any) -> ToolAction:
    event = event if isinstance(event, dict) else {}
    tool_input = event.get("tool_input", {})
    return ToolAction(
        user_messages=(),
        tool_name=str(event.get("tool_name", "unknown")),
        tool_input=tool_input if isinstance(tool_input, dict) else {},
        cwd=str(event.get("cwd", "unknown")),
    )


def _write_hook_output(*, output_stream: TextIO, verdict: Verdict) -> None:
    decision = "deny" if verdict.decision is Decision.BLOCK else verdict.decision.value
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": verdict.reason,
        }
    }
    json.dump(payload, output_stream, separators=(",", ":"))
    output_stream.write("\n")


def _action_hash(action: ToolAction) -> str:
    encoded = json.dumps(
        {
            "user_messages": action.user_messages,
            "tool_name": action.tool_name,
            "tool_input": action.tool_input,
            "cwd": action.cwd,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


def _log_path() -> Path:
    configured = os.environ.get("JEV_AUTO_MODE_LOG_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".local" / "state" / "jev-auto-mode" / "decisions.jsonl"


def main() -> int:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "WARNING"))
    return run_hook(input_stream=sys.stdin, output_stream=sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
