from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, Iterable, List, Mapping

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from review.risk_statistics_engine import RiskStatisticsEngine


class InputLimitationAnalyzer:
    """Break INPUT_LIMITATION risk reasons into more useful subcategories."""

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self.engine = RiskStatisticsEngine(base_dir=base_dir)

    def analyze(self, rows: Iterable[Mapping[str, str]]) -> List[Dict[str, object]]:
        return self.engine.aggregate_input_limitations(rows)


def main() -> None:
    analyzer = InputLimitationAnalyzer()
    rows = analyzer.engine.load_rows()
    for item in analyzer.analyze(rows):
        print(item)


if __name__ == "__main__":
    main()
