from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import replace
from typing import Any, Protocol

from jev_auto_mode.models import Decision, ToolAction, Verdict
from jev_auto_mode.policy import CRITERIA, QUESTION, apply_confidence_gate

logger = logging.getLogger(__name__)


class Classifier(Protocol):
    def classify(self, action: ToolAction) -> Verdict: ...


class ProviderError(RuntimeError):
    """Raised when a remote classifier cannot return a valid decision."""


def _post_json(
    *, url: str, headers: dict[str, str], body: dict[str, Any], timeout: float
) -> tuple[dict[str, Any], float]:
    encoded = json.dumps(body, separators=(",", ":")).encode()
    request = urllib.request.Request(url, data=encoded, headers=headers, method="POST")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")[:500]
        logger.error("Classifier returned HTTP %s: %s", error.code, detail)
        raise ProviderError(f"classifier returned HTTP {error.code}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        logger.error("Classifier request failed: %s", error)
        raise ProviderError(f"classifier request failed: {error}") from error
    except json.JSONDecodeError as error:
        logger.error("Classifier returned invalid JSON", exc_info=True)
        raise ProviderError("classifier returned invalid JSON") from error
    latency_ms = (time.perf_counter() - started) * 1000
    if not isinstance(payload, dict):
        raise ProviderError("classifier response must be a JSON object")
    return payload, latency_ms


def _state(action: ToolAction) -> dict[str, Any]:
    return {
        "user_messages": list(action.user_messages),
        "requested_tool_call": {
            "tool_name": action.tool_name,
            "tool_input": action.tool_input,
        },
        "trusted_working_directory": action.cwd,
    }


class OpenRouterJevClassifier:
    """Call Jev through OpenRouter's typed decisions endpoint."""

    def __init__(
        self,
        *,
        api_key: str,
        confidence_threshold: float = 0.85,
        timeout: float = 3.0,
        model: str = "typesafe/jev-1.13",
        decisions_url: str = "https://openrouter.ai/api/alpha/decisions",
    ) -> None:
        self.api_key = api_key
        self.confidence_threshold = confidence_threshold
        self.timeout = timeout
        self.model = model
        self.decisions_url = decisions_url

    def classify(self, action: ToolAction) -> Verdict:
        payload, latency_ms = _post_json(
            url=self.decisions_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "jev-auto-mode/0.1.0",
            },
            body={
                "state": _state(action),
                "model": self.model,
                "questions": {
                    "permission": {
                        "type": "choice",
                        "instructions": QUESTION,
                        "criteria": CRITERIA,
                    }
                },
            },
            timeout=self.timeout,
        )
        try:
            answer = payload["answers"]["permission"]
            raw_decision = Decision(answer["choice"])
            confidence = float(answer["confidence"])
            usage = payload.get("usage", {})
        except (KeyError, TypeError, ValueError) as error:
            logger.error("Unexpected Jev response shape: %s", payload)
            raise ProviderError("unexpected Jev response shape") from error
        decision = apply_confidence_gate(
            decision=raw_decision,
            confidence=confidence,
            threshold=self.confidence_threshold,
        )
        reason = (
            f"OpenRouter Jev chose {raw_decision.value} at {confidence:.1%} confidence"
            if decision is raw_decision
            else f"OpenRouter Jev confidence {confidence:.1%} was below the threshold"
        )
        return Verdict(
            decision=decision,
            confidence=confidence,
            reason=reason,
            latency_ms=latency_ms,
            input_tokens=_optional_int(usage.get("input_tokens")),
            output_tokens=_optional_int(usage.get("output_tokens")),
            cost_usd=_optional_float(usage.get("cost")),
            model=str(payload.get("model", self.model)),
        )


class OpenRouterHaikuClassifier:
    """Run the same permission policy through Haiku 4.5 on OpenRouter."""

    def __init__(
        self,
        *,
        api_key: str,
        confidence_threshold: float = 0.85,
        timeout: float = 15.0,
        model: str = "anthropic/claude-haiku-4.5",
        chat_url: str = "https://openrouter.ai/api/v1/chat/completions",
    ) -> None:
        self.api_key = api_key
        self.confidence_threshold = confidence_threshold
        self.timeout = timeout
        self.model = model
        self.chat_url = chat_url

    def classify(self, action: ToolAction) -> Verdict:
        payload, latency_ms = _post_json(
            url=self.chat_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "jev-auto-mode/0.1.0",
            },
            body={
                "model": self.model,
                "max_tokens": 128,
                "temperature": 0,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a permission classifier. Use only user messages "
                            "and the requested tool call. Do not invent authorization."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "question": QUESTION,
                                "criteria": CRITERIA,
                                "state": _state(action),
                            },
                            separators=(",", ":"),
                        ),
                    },
                ],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "record_permission",
                            "description": "Record the permission decision.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "decision": {
                                        "type": "string",
                                        "enum": [item.value for item in Decision],
                                    },
                                    "confidence": {
                                        "type": "number",
                                        "minimum": 0,
                                        "maximum": 1,
                                    },
                                },
                                "required": ["decision", "confidence"],
                                "additionalProperties": False,
                            },
                        },
                    }
                ],
                "tool_choice": {
                    "type": "function",
                    "function": {"name": "record_permission"},
                },
            },
            timeout=self.timeout,
        )
        tool_input = _find_openrouter_tool_input(payload)
        try:
            raw_decision = Decision(tool_input["decision"])
            confidence = float(tool_input["confidence"])
            usage = payload.get("usage", {})
        except (KeyError, TypeError, ValueError) as error:
            logger.error("Unexpected OpenRouter Haiku response shape: %s", payload)
            raise ProviderError("unexpected OpenRouter Haiku response shape") from error
        decision = apply_confidence_gate(
            decision=raw_decision,
            confidence=confidence,
            threshold=self.confidence_threshold,
        )
        reason = (
            f"OpenRouter Haiku chose {raw_decision.value} at "
            f"{confidence:.1%} confidence"
            if decision is raw_decision
            else f"OpenRouter Haiku confidence {confidence:.1%} was below the threshold"
        )
        return Verdict(
            decision=decision,
            confidence=confidence,
            reason=reason,
            latency_ms=latency_ms,
            input_tokens=_optional_int(usage.get("prompt_tokens")),
            output_tokens=_optional_int(usage.get("completion_tokens")),
            cost_usd=_openrouter_cost(usage),
            model=str(payload.get("model", self.model)),
        )


class AnthropicClassifier:
    """A Sonnet policy replica for A/B testing, not Anthropic's private classifier."""

    def __init__(
        self,
        *,
        api_key: str,
        confidence_threshold: float = 0.85,
        timeout: float = 15.0,
        model: str = "claude-sonnet-4-6",
        base_url: str = "https://api.anthropic.com",
    ) -> None:
        self.api_key = api_key
        self.confidence_threshold = confidence_threshold
        self.timeout = timeout
        self.model = model
        self.base_url = base_url.rstrip("/")

    def classify(self, action: ToolAction) -> Verdict:
        payload, latency_ms = _post_json(
            url=f"{self.base_url}/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            body={
                "model": self.model,
                "max_tokens": 64,
                "temperature": 0,
                "system": (
                    "You are a permission classifier. Use only user messages and the "
                    "requested tool call. Do not invent authorization."
                ),
                "messages": [
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "question": QUESTION,
                                "criteria": CRITERIA,
                                "state": _state(action),
                            },
                            separators=(",", ":"),
                        ),
                    }
                ],
                "tools": [
                    {
                        "name": "record_permission",
                        "description": "Record the permission decision.",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "decision": {
                                    "type": "string",
                                    "enum": [item.value for item in Decision],
                                },
                                "confidence": {
                                    "type": "number",
                                    "minimum": 0,
                                    "maximum": 1,
                                },
                            },
                            "required": ["decision", "confidence"],
                            "additionalProperties": False,
                        },
                    }
                ],
                "tool_choice": {"type": "tool", "name": "record_permission"},
            },
            timeout=self.timeout,
        )
        tool_input = _find_tool_input(payload)
        try:
            raw_decision = Decision(tool_input["decision"])
            confidence = float(tool_input["confidence"])
            usage = payload.get("usage", {})
        except (KeyError, TypeError, ValueError) as error:
            logger.error("Unexpected Anthropic response shape: %s", payload)
            raise ProviderError("unexpected Anthropic response shape") from error
        verdict = Verdict(
            decision=raw_decision,
            confidence=confidence,
            reason=f"Sonnet replica chose {raw_decision.value}",
            latency_ms=latency_ms,
            input_tokens=_optional_int(usage.get("input_tokens")),
            output_tokens=_optional_int(usage.get("output_tokens")),
            model=str(payload.get("model", self.model)),
        )
        gated = apply_confidence_gate(
            decision=verdict.decision,
            confidence=verdict.confidence,
            threshold=self.confidence_threshold,
        )
        if gated is verdict.decision:
            return verdict
        return replace(
            verdict,
            decision=gated,
            reason=f"Sonnet confidence {confidence:.1%} was below the threshold",
        )


def _find_tool_input(payload: dict[str, Any]) -> dict[str, Any]:
    content = payload.get("content", [])
    if not isinstance(content, list):
        raise ProviderError("Anthropic content must be a list")
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            tool_input = block.get("input")
            if isinstance(tool_input, dict):
                return tool_input
    raise ProviderError("Anthropic response did not contain a tool decision")


def _find_openrouter_tool_input(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        arguments = payload["choices"][0]["message"]["tool_calls"][0]["function"][
            "arguments"
        ]
    except (KeyError, IndexError, TypeError) as error:
        raise ProviderError(
            "OpenRouter response did not contain a tool decision"
        ) from error
    if isinstance(arguments, dict):
        return arguments
    if not isinstance(arguments, str):
        raise ProviderError("OpenRouter tool arguments must be JSON")
    try:
        tool_input = json.loads(arguments)
    except json.JSONDecodeError as error:
        raise ProviderError("OpenRouter tool arguments were invalid JSON") from error
    if not isinstance(tool_input, dict):
        raise ProviderError("OpenRouter tool arguments must be an object")
    return tool_input


def _optional_int(value: Any) -> int | None:
    if value is None:
        logger.debug("Provider did not report token usage")
        return None
    return int(value)


def _optional_float(value: Any) -> float | None:
    if value is None:
        logger.debug("Provider did not report cost")
        return None
    return float(value)


def _openrouter_cost(usage: Any) -> float | None:
    if not isinstance(usage, dict):
        logger.debug("OpenRouter did not report structured usage")
        return None
    reported_cost = _optional_float(usage.get("cost"))
    if reported_cost not in (None, 0.0):
        return reported_cost
    cost_details = usage.get("cost_details")
    if isinstance(cost_details, dict):
        upstream_cost = _optional_float(cost_details.get("upstream_inference_cost"))
        if upstream_cost is not None:
            return upstream_cost
    return reported_cost
