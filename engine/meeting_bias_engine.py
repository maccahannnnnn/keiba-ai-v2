"""Meeting-level bias scaffold for KeibaAI Ver0.94.

MeetingBias is intentionally separate from TrackBias.

MeetingBias describes longer-term meeting context:
- meeting stage, such as opening, middle, or closing week
- course rotation, such as A/B/C/D course changes
- turf wear and meeting progression
- meeting-level tendency hints

TrackBias remains responsible for same-day conditions such as front/closer
or inside/outside bias.  This engine does not score horses, change decisions,
or change the current evaluation scores.
"""


class MeetingBiasEngine:
    """Build a neutral meeting-bias structure without changing evaluation.

    This class is a stable API placeholder for future phases.  It accepts
    race-level context and optional knowledge data, then returns explainable
    meeting-bias metadata.  No score calculation is performed here.
    """

    DEFAULT_RESULT = {
        "meeting_stage": "unknown",
        "course_rotation": "unknown",
        "turf_wear": "unknown",
        "inside_bias": "unknown",
        "outside_bias": "unknown",
        "front_bias": "unknown",
        "closer_bias": "unknown",
        "speed_bias": "unknown",
        "stamina_bias": "unknown",
    }

    def analyze(self, race_context=None, meeting_knowledge=None):
        """Return meeting-bias metadata from supplied context and knowledge.

        Parameters
        ----------
        race_context:
            Optional dict containing racecourse, surface, distance, race_date,
            race_number, and other race metadata.
        meeting_knowledge:
            Optional dict loaded from knowledge/meeting_bias.  Ver0.94-1
            knowledge files are course-level templates, so this method keeps
            scoring disabled and converts only available text into explain data.

        Returns
        -------
        dict
            A stable, non-scoring result shape that can later be consumed by
            ExplainEngine, TrackBias, RaceShape, or Decision layers.
        """

        context = race_context if isinstance(race_context, dict) else {}
        knowledge = meeting_knowledge if isinstance(meeting_knowledge, dict) else {}

        meeting_bias = dict(self.DEFAULT_RESULT)
        for key in meeting_bias:
            value = knowledge.get(key, context.get(key))
            if value not in (None, ""):
                meeting_bias[key] = value

        surface = self._surface(context, knowledge)
        distance_category = self._distance_category(context, knowledge)
        stage, stage_warning = self._stage(context, knowledge)
        profile = self._profile(knowledge, surface, distance_category, stage)
        if stage != "unknown":
            meeting_bias["meeting_stage"] = stage
        if surface != "unknown":
            meeting_bias["surface"] = surface
        if distance_category != "unknown":
            meeting_bias["distance_category"] = distance_category
        if profile.get("turf_wear"):
            meeting_bias["turf_wear"] = profile.get("turf_wear")
        if profile.get("inside_outside_tendency"):
            tendency = profile.get("inside_outside_tendency")
            meeting_bias["inside_bias"] = "noted" if "inside" in str(tendency) else meeting_bias["inside_bias"]
            meeting_bias["outside_bias"] = "noted" if "outside" in str(tendency) else meeting_bias["outside_bias"]
        if profile.get("front_closer_tendency") or profile.get("running_style_tendency"):
            tendency = profile.get("front_closer_tendency") or profile.get("running_style_tendency")
            text = str(tendency)
            meeting_bias["front_bias"] = "noted" if "front" in text or "stalk" in text else meeting_bias["front_bias"]
            meeting_bias["closer_bias"] = "noted" if "closer" in text else meeting_bias["closer_bias"]

        warnings = []
        if not knowledge:
            warnings.append("meeting_bias_knowledge_not_loaded")
        if stage_warning:
            warnings.append(stage_warning)
        if context.get("surface") == "turf" and meeting_bias.get("turf_wear") == "unknown":
            warnings.append("turf_wear_unknown")

        return {
            "meeting_bias": meeting_bias,
            "meeting_bias_comment": self._comment(context, knowledge, meeting_bias, profile, warnings),
            "meeting_bias_factors": self._factors(meeting_bias, profile, knowledge),
            "meeting_bias_flags": self._flags(meeting_bias),
            "meeting_bias_warnings": warnings,
            "meeting_bias_source": knowledge.get("source", "not_connected"),
            "meeting_bias_ready": bool(knowledge),
            "selected_surface": surface,
            "selected_distance_category": distance_category,
            "selected_meeting_stage": stage,
            "score_impact": "none",
        }

    def _stage(self, context, knowledge):
        for source in (context, knowledge):
            value = source.get("meeting_stage") if isinstance(source, dict) else None
            if value not in (None, ""):
                text = str(value).strip().lower()
                if text in {"opening", "middle", "closing"}:
                    return text, ""
        return "middle", "meeting_stage_defaulted_to_middle"

    def _surface(self, context, knowledge):
        for source in (context, knowledge):
            value = source.get("surface") if isinstance(source, dict) else None
            text = str(value or "").strip().lower()
            if text in {"turf", "芝"}:
                return "turf"
            if text in {"dirt", "ダート", "ダ"}:
                return "dirt"
        return "unknown"

    def _distance_category(self, context, knowledge):
        value = context.get("distance")
        if value in (None, "") and isinstance(knowledge, dict):
            value = knowledge.get("distance")
        try:
            distance = int(float(str(value).strip().replace("m", "")))
        except (TypeError, ValueError):
            return "unknown"
        if distance <= 1400:
            return "sprint"
        if distance <= 1600:
            return "mile"
        if distance <= 2200:
            return "middle"
        return "long"

    def _profile(self, knowledge, surface, distance_category, stage):
        if not isinstance(knowledge, dict):
            return {}
        surface_profiles = knowledge.get("surface_profiles")
        if isinstance(surface_profiles, dict):
            surface_data = surface_profiles.get(surface)
            if isinstance(surface_data, dict):
                distance_data = surface_data.get(distance_category)
                if isinstance(distance_data, dict):
                    profile = distance_data.get(stage)
                    if isinstance(profile, dict):
                        return profile

        legacy_profile = knowledge.get(stage)
        return legacy_profile if isinstance(legacy_profile, dict) else {}

    def _comment(self, context, knowledge, meeting_bias, profile, warnings):
        racecourse = context.get("racecourse") or "unknown_course"
        surface = context.get("surface") or "unknown_surface"
        stage = meeting_bias.get("meeting_stage", "unknown")
        rotation = meeting_bias.get("course_rotation", "unknown")
        turf_wear = meeting_bias.get("turf_wear", "unknown")

        if not knowledge:
            return (
                f"{racecourse} {surface}: MeetingBias is not active yet. "
                f"stage={stage}, course_rotation={rotation}, turf_wear={turf_wear}."
            )
        explain = profile.get("explain")
        features = self._list(profile.get("features"))[:2]
        cautions = self._list(profile.get("cautions"))[:1]
        if explain:
            parts = [str(explain)]
            parts.extend(str(feature) for feature in features)
            parts.extend(str(caution) for caution in cautions)
            return " / ".join(parts)
        if features:
            parts = [str(feature) for feature in features]
            parts.extend(str(caution) for caution in cautions)
            return " / ".join(parts)
        notes = self._list(knowledge.get("notes"))[:2]
        if notes:
            return " / ".join(str(note) for note in notes)
        if warnings:
            return (
                f"{racecourse} {surface}: MeetingBias knowledge loaded. "
                f"stage={stage}, course_rotation={rotation}, turf_wear={turf_wear}."
            )
        return (
            f"{racecourse} {surface}: meeting stage {stage}, "
            f"course rotation {rotation}, turf wear {turf_wear}."
        )

    def _factors(self, meeting_bias, profile=None, knowledge=None):
        factors = []
        for key, value in meeting_bias.items():
            if value not in (None, "", "unknown"):
                factors.append(f"{key}:{value}")
        profile = profile if isinstance(profile, dict) else {}
        for key in [
            "inside_outside_tendency",
            "front_closer_tendency",
            "running_style_tendency",
            "turf_condition",
        ]:
            value = profile.get(key)
            if value not in (None, ""):
                factors.append(f"{key}:{value}")
        knowledge = knowledge if isinstance(knowledge, dict) else {}
        rotation = knowledge.get("course_rotation")
        if isinstance(rotation, dict) and rotation:
            factors.append("course_rotation_template_available")
        return factors

    def _flags(self, meeting_bias):
        return {
            "opening_stage": meeting_bias.get("meeting_stage") == "opening",
            "middle_stage": meeting_bias.get("meeting_stage") == "middle",
            "closing_stage": meeting_bias.get("meeting_stage") == "closing",
            "course_rotation_known": meeting_bias.get("course_rotation") != "unknown",
            "turf_wear_known": meeting_bias.get("turf_wear") != "unknown",
            "surface_known": meeting_bias.get("surface") != "unknown",
            "distance_category_known": meeting_bias.get("distance_category") != "unknown",
        }

    def _list(self, value):
        return value if isinstance(value, list) else []


if __name__ == "__main__":
    engine = MeetingBiasEngine()
    print(engine.analyze({"racecourse": "hakodate", "surface": "turf"}))
