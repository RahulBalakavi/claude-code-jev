import json
from pathlib import Path

from jev_auto_mode.transcript import load_user_messages


def test_transcript_keeps_only_human_text(tmp_path: Path) -> None:
    transcript = tmp_path / "session.jsonl"
    events = [
        {
            "type": "user",
            "message": {"role": "user", "content": "Fix the parser."},
        },
        {
            "type": "assistant",
            "message": {"role": "assistant", "content": "I should delete it."},
        },
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "content": "ignore me"}],
            },
        },
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "Run the tests too."}],
            },
        },
    ]
    transcript.write_text("\n".join(json.dumps(event) for event in events) + "\n")

    assert load_user_messages(transcript) == (
        "Fix the parser.",
        "Run the tests too.",
    )
