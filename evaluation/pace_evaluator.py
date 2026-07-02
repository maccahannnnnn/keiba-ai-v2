"""Course Knowledge のペース傾向を単体評価するためのEvaluatorです。

このモジュールは Analyzer や main.py には接続しません。
既存の Course Knowledge を読み取り、ScoreModifierEngine に
source_type="pace" として渡すための土台です。
"""

from importlib import import_module

from evaluation.score_modifier_engine import ScoreModifierEngine


class PaceEvaluator:
    """競馬場・馬場種別・距離・想定ペースから展開評価を返すクラスです。"""

    COURSE_MODULES = {
        "sapporo": ("knowledge.courses.sapporo", "SAPPORO_COURSE_PROFILES"),
        "hakodate": ("knowledge.courses.hakodate", "HAKODATE_COURSE_PROFILES"),
        "fukushima": ("knowledge.courses.fukushima", "FUKUSHIMA_COURSE_PROFILES"),
        "niigata": ("knowledge.courses.niigata", "NIIGATA_COURSE_PROFILES"),
        "tokyo": ("knowledge.courses.tokyo", "TOKYO_COURSE_PROFILES"),
        "nakayama": ("knowledge.courses.nakayama", "NAKAYAMA_COURSE_PROFILES"),
        "chukyo": ("knowledge.courses.chukyo", "CHUKYO_COURSE_PROFILES"),
        "kyoto": ("knowledge.courses.kyoto", "KYOTO_COURSE_PROFILES"),
        "hanshin": ("knowledge.courses.hanshin", "HANSHIN_COURSE_PROFILES"),
        "kokura": ("knowledge.courses.kokura", "KOKURA_COURSE_PROFILES"),
    }

    RACECOURSE_ALIASES = {
        "sapporo": "札幌",
        "hakodate": "函館",
        "fukushima": "福島",
        "niigata": "新潟",
        "tokyo": "東京",
        "nakayama": "中山",
        "chukyo": "中京",
        "kyoto": "京都",
        "hanshin": "阪神",
        "kokura": "小倉",
    }

    SURFACE_ALIASES = {
        "turf": "芝",
        "dirt": "ダート",
    }

    PACE_ALIASES = {
        "slow": "スロー",
        "average": "平均",
        "middle": "ミドル",
        "medium": "平均",
        "fast": "ハイ",
        "high": "ハイ",
        "スロー": "スロー",
        "平均": "平均",
        "ミドル": "ミドル",
        "ハイ": "ハイ",
    }

    PACE_EQUIVALENTS = {
        "平均": ["平均", "ミドル"],
        "ミドル": ["ミドル", "平均"],
        "スロー": ["スロー"],
        "ハイ": ["ハイ"],
    }

    def evaluate(self, racecourse, surface, distance, pace=None):
        """指定条件に合うペース評価summaryを返します。"""

        course_info = self._normalize_racecourse(racecourse)
        surface_info = self._normalize_surface(surface)
        normalized_distance = self._normalize_distance(distance)
        normalized_pace = self._normalize_pace(pace)

        if normalized_distance is None:
            return self._not_found_result(
                racecourse,
                surface,
                distance,
                pace,
                "Course profile not found",
            )

        module = self._load_module(course_info["english"])
        profile = self._find_profile(module, course_info, surface_info, normalized_distance)

        if profile is None:
            return self._not_found_result(
                racecourse,
                surface,
                distance,
                pace,
                "Course profile not found",
            )

        source_name = self._make_source_name(
            course_info["english"],
            surface_info["english"],
            normalized_distance,
            normalized_pace,
        )
        pace_trend = self._find_pace_trend(
            module,
            surface_info,
            normalized_distance,
            normalized_pace,
        )
        base_modifiers = self._get_course_modifiers(module, profile, surface_info, normalized_distance)
        keyword_modifiers = self._filter_modifiers_by_trend(base_modifiers, pace_trend)
        score_modifiers = keyword_modifiers or base_modifiers

        if not score_modifiers and not pace_trend and not self._get_value(profile, ["pace_tendency"]):
            return self._not_found_result(
                racecourse,
                surface,
                distance,
                pace,
                "Pace profile not found",
            )

        engine = ScoreModifierEngine()
        engine.add_modifiers(
            source_name=source_name,
            source_type="pace",
            score_modifiers=score_modifiers,
            modifier_reasons=self._build_modifier_reasons(
                module,
                profile,
                surface_info,
                normalized_distance,
                score_modifiers,
                pace_trend,
            ),
            explain=self._build_explain(profile, pace_trend, normalized_pace),
        )

        return {
            "racecourse": course_info["english"],
            "surface": surface_info["english"],
            "distance": normalized_distance,
            "pace": normalized_pace,
            "matched": True,
            "matched_sources": [source_name],
            "summary": engine.get_summary(),
        }

    def _load_module(self, racecourse_english):
        module_info = self.COURSE_MODULES.get(racecourse_english)
        if module_info is None:
            return None

        try:
            return import_module(module_info[0])
        except Exception:
            return None

    def _load_profiles(self, module, racecourse_english):
        if module is None:
            return {}

        module_info = self.COURSE_MODULES.get(racecourse_english)
        if module_info is None:
            return {}

        profiles = getattr(module, module_info[1], None)
        return profiles if isinstance(profiles, dict) else {}

    def _find_profile(self, module, racecourse_info, surface_info, distance):
        profiles = self._load_profiles(module, racecourse_info["english"])
        if not profiles:
            return None

        racecourse_candidates = [
            racecourse_info["japanese"],
            racecourse_info["english"],
            racecourse_info["original"],
        ]
        surface_candidates = [
            surface_info["japanese"],
            surface_info["english"],
            surface_info["original"],
        ]

        for racecourse_name in racecourse_candidates:
            for surface_name in surface_candidates:
                key = (racecourse_name, surface_name, distance)
                if key in profiles:
                    return profiles[key]

        for key, profile in profiles.items():
            if not isinstance(key, tuple) or len(key) != 3:
                continue
            key_course, key_surface, key_distance = key
            if (
                key_distance == distance
                and key_course in racecourse_candidates
                and key_surface in surface_candidates
            ):
                return profile

        return None

    def _find_pace_trend(self, module, surface_info, distance, pace):
        trends = self._get_module_dict_by_suffix(module, "_PACE_TRENDS")
        if not trends:
            return None

        course_keys = [
            (surface_info["japanese"], distance),
            (surface_info["english"], distance),
            f"{surface_info['japanese']}{distance}",
            f"{surface_info['english']}{distance}",
        ]

        for key in course_keys:
            if key in trends:
                return self._select_pace_entry(trends.get(key), pace)

        return self._select_pace_entry(trends, pace)

    def _select_pace_entry(self, trend_data, pace):
        if not isinstance(trend_data, dict):
            return trend_data

        if pace is None:
            return trend_data

        for pace_key in self.PACE_EQUIVALENTS.get(pace, [pace]):
            if pace_key in trend_data:
                return trend_data[pace_key]

        return trend_data

    def _get_course_modifiers(self, module, profile, surface_info, distance):
        modifiers = self._get_value(profile, ["score_modifiers"])
        if isinstance(modifiers, dict) and modifiers:
            return dict(modifiers)

        reason_entries = self._get_reason_entries(module, surface_info, distance)
        extracted = {}
        for modifier, value in reason_entries.items():
            if isinstance(value, dict) and isinstance(value.get("score"), (int, float)):
                extracted[str(modifier)] = value["score"]
        return extracted

    def _filter_modifiers_by_trend(self, modifiers, trend):
        if not isinstance(modifiers, dict) or not modifiers:
            return {}

        keywords = self._extract_trend_keywords(trend)
        if not keywords:
            return {}

        filtered = {}
        for modifier, score in modifiers.items():
            modifier_text = str(modifier)
            if any(self._keyword_matches_modifier(keyword, modifier_text) for keyword in keywords):
                filtered[modifier] = score
        return filtered

    def _extract_trend_keywords(self, trend):
        if not isinstance(trend, dict):
            return []

        keywords = []
        for key in [
            "favorable_styles",
            "required_abilities",
            "有利脚質",
            "能力",
            "styles",
            "abilities",
        ]:
            value = trend.get(key)
            if isinstance(value, list):
                keywords.extend(str(item) for item in value)
            elif isinstance(value, str):
                keywords.append(value)

        return keywords

    def _keyword_matches_modifier(self, keyword, modifier):
        keyword_text = str(keyword)
        return keyword_text == modifier or keyword_text in modifier or modifier in keyword_text

    def _build_modifier_reasons(self, module, profile, surface_info, distance, modifiers, trend):
        reason_entries = self._get_reason_entries(module, surface_info, distance)
        trend_summary = self._get_trend_summary(trend)
        profile_pace_text = self._get_value(profile, ["pace_tendency"])
        reasons = {}

        for modifier in modifiers:
            reason = ""
            entry = reason_entries.get(modifier)
            if isinstance(entry, dict):
                reason = entry.get("reason", "")
            elif isinstance(entry, str):
                reason = entry

            if not reason:
                reason = trend_summary or profile_pace_text or "コース教科書のペース傾向に基づく補正"
            reasons[str(modifier)] = reason

        return reasons

    def _get_reason_entries(self, module, surface_info, distance):
        entries = self._get_module_dict_by_suffix(module, "_SCORE_MODIFIER_REASONS")
        if not entries:
            return {}

        keys = [
            (surface_info["japanese"], distance),
            (surface_info["english"], distance),
            f"{surface_info['japanese']}{distance}",
            f"{surface_info['english']}{distance}",
        ]

        for key in keys:
            if key in entries and isinstance(entries[key], dict):
                return entries[key]

        return {}

    def _build_explain(self, profile, trend, pace):
        parts = []
        trend_summary = self._get_trend_summary(trend)
        if trend_summary:
            parts.append(trend_summary)

        pace_tendency = self._get_value(profile, ["pace_tendency", "pace_profile"])
        if pace_tendency:
            parts.append(str(pace_tendency))

        closing_tendency = self._get_value(profile, ["closing_tendency", "race_shape", "running_shape"])
        if closing_tendency:
            parts.append(str(closing_tendency))

        course_shape = self._get_value(profile, ["course_shape"])
        if course_shape:
            parts.append(str(course_shape))

        prefix = f"{pace}想定: " if pace else ""
        return prefix + " / ".join(self._unique_texts(parts)) if parts else None

    def _get_trend_summary(self, trend):
        if isinstance(trend, dict):
            for name in ["summary", "explain", "Explain", "comment", "コメント"]:
                value = trend.get(name)
                if value:
                    return str(value)
        elif trend:
            return str(trend)
        return None

    def _get_module_dict_by_suffix(self, module, suffix):
        if module is None:
            return {}

        for name in dir(module):
            if not name.endswith(suffix):
                continue
            value = getattr(module, name, None)
            if isinstance(value, dict):
                return value
        return {}

    def _get_value(self, profile, names):
        for name in names:
            if isinstance(profile, dict) and name in profile:
                return profile.get(name)
            if hasattr(profile, name):
                return getattr(profile, name)
        return None

    def _normalize_racecourse(self, racecourse):
        original = str(racecourse).strip() if racecourse is not None else ""
        lower = original.lower()

        if lower in self.RACECOURSE_ALIASES:
            return {
                "original": original,
                "english": lower,
                "japanese": self.RACECOURSE_ALIASES[lower],
            }

        for english, japanese in self.RACECOURSE_ALIASES.items():
            if original == japanese:
                return {
                    "original": original,
                    "english": english,
                    "japanese": japanese,
                }

        return {
            "original": original,
            "english": lower,
            "japanese": original,
        }

    def _normalize_surface(self, surface):
        original = str(surface).strip() if surface is not None else ""
        lower = original.lower()

        if lower in self.SURFACE_ALIASES:
            return {
                "original": original,
                "english": lower,
                "japanese": self.SURFACE_ALIASES[lower],
            }

        for english, japanese in self.SURFACE_ALIASES.items():
            if original == japanese:
                return {
                    "original": original,
                    "english": english,
                    "japanese": japanese,
                }

        return {
            "original": original,
            "english": lower,
            "japanese": original,
        }

    def _normalize_distance(self, distance):
        try:
            return int(distance)
        except (TypeError, ValueError):
            return None

    def _normalize_pace(self, pace):
        if pace is None:
            return None

        text = str(pace).strip()
        key = text.lower() if self._is_ascii(text) else text
        return self.PACE_ALIASES.get(key, text)

    def _make_source_name(self, racecourse, surface, distance, pace):
        parts = [racecourse, surface, str(distance)]
        if pace:
            parts.append(str(pace))
        return "_".join(parts)

    def _not_found_result(self, racecourse, surface, distance, pace, warning):
        return {
            "racecourse": racecourse,
            "surface": surface,
            "distance": distance,
            "pace": pace,
            "matched": False,
            "matched_sources": [],
            "summary": self._empty_summary(),
            "warning": warning,
        }

    def _empty_summary(self):
        return {
            "total_score": 0,
            "modifiers": {},
            "reasons": [],
            "explains": [],
            "source_type_summary": {},
        }

    def _unique_texts(self, values):
        unique_values = []
        seen = set()
        for value in values:
            text = str(value)
            if text in seen:
                continue
            seen.add(text)
            unique_values.append(text)
        return unique_values

    def _is_ascii(self, value):
        try:
            value.encode("ascii")
        except UnicodeEncodeError:
            return False
        return True


if __name__ == "__main__":
    evaluator = PaceEvaluator()
    checks = [
        ("tokyo", "turf", 1600, "average"),
        ("tokyo", "turf", 1600, "ハイ"),
        ("hanshin", "turf", 2200, "slow"),
        ("tokyo", "turf", 9999, "average"),
    ]

    for racecourse, surface, distance, pace in checks:
        result = evaluator.evaluate(
            racecourse=racecourse,
            surface=surface,
            distance=distance,
            pace=pace,
        )
        print(
            {
                "input": (racecourse, surface, distance, pace),
                "matched": result["matched"],
                "matched_sources": result["matched_sources"],
                "summary_keys": list(result["summary"].keys()),
                "source_type_summary": result["summary"]["source_type_summary"],
            }
        )
