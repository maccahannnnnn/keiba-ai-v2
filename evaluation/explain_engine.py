"""EvaluationAggregator の結果から説明文を作るためのEngineです。

このモジュールは評価スコアを変更しません。
Aggregator がまとめた explains / modifiers / total_score を読み取り、
Explainable AI 用に見やすく整理するだけの独立モジュールです。
"""


class ExplainEngine:
    """総合評価結果を source_type ごとの説明に整理するクラスです。"""

    DEFAULT_SECTIONS = ["course", "bloodline", "track_condition", "pace"]

    SECTION_LABELS = {
        "course": "コース適性",
        "bloodline": "血統面",
        "track_condition": "馬場状態",
        "pace": "展開面",
        "other": "その他",
    }

    def build(self, aggregate_result):
        """Aggregatorの返却辞書から説明用の辞書を作ります。

        Args:
            aggregate_result (dict | None): EvaluationAggregator.aggregate() の返却値。

        Returns:
            dict: summary_text / sections / total_score / modifier_summary を持つ辞書。
        """

        result = aggregate_result if isinstance(aggregate_result, dict) else {}
        total_score = self._safe_number(result.get("total_score"))
        modifier_summary = result.get("modifiers")
        if not isinstance(modifier_summary, dict):
            modifier_summary = {}

        sections = self._build_sections(result.get("explains"))
        summary_text = self._build_summary_text(total_score, sections)

        return {
            "summary_text": summary_text,
            "sections": sections,
            "total_score": total_score,
            "modifier_summary": dict(modifier_summary),
        }

    def _build_sections(self, explains):
        """explainsをsource_typeごとのセクションに分類します。"""

        sections = {name: [] for name in self.DEFAULT_SECTIONS}
        sections["other"] = []

        if not isinstance(explains, list):
            return sections

        for item in explains:
            source_type, explain_text = self._extract_explain(item)
            if not explain_text:
                continue

            section_name = source_type if source_type in sections and source_type != "other" else "other"
            sections[section_name].append(explain_text)

        return sections

    def _extract_explain(self, item):
        """dict / object / 文字列のどれでもExplainを取り出せるようにします。"""

        if isinstance(item, dict):
            source_type = item.get("source_type") or "other"
            explain_text = item.get("explain") or item.get("Explain") or item.get("text")
            return str(source_type), str(explain_text) if explain_text else ""

        if hasattr(item, "source_type") or hasattr(item, "explain"):
            source_type = getattr(item, "source_type", "other")
            explain_text = getattr(item, "explain", "")
            return str(source_type), str(explain_text) if explain_text else ""

        if isinstance(item, str):
            return "other", item

        return "other", ""

    def _build_summary_text(self, total_score, sections):
        """セクション内容から読みやすい説明文を作ります。"""

        lines = [f"総合評価は {self._format_score(total_score)}。"]

        for section_name in ["course", "bloodline", "track_condition", "pace", "other"]:
            section_items = sections.get(section_name, [])
            if not section_items:
                continue

            label = self.SECTION_LABELS.get(section_name, section_name)
            joined_text = " ".join(section_items)
            lines.append(f"{label}では、{joined_text}")

        if len(lines) == 1:
            lines.append("説明に使えるExplain情報はまだありません。")

        return "\n\n".join(lines)

    def _format_score(self, score):
        """プラス値を + 表記にして、説明文で読みやすくします。"""

        if score > 0:
            return f"+{score:g}"
        return f"{score:g}"

    def _safe_number(self, value):
        """数値でなければ0として扱います。"""

        if isinstance(value, bool):
            return 0
        if isinstance(value, (int, float)):
            return value
        return 0


if __name__ == "__main__":
    engine = ExplainEngine()
    dummy_aggregate_result = {
        "total_score": 18,
        "modifiers": {
            "sustained_speed": 5,
            "late_speed": 4,
            "left_turn": 2,
        },
        "explains": [
            {
                "source_type": "course",
                "explain": "東京芝1600mの特徴から持続力と左回り適性を評価しました。",
            },
            {
                "source_type": "bloodline",
                "explain": "キズナ産駒の末脚持続力を評価しました。",
            },
            {
                "source_type": "track_condition",
                "explain": "高速馬場への適性を評価しました。",
            },
            {
                "source_type": "pace",
                "explain": "平均ペースで能力を発揮しやすいと判断しました。",
            },
            {
                "source_type": "jockey",
                "explain": "未知のsource_typeはotherへ分類します。",
            },
        ],
    }

    print(engine.build(dummy_aggregate_result))
    print(engine.build(None))
