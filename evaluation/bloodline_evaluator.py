"""Bloodline Knowledge を ScoreModifierEngine に渡すための独立Evaluatorです。

このモジュールはまだ Analyzer や main.py には接続しません。
既存の血統教科書を読み取り、単体で血統補正の summary を返します。
"""

from evaluation.score_modifier_engine import ScoreModifierEngine


class BloodlineEvaluator:
    """父・母父・ニックスから血統Profileを評価するクラスです。"""

    def evaluate(self, sire_name=None, broodmare_sire_name=None):
        """取得できる血統Profileだけを評価し、summary を返します。"""

        sire = self._normalize_name(sire_name)
        broodmare_sire = self._normalize_name(broodmare_sire_name)
        engine = ScoreModifierEngine()
        matched_sources = []

        sire_profile = self._find_sire_profile(sire)
        if sire_profile is not None:
            source_name = f"sire_{sire}"
            self._add_profile_to_engine(engine, source_name, sire_profile)
            matched_sources.append(source_name)

        broodmare_profile = self._find_broodmare_sire_profile(broodmare_sire)
        if broodmare_profile is not None:
            source_name = f"broodmare_sire_{broodmare_sire}"
            self._add_profile_to_engine(engine, source_name, broodmare_profile)
            matched_sources.append(source_name)

        nick_profile = self._find_nick_profile(sire, broodmare_sire)
        if nick_profile is not None:
            source_name = f"nick_{sire}_x_{broodmare_sire}"
            self._add_profile_to_engine(engine, source_name, nick_profile)
            matched_sources.append(source_name)

        matched = bool(matched_sources)
        result = {
            "sire_name": sire if sire is not None else "不明",
            "broodmare_sire_name": broodmare_sire if broodmare_sire is not None else "不明",
            "matched": matched,
            "matched_sources": matched_sources,
            "summary": engine.get_summary() if matched else self._empty_summary(),
        }

        if not matched:
            result["warning"] = "Bloodline profile not found"

        return result

    def _add_profile_to_engine(self, engine, source_name, profile):
        """Profileから補正情報を取り出して ScoreModifierEngine に渡します。"""

        engine.add_modifiers(
            source_name=source_name,
            source_type="bloodline",
            score_modifiers=self._get_value(profile, ["score_modifiers"]),
            modifier_reasons=self._get_value(
                profile,
                ["modifier_reasons", "modifier_reason"],
            ),
            explain=self._get_value(profile, ["explain", "Explain"]),
        )

    def _find_sire_profile(self, sire_name):
        """父名から SIRE_PROFILES を探します。"""

        if not sire_name:
            return None

        try:
            from knowledge.bloodlines.sire_profiles import SIRE_PROFILES
        except Exception:
            return None

        return self._find_by_name(SIRE_PROFILES, sire_name)

    def _find_broodmare_sire_profile(self, broodmare_sire_name):
        """母父名から BROODMARE_SIRE_PROFILES を探します。"""

        if not broodmare_sire_name:
            return None

        try:
            from knowledge.bloodlines.broodmare import BROODMARE_SIRE_PROFILES
        except Exception:
            return None

        return self._find_by_name(BROODMARE_SIRE_PROFILES, broodmare_sire_name)

    def _find_nick_profile(self, sire_name, broodmare_sire_name):
        """父 x 母父の組み合わせからニックスProfileを探します。"""

        if not sire_name or not broodmare_sire_name:
            return None

        try:
            from knowledge.bloodlines.nicks import NICKS_PROFILES
        except Exception:
            try:
                from knowledge.bloodlines.nicks import NICKS as NICKS_PROFILES
            except Exception:
                return None

        if not isinstance(NICKS_PROFILES, dict):
            return None

        direct_key = (sire_name, broodmare_sire_name)
        if direct_key in NICKS_PROFILES:
            return NICKS_PROFILES[direct_key]

        normalized_sire = self._compact_name(sire_name)
        normalized_broodmare = self._compact_name(broodmare_sire_name)
        for key, profile in NICKS_PROFILES.items():
            if not isinstance(key, tuple) or len(key) != 2:
                continue
            key_sire, key_broodmare = key
            if (
                self._compact_name(key_sire) == normalized_sire
                and self._compact_name(key_broodmare) == normalized_broodmare
            ):
                return profile

        return None

    def _find_by_name(self, profiles, name):
        """完全一致を優先し、空白差などは吸収してProfileを探します。"""

        if not isinstance(profiles, dict):
            return None

        if name in profiles:
            return profiles[name]

        normalized_name = self._compact_name(name)
        for key, profile in profiles.items():
            if self._compact_name(key) == normalized_name:
                return profile

        return None

    def _get_value(self, profile, names):
        """dict / dataclass / object のどれでも値を取得できるようにします。"""

        for name in names:
            if isinstance(profile, dict) and name in profile:
                return profile.get(name)
            if hasattr(profile, name):
                return getattr(profile, name)
        return None

    def _normalize_name(self, value):
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _compact_name(self, value):
        if value is None:
            return ""
        return str(value).replace(" ", "").replace("　", "").strip()

    def _empty_summary(self):
        return {
            "total_score": 0,
            "modifiers": {},
            "reasons": [],
            "explains": [],
            "source_type_summary": {},
        }


if __name__ == "__main__":
    evaluator = BloodlineEvaluator()
    checks = [
        ("キズナ", None),
        ("キズナ", "キングカメハメハ"),
        ("存在しない父", None),
    ]

    for sire_name, broodmare_sire_name in checks:
        result = evaluator.evaluate(
            sire_name=sire_name,
            broodmare_sire_name=broodmare_sire_name,
        )
        print(
            {
                "input": (sire_name, broodmare_sire_name),
                "matched": result["matched"],
                "matched_sources": result["matched_sources"],
                "summary_keys": list(result["summary"].keys()),
                "source_type_summary": result["summary"]["source_type_summary"],
            }
        )
