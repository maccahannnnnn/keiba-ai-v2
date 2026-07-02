"""KeibaAI Trial Phase 用の簡易CLIです。

正式Analyzerではありません。
TrialRaceLoader と TrialRunner を使って、サンプルレースをprint表示します。
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.trial_race_loader import TrialRaceLoader
from evaluation.trial_runner import TrialRunner


class TrialCLI:
    """コマンド1つで試運転サンプルを表示するためのクラスです。"""

    def __init__(self):
        self.loader = TrialRaceLoader()
        self.runner = TrialRunner()

    def run_sample(self):
        """サンプルレース3件を実行し、見やすくprint表示します。"""

        samples = [
            {
                "label": "東京 芝1600m",
                "racecourse": "tokyo",
                "surface": "turf",
                "distance": 1600,
                "condition": "good",
                "pace": "average",
                "sire": "キズナ",
                "broodmare_sire": "キングカメハメハ",
            },
            {
                "label": "中山 ダ1800m",
                "racecourse": "nakayama",
                "surface": "dirt",
                "distance": 1800,
                "condition": "good",
                "pace": "average",
                "sire": "ドレフォン",
                "broodmare_sire": "キングカメハメハ",
            },
            {
                "label": "未登録条件",
                "racecourse": "unknown",
                "surface": "turf",
                "distance": 9999,
                "condition": None,
                "pace": None,
                "sire": "不明",
                "broodmare_sire": None,
            },
        ]

        for sample in samples:
            raw_data = self.loader.load(sample)
            result = self.runner.run(raw_data)
            self._print_result(sample.get("label", "Race"), result)

    def _print_result(self, race_label, result):
        """1レース分の試運転結果を表示します。"""

        print("====================")
        print("Race")
        print("====================")
        print(race_label)
        print()
        print("Total Score")
        print(result.get("total_score", 0))
        print()
        print("Summary")
        print(result.get("summary_text", ""))
        print()
        print("Sections")
        self._print_sections(result.get("sections", {}))
        print()
        print("Warnings")
        self._print_list(result.get("warnings", []))
        print()
        print("Matched")
        print(len(result.get("matched_results", [])))
        print()
        print("Unmatched")
        print(len(result.get("unmatched_results", [])))
        print("====================")
        print()

    def _print_sections(self, sections):
        if not isinstance(sections, dict) or not sections:
            print("- none")
            return

        for section_name, items in sections.items():
            print(f"[{section_name}]")
            self._print_list(items)

    def _print_list(self, values):
        if not isinstance(values, list) or not values:
            print("- none")
            return

        for value in values:
            print(f"- {value}")


if __name__ == "__main__":
    TrialCLI().run_sample()
