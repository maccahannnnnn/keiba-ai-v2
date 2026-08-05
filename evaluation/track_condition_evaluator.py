"""Track Condition Knowledge を ScoreModifierEngine に渡す独立Evaluatorです。

このモジュールはまだ Analyzer や main.py には接続しません。
既存の馬場状態教科書を読み取り、単体で馬場補正の summary を返します。
"""

from evaluation.score_modifier_engine import ScoreModifierEngine


class TrackConditionEvaluator:
    """馬場状態・馬場傾向からTrack Condition Profileを評価するクラスです。"""

    CONDITION_PROFILE_MAP = {
        "good": ["良馬場巧者"],
        "良": ["良馬場巧者"],
        "yielding": ["稍重巧者"],
        "稍": ["稍重巧者"],
        "稍重": ["稍重巧者"],
        "soft": ["重馬場巧者"],
        "重": ["重馬場巧者"],
        "heavy": ["不良馬場巧者"],
        "不": ["不良馬場巧者"],
        "不良": ["不良馬場巧者"],
        "firm": ["高速決着型"],
        "good": ["良馬場巧者"],
        "良": ["良馬場巧者"],
        "yielding": ["稍重巧者"],
        "稍重": ["稍重巧者"],
        "soft": ["重馬場巧者"],
        "重": ["重馬場巧者"],
        "heavy": ["不良馬場巧者"],
        "不良": ["不良馬場巧者"],
    }

    BIAS_PROFILE_MAP = {
        "fast_track": ["高速決着型"],
        "speed_track": ["高速決着型"],
        "firm_track": ["高速瞬発型"],
        "power_track": ["タフ馬場型"],
        "heavy_track": ["タフ馬場型", "消耗戦型"],
        "wet_track": ["雨歓迎型"],
        "stamina_track": ["消耗戦型"],
        "outside_bias": ["外差し向き"],
        "outer_bias": ["外差し向き"],
        "inside_bias": ["内伸び向き"],
        "inner_bias": ["内伸び向き"],
        "opening_week": ["開幕週向き"],
        "middle_meeting": ["中盤開催向き"],
        "final_week": ["最終週向き"],
        "western_turf": ["洋芝巧者"],
        "japanese_turf": ["野芝巧者"],
        "clock": ["時計勝負型"],
        "late_speed": ["上がり勝負型"],
        "sustained": ["持続戦型"],
        "hill": ["坂歓迎型"],
        "flat": ["平坦歓迎型"],
    }

    SURFACE_PROFILE_MAP = {
        "turf": [],
        "芝": [],
        "dirt": [],
        "ダート": [],
    }

    def evaluate(self, surface=None, condition=None, bias_type=None):
        """指定された馬場状態・傾向に合うProfileを集約して返します。"""

        normalized_surface = self._normalize_text(surface)
        normalized_condition = self._normalize_text(condition)
        normalized_bias = self._normalize_text(bias_type)
        profiles = self._load_profiles()
        matched_profile_names = self._resolve_profile_names(
            normalized_surface,
            normalized_condition,
            normalized_bias,
            profiles,
        )

        engine = ScoreModifierEngine()
        matched_sources = []

        for profile_name in matched_profile_names:
            profile = profiles.get(profile_name)
            if profile is None:
                continue

            source_name = self._make_source_name(
                normalized_surface,
                normalized_condition,
                normalized_bias,
                profile_name,
            )
            engine.add_modifiers(
                source_name=source_name,
                source_type="track_condition",
                score_modifiers=self._get_value(profile, ["score_modifiers"]),
                modifier_reasons=self._get_value(
                    profile,
                    ["modifier_reasons", "modifier_reason"],
                ),
                explain=self._get_value(profile, ["explain", "Explain"]),
            )
            matched_sources.append(source_name)

        matched = bool(matched_sources)
        result = {
            "surface": surface,
            "condition": condition,
            "bias_type": bias_type,
            "matched": matched,
            "matched_sources": matched_sources,
            "summary": engine.get_summary() if matched else self._empty_summary(),
        }

        if not matched:
            result["warning"] = "Track condition profile not found"

        return result

    def _resolve_profile_names(self, surface, condition, bias_type, profiles):
        """入力値から該当するProfile名を重複なしで返します。"""

        candidates = []

        for profile_name in self.SURFACE_PROFILE_MAP.get(surface, []):
            candidates.append(profile_name)

        for profile_name in self.CONDITION_PROFILE_MAP.get(condition, []):
            candidates.append(profile_name)

        actual_condition_profiles = {
            "good": "良馬場巧者",
            "良": "良馬場巧者",
            "yielding": "稍重巧者",
            "稍": "稍重巧者",
            "稍重": "稍重巧者",
            "soft": "重馬場巧者",
            "重": "重馬場巧者",
            "heavy": "不良馬場巧者",
            "不": "不良馬場巧者",
            "不良": "不良馬場巧者",
        }
        if condition in actual_condition_profiles:
            candidates.append(actual_condition_profiles[condition])

        for profile_name in self.BIAS_PROFILE_MAP.get(bias_type, []):
            candidates.append(profile_name)

        if condition in profiles:
            candidates.append(condition)
        if bias_type in profiles:
            candidates.append(bias_type)

        return self._unique_existing(candidates, profiles)

    def _load_profiles(self):
        """馬場状態Knowledgeを安全に読み込みます。"""

        try:
            from knowledge.bloodlines.track_condition import TRACK_CONDITION_BLOODLINES
        except Exception:
            return {}

        return TRACK_CONDITION_BLOODLINES if isinstance(TRACK_CONDITION_BLOODLINES, dict) else {}

    def _get_value(self, profile, names):
        """dict / dataclass / object のどれでも値を取得できるようにします。"""

        for name in names:
            if isinstance(profile, dict) and name in profile:
                return profile.get(name)
            if hasattr(profile, name):
                return getattr(profile, name)
        return None

    def _make_source_name(self, surface, condition, bias_type, profile_name):
        """source_nameを入力条件とProfile名から作ります。"""

        parts = ["track_condition"]
        if surface:
            parts.append(surface)
        if condition:
            parts.append(condition)
        if bias_type:
            parts.append(bias_type)
        parts.append(profile_name)
        return "_".join(parts)

    def _normalize_text(self, value):
        if value is None:
            return None
        text = str(value).strip()
        return text.lower() if self._is_ascii(text) else text

    def _is_ascii(self, value):
        try:
            value.encode("ascii")
        except UnicodeEncodeError:
            return False
        return True

    def _unique_existing(self, values, profiles):
        unique_values = []
        seen = set()
        for value in values:
            if value in seen or value not in profiles:
                continue
            seen.add(value)
            unique_values.append(value)
        return unique_values

    def _empty_summary(self):
        return {
            "total_score": 0,
            "modifiers": {},
            "reasons": [],
            "explains": [],
            "source_type_summary": {},
        }


if __name__ == "__main__":
    evaluator = TrackConditionEvaluator()
    checks = [
        ("turf", "good", "fast_track"),
        ("dirt", "heavy", "power_track"),
        ("turf", "良", None),
        ("turf", "unknown", None),
    ]

    for surface, condition, bias_type in checks:
        result = evaluator.evaluate(
            surface=surface,
            condition=condition,
            bias_type=bias_type,
        )
        print(
            {
                "input": (surface, condition, bias_type),
                "matched": result["matched"],
                "matched_sources": result["matched_sources"],
                "summary_keys": list(result["summary"].keys()),
                "source_type_summary": result["summary"]["source_type_summary"],
            }
        )
