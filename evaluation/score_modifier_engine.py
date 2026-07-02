"""score_modifiers を安全に集約するための独立エンジンです。

Knowledge Base に登録されている score_modifiers / modifier_reasons / Explain を、
将来の評価エンジンで使いやすい形にまとめます。

重要:
    このモジュールはまだ Analyzer や main.py には接続しません。
    単体で使える部品として追加しています。
"""


class ScoreModifierEngine:
    """複数の score_modifiers を安全に合算するクラスです。

    v1.1 では source_type を追加し、補正がどの評価ソースから来たかを追跡します。
    source_type は任意文字列を受け付けるため、将来の評価項目追加にも対応できます。
    """

    def __init__(self):
        """集計用の空データを用意します。"""

        self._modifiers = {}
        self._reasons = []
        self._explains = []
        self._source_type_summary = {}

    def add_modifiers(
        self,
        source_name,
        score_modifiers,
        modifier_reasons=None,
        explain=None,
        source_type="general",
    ):
        """modifier を追加して、同じ modifier 名ごとにスコアを合算します。

        Args:
            source_name (str | None): どの知識データから来た補正かを示す名前。
            score_modifiers (dict | None): {"modifier名": 数値} の辞書。
            modifier_reasons (dict | None): {"modifier名": "理由"} の辞書。
            explain (str | None): Explain 用の自然文コメント。
            source_type (str | None): course / bloodline など補正元の種類。
        """

        source = str(source_name) if source_name is not None else "unknown"
        source_kind = str(source_type) if source_type is not None else "general"
        modifiers = score_modifiers or {}
        reasons = modifier_reasons or {}

        if not isinstance(modifiers, dict):
            return

        if not isinstance(reasons, dict):
            reasons = {}

        self._ensure_source_type(source_kind)

        for modifier_name, score in modifiers.items():
            if not self._is_valid_score(score):
                continue

            modifier = str(modifier_name)
            self._modifiers[modifier] = self._modifiers.get(modifier, 0) + score

            source_summary = self._source_type_summary[source_kind]
            source_summary["total_score"] += score
            source_summary["modifiers"][modifier] = (
                source_summary["modifiers"].get(modifier, 0) + score
            )
            if source not in source_summary["sources"]:
                source_summary["sources"].append(source)

            self._reasons.append(
                {
                    "source_type": source_kind,
                    "source": source,
                    "modifier": modifier,
                    "score": score,
                    "reason": reasons.get(modifier, ""),
                }
            )

        if explain:
            self._explains.append(
                {
                    "source_type": source_kind,
                    "source": source,
                    "explain": str(explain),
                }
            )

    def get_total_score(self):
        """すべての modifier スコアの合計を返します。"""

        return sum(self._modifiers.values())

    def get_modifier_breakdown(self):
        """modifier 名ごとの合算結果を返します。"""

        return dict(self._modifiers)

    def get_reason_list(self):
        """Explain Engine などで使える理由一覧を返します。"""

        return list(self._reasons)

    def get_explain_list(self):
        """知識データ由来の Explain コメント一覧を返します。"""

        return list(self._explains)

    def get_source_type_summary(self):
        """source_type ごとの合計、modifier 内訳、source 一覧を返します。"""

        summary = {}
        for source_type, values in self._source_type_summary.items():
            summary[source_type] = {
                "total_score": values["total_score"],
                "modifiers": dict(values["modifiers"]),
                "sources": list(values["sources"]),
            }
        return summary

    def get_summary(self):
        """集計結果をまとめて辞書で返します。"""

        return {
            "total_score": self.get_total_score(),
            "modifiers": self.get_modifier_breakdown(),
            "reasons": self.get_reason_list(),
            "explains": self.get_explain_list(),
            "source_type_summary": self.get_source_type_summary(),
        }

    def _ensure_source_type(self, source_type):
        """source_type ごとの集計枠を必要に応じて作成します。"""

        if source_type not in self._source_type_summary:
            self._source_type_summary[source_type] = {
                "total_score": 0,
                "modifiers": {},
                "sources": [],
            }

    @staticmethod
    def _is_valid_score(score):
        """modifier の値として使える数値かどうかを判定します。"""

        return isinstance(score, (int, float)) and not isinstance(score, bool)


if __name__ == "__main__":
    engine = ScoreModifierEngine()

    engine.add_modifiers(
        source_name="tokyo_turf_1600",
        source_type="course",
        score_modifiers={
            "left_turn": 2,
            "sustained_speed": 3,
            "invalid_value": "skip",
        },
        modifier_reasons={
            "left_turn": "東京芝1600mの左回り適性を評価",
            "sustained_speed": "長い直線で持続力を評価",
        },
        explain="東京芝1600mは長い直線で持続力を評価する。",
    )

    engine.add_modifiers(
        source_name="kizuna",
        source_type="bloodline",
        score_modifiers={
            "late_speed": 2,
            "stamina": 2,
        },
        modifier_reasons={
            "late_speed": "キズナ系の末脚性能を評価",
            "stamina": "中距離での底力を評価",
        },
        explain="キズナ系は持続力と中距離適性を評価する。",
    )

    engine.add_modifiers(
        source_name="manual_check",
        score_modifiers={
            "condition_note": 1,
        },
        modifier_reasons={
            "condition_note": "手動メモによる汎用補正",
        },
        explain="汎用補正は source_type 未指定時に general として扱う。",
    )

    print(engine.get_summary())
