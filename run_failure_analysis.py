"""CLI entry point for Failure Analysis Engine v1.0."""

from __future__ import annotations

import argparse
import json

from review.failure_analysis_engine import FailureAnalysisEngine, PROJECT_ID


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run KeibaAI failure analysis")
    parser.add_argument("--project-id", default=PROJECT_ID)
    parser.add_argument("--validation-mode", default="general-unseen", choices=["general-unseen", "focused-unseen"])
    parser.add_argument("--race-id", default="")
    parser.add_argument("--horse-number", default="")
    parser.add_argument("--rule-id", default="SP_COUNT_EQ_2")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--run-validators", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> dict[str, object]:
    args = parse_args(argv)
    engine = FailureAnalysisEngine(project_id=args.project_id, validation_mode=args.validation_mode)
    result = engine.run(dry_run=args.dry_run)
    validator = {}
    if args.run_validators and not args.dry_run:
        from review.failure_analysis_validator import run_validation

        validator = run_validation()
        result["validator_result"] = validator
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return result


if __name__ == "__main__":
    main()
