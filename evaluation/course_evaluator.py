"""Course Knowledge を ScoreModifierEngine に渡すための独立Evaluatorです。

このモジュールはまだ Analyzer や main.py には接続しません。
既存の Course Knowledge を読み取り、単体でコース補正の summary を返します。
"""

from importlib import import_module

from evaluation.score_modifier_engine import ScoreModifierEngine


class CourseEvaluator:
    """競馬場・馬場種別・距離から CourseProfile を評価するクラスです。"""

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

    def evaluate(self, racecourse, surface, distance):
        """指定条件に一致する CourseProfile を評価し、summary を返します。"""

        normalized_course = self._normalize_racecourse(racecourse)
        normalized_surface = self._normalize_surface(surface)
        normalized_distance = self._normalize_distance(distance)
        source_name = None

        if normalized_distance is None:
            return self._not_found_result(racecourse, surface, distance)

        profile = self._find_profile(
            normalized_course,
            normalized_surface,
            normalized_distance,
        )

        if profile is None:
            return self._not_found_result(racecourse, surface, distance)

        source_name = self._make_source_name(
            normalized_course["english"],
            normalized_surface["english"],
            normalized_distance,
        )

        engine = ScoreModifierEngine()
        engine.add_modifiers(
            source_name=source_name,
            source_type="course",
            score_modifiers=self._get_value(profile, ["score_modifiers"]),
            modifier_reasons=self._get_value(
                profile,
                ["modifier_reasons", "modifier_reason"],
            ),
            explain=self._get_explain(profile),
        )

        return {
            "racecourse": normalized_course["english"],
            "surface": normalized_surface["english"],
            "distance": normalized_distance,
            "matched": True,
            "source_name": source_name,
            "summary": engine.get_summary(),
        }

    def _find_profile(self, racecourse_info, surface_info, distance):
        """既存Knowledge Baseの形式に合わせて CourseProfile を探します。"""

        profiles = self._load_profiles(racecourse_info["english"])
        if not isinstance(profiles, dict):
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

    def _load_profiles(self, racecourse_english):
        """競馬場別の course profile 辞書を安全に読み込みます。"""

        module_info = self.COURSE_MODULES.get(racecourse_english)
        if module_info is None:
            return {}

        module_name, constant_name = module_info
        try:
            module = import_module(module_name)
        except Exception:
            return {}

        profiles = getattr(module, constant_name, None)
        return profiles if isinstance(profiles, dict) else {}

    def _get_value(self, profile, names):
        """dict / dataclass / object のどれでも値を取得できるようにします。"""

        for name in names:
            if isinstance(profile, dict) and name in profile:
                return profile.get(name)
            if hasattr(profile, name):
                return getattr(profile, name)
        return None

    def _get_explain(self, profile):
        """Explain が無いCourseProfileでも、概要を説明文として利用します。"""

        explain = self._get_value(profile, ["explain", "Explain"])
        if explain:
            return explain

        course_shape = self._get_value(profile, ["course_shape"])
        if course_shape and course_shape != "不明":
            return course_shape

        if hasattr(profile, "summary"):
            try:
                return profile.summary()
            except Exception:
                return None

        features = self._get_value(profile, ["features"])
        if isinstance(features, list):
            return " / ".join(str(item) for item in features)
        return None

    def _normalize_racecourse(self, racecourse):
        original = str(racecourse) if racecourse is not None else ""
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
        original = str(surface) if surface is not None else ""
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

    def _make_source_name(self, racecourse, surface, distance):
        return f"{racecourse}_{surface}_{distance}"

    def _empty_summary(self):
        return {
            "total_score": 0,
            "modifiers": {},
            "reasons": [],
            "explains": [],
            "source_type_summary": {},
        }

    def _not_found_result(self, racecourse, surface, distance):
        return {
            "racecourse": racecourse,
            "surface": surface,
            "distance": distance,
            "matched": False,
            "source_name": None,
            "summary": self._empty_summary(),
            "warning": "Course profile not found",
        }


if __name__ == "__main__":
    evaluator = CourseEvaluator()
    checks = [
        ("tokyo", "turf", 1600),
        ("nakayama", "dirt", 1800),
        ("tokyo", "turf", 9999),
    ]

    for racecourse, surface, distance in checks:
        result = evaluator.evaluate(racecourse, surface, distance)
        print(
            {
                "input": (racecourse, surface, distance),
                "matched": result["matched"],
                "source_name": result["source_name"],
                "summary_keys": list(result["summary"].keys()),
                "source_type_summary": result["summary"]["source_type_summary"],
            }
        )
