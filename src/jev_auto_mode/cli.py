from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from jev_auto_mode.benchmark import load_cases, run_benchmark, write_results
from jev_auto_mode.capacity import project_capacity
from jev_auto_mode.hook import run_hook
from jev_auto_mode.policy import validate_threshold
from jev_auto_mode.providers import (
    AnthropicClassifier,
    Classifier,
    OpenRouterHaikuClassifier,
    OpenRouterJevClassifier,
)

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jev-auto-mode",
        description="Jev-backed permission decisions and reproducible benchmarks.",
    )
    parser.add_argument("--verbose", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("hook", help="Read one Claude Code hook event from stdin")

    benchmark = commands.add_parser("benchmark", help="Run the labeled A/B fixture")
    benchmark.add_argument(
        "--provider", choices=["jev", "haiku", "anthropic"], required=True
    )
    benchmark.add_argument(
        "--fixture", type=Path, default=Path("fixtures/actions.jsonl")
    )
    benchmark.add_argument("--output", type=Path)
    benchmark.add_argument("--threshold", type=float, default=0.85)
    benchmark.add_argument("--timeout", type=float)
    benchmark.add_argument("--model")

    capacity = commands.add_parser(
        "capacity", help="Project daily time and token capacity"
    )
    capacity.add_argument("--baseline-ms", type=float, required=True)
    capacity.add_argument("--candidate-ms", type=float, required=True)
    capacity.add_argument("--tool-calls", type=int, required=True)
    capacity.add_argument("--tokens-per-second", type=float, default=25)
    capacity.add_argument("--non-classifier-minutes", type=float, default=480)
    capacity.add_argument("--working-days-per-month", type=int, default=22)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)
    if args.command == "hook":
        return run_hook(input_stream=sys.stdin, output_stream=sys.stdout)
    if args.command == "capacity":
        projection = project_capacity(
            baseline_latency_ms=args.baseline_ms,
            candidate_latency_ms=args.candidate_ms,
            tool_calls_per_day=args.tool_calls,
            productive_tokens_per_second=args.tokens_per_second,
            non_classifier_minutes_per_day=args.non_classifier_minutes,
            working_days_per_month=args.working_days_per_month,
        )
        print(json.dumps(asdict(projection), indent=2))
        return 0
    return _benchmark(args)


def _benchmark(args: argparse.Namespace) -> int:
    validate_threshold(args.threshold)
    classifier = _build_classifier(args)
    cases = load_cases(args.fixture)
    summary, results = run_benchmark(
        classifier=classifier,
        provider_name=args.provider,
        cases=cases,
    )
    print(json.dumps(asdict(summary), indent=2))
    if args.output is not None:
        write_results(path=args.output, summary=summary, results=results)
    else:
        logger.debug("No output file requested; printing summary only")
    return 0


def _build_classifier(args: argparse.Namespace) -> Classifier:
    if args.provider == "jev":
        api_key = _required_environment("OPENROUTER_API_KEY")
        return OpenRouterJevClassifier(
            api_key=api_key,
            confidence_threshold=args.threshold,
            timeout=args.timeout or 3.0,
            model=args.model or "typesafe/jev-1.13",
        )
    if args.provider == "haiku":
        api_key = _required_environment("OPENROUTER_API_KEY")
        return OpenRouterHaikuClassifier(
            api_key=api_key,
            confidence_threshold=args.threshold,
            timeout=args.timeout or 15.0,
            model=args.model or "anthropic/claude-haiku-4.5",
        )
    api_key = _required_environment("ANTHROPIC_API_KEY")
    return AnthropicClassifier(
        api_key=api_key,
        confidence_threshold=args.threshold,
        timeout=args.timeout or 15.0,
        model=args.model or "claude-sonnet-4-6",
    )


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
