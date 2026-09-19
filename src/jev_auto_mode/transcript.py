from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def load_user_messages(path: Path, *, limit: int = 8) -> tuple[str, ...]:
    """Read only human-authored text from a Claude Code JSONL transcript."""
    messages: list[str] = []
    if not path.exists():
        logger.warning("Transcript does not exist: %s", path)
        return ()
    with path.open(encoding="utf-8") as transcript:
        for line_number, line in enumerate(transcript, start=1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                logger.warning(
                    "Skipping malformed transcript line %s in %s", line_number, path
                )
                continue
            text = _human_text(event)
            if text:
                messages.append(text)
    return tuple(messages[-limit:])


def _human_text(event: Any) -> str | None:
    if not isinstance(event, dict) or event.get("type") != "user":
        logger.debug("Skipping non-user transcript event")
        return None
    message = event.get("message")
    if not isinstance(message, dict) or message.get("role") != "user":
        logger.debug("Skipping transcript event without a user message")
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content.strip() or None
    if not isinstance(content, list):
        logger.debug("Skipping user message with unsupported content")
        return None
    text_parts = [
        block["text"].strip()
        for block in content
        if isinstance(block, dict)
        and block.get("type") == "text"
        and isinstance(block.get("text"), str)
        and block["text"].strip()
    ]
    if not text_parts:
        logger.debug("Skipping tool-result-only user message")
        return None
    return "\n".join(text_parts)
