import os
import subprocess
from pathlib import Path

LAUNCHER = Path(__file__).parents[1] / "bin" / "claude-openrouter"


def test_launcher_requires_openrouter_key() -> None:
    environment = {
        key: value for key, value in os.environ.items() if key != "OPENROUTER_API_KEY"
    }
    environment["CLAUDE_OPENROUTER_BIN"] = "/usr/bin/true"

    completed = subprocess.run(
        [str(LAUNCHER)],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )

    assert completed.returncode == 1
    assert "OPENROUTER_API_KEY is required" in completed.stderr


def test_launcher_accepts_openrouter_key_from_environment() -> None:
    environment = os.environ.copy()
    environment["CLAUDE_OPENROUTER_BIN"] = "/usr/bin/true"
    environment["OPENROUTER_API_KEY"] = "test-key"

    completed = subprocess.run(
        [str(LAUNCHER)],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )

    assert completed.returncode == 0
