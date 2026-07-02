"""raw_dataからEvaluation Engineを試運転するためのRunnerです。

このモジュールは正式Analyzerではありません。
RaceContextBuilder と TrialAnalyzer を接続し、辞書形式のraw_dataだけで
コース・血統・馬場・展開の試運転結果を確認できるようにします。
"""

from evaluation.race_context_builder import RaceContextBuilder
from evaluation.trial_analyzer import TrialAnalyzer


class TrialRunner:
    """raw_dataを受け取り、試運転用の最終結果を返すクラスです。"""

    def __init__(self):
        self.context_builder = RaceContextBuilder()
        self.trial_analyzer = TrialAnalyzer()

    def run(self, raw_data):
        """raw_dataをrace_contextへ変換し、TrialAnalyzerで評価します。

        Returns:
            dict: TrialAnalyzerの結果から、試運転で見たい要素だけを抜き出した辞書。
        """

        race_context = self.context_builder.build(raw_data)
        analysis_result = self.trial_analyzer.analyze(race_context)
        aggregate_result = analysis_result.get("aggregate_result", {})
        explain_result = analysis_result.get("explain_result", {})

        return {
            "total_score": aggregate_result.get("total_score", 0),
            "summary_text": explain_result.get("summary_text", ""),
            "sections": explain_result.get("sections", {}),
            "modifier_summary": explain_result.get("modifier_summary", {}),
            "warnings": aggregate_result.get("warnings", []),
            "matched_results": aggregate_result.get("matched_results", []),
            "unmatched_results": aggregate_result.get("unmatched_results", []),
        }


if __name__ == "__main__":
    runner = TrialRunner()
    samples = [
        {
            "racecourse": "tokyo",
            "surface": "turf",
            "distance": 1600,
            "pace": "average",
            "track_condition": "good",
            "bias_type": "fast_track",
            "sire_name": "キズナ",
            "broodmare_sire_name": "キングカメハメハ",
        },
        {
            "racecourse": "nakayama",
            "surface": "dirt",
            "distance": 1800,
            "pace": "average",
            "track_condition": "heavy",
            "bias_type": "power_track",
            "sire_name": "ドレフォン",
            "broodmare_sire_name": "キングカメハメハ",
        },
        {},
    ]

    for sample in samples:
        result = runner.run(sample)
        print(
            {
                "summary_text": result["summary_text"],
                "total_score": result["total_score"],
                "sections": result["sections"],
                "warnings": result["warnings"],
            }
        )
