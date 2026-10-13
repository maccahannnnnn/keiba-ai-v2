"""Regression coverage for canonical DecisionEngine tie ranking."""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.decision_engine import DecisionEngine


def _row(number: int, score: float) -> dict:
    return {
        "horse_number": number,
        "horse_name": f"Horse{number}",
        "adjusted_score": score,
        "final_score": score,
        "consistency_score": 0.9,
        "strong_matches": ["a", "b", "c", "d"],
        "final_strengths": ["距離適性", "ラップ適性", "血統適性"],
        "warnings": [],
        "final_risks": [],
        "conflict_factors": [],
    }


def _rank_by_number(rows: list[dict]) -> dict[int, int | None]:
    results = DecisionEngine().decide_many(rows)
    return {
        int(row["horse_number"]): result.get("ai_rank")
        for row, result in zip(rows, results)
    }


def _tie_rows() -> list[dict]:
    # #10 and #4 are the 5th/6th-boundary tie from the 2026-03-21 incident.
    return [
        _row(1, 220.0), _row(2, 200.0), _row(3, 180.0), _row(5, 150.0),
        _row(4, 123.6), _row(10, 123.6), _row(6, 100.0),
    ]


def test_tied_score_rank_is_stable_over_200_allocation_and_order_variations() -> None:
    expected = {1: 1, 2: 2, 3: 3, 5: 4, 10: 5, 4: 6, 6: 7}
    for seed in range(200):
        randomizer = random.Random(seed)
        source = _tie_rows()
        randomizer.shuffle(source)
        # Allocate fresh dictionaries in a separate creation order from list order.
        allocation = list(source)
        randomizer.shuffle(allocation)
        fresh = {row["horse_number"]: dict(row) for row in allocation}
        rows = [fresh[row["horse_number"]] for row in source]
        assert _rank_by_number(rows) == expected


def test_tied_score_rank_is_stable_across_fresh_processes_and_hash_seeds() -> None:
    program = """
import json
from engine.decision_engine import DecisionEngine
rows = [
 {'horse_number': 1, 'adjusted_score': 220.0},
 {'horse_number': 2, 'adjusted_score': 200.0},
 {'horse_number': 3, 'adjusted_score': 180.0},
 {'horse_number': 5, 'adjusted_score': 150.0},
 {'horse_number': 4, 'adjusted_score': 123.6},
 {'horse_number': 10, 'adjusted_score': 123.6},
 {'horse_number': 6, 'adjusted_score': 100.0},
]
rows = list(reversed(rows))
out = DecisionEngine().decide_many(rows)
print(json.dumps({str(row['horse_number']): result['ai_rank'] for row, result in zip(rows, out)}, sort_keys=True))
"""
    expected = {"1": 1, "2": 2, "3": 3, "4": 6, "5": 4, "6": 7, "10": 5}
    for seed in ("1", "2", "7", "19", "101", "99991"):
        environment = dict(os.environ, PYTHONHASHSEED=seed)
        raw = subprocess.check_output(
            [sys.executable, "-c", program], cwd=ROOT, env=environment, text=True
        )
        assert json.loads(raw) == expected


def test_non_tie_rank_order_is_unchanged() -> None:
    rows = [_row(3, 120.0), _row(1, 140.0), _row(2, 130.0)]
    assert _rank_by_number(rows) == {3: 3, 1: 1, 2: 2}


if __name__ == "__main__":
    test_tied_score_rank_is_stable_over_200_allocation_and_order_variations()
    test_tied_score_rank_is_stable_across_fresh_processes_and_hash_seeds()
    test_non_tie_rank_order_is_unchanged()
    print("DecisionEngine deterministic tie-break tests: PASS")
