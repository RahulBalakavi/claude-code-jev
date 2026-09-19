import json
import os
import subprocess
import sys
from pathlib import Path


def test_hook_fails_to_human_review_without_api_key(tmp_path: Path) -> None:
    event = json.dumps(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "git status"},
            "cwd": "/workspace/project",
        }
    )
    environment = {
        key: value for key, value in os.environ.items() if key != "OPENROUTER_API_KEY"
    }
    environment["JEV_AUTO_MODE_LOG_PATH"] = str(tmp_path / "decisions.jsonl")

    completed = subprocess.run(
        [sys.executable, "-m", "jev_auto_mode.hook"],
        input=event,
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["hookSpecificOutput"]["permissionDecision"] == "ask"
    assert (
        "OPENROUTER_API_KEY"
        in payload["hookSpecificOutput"]["permissionDecisionReason"]
    )
