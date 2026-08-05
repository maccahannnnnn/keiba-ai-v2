"""Break BloodlineEvaluator root causes into explainable bloodline factors."""

from collections import Counter


class BloodlineRootCauseEngine:
    """Classify existing bloodline output without changing evaluation logic."""

    ROOT_VERSION = "phase_e_step3_v1"
    BLOODLINE_TARGET = "BloodlineEvaluator"

    CATEGORY_KEYWORDS = [
        ("Surface", ("芝", "ダート", "turf", "dirt")),
        ("Distance", ("短距離", "スプリント", "マイル", "中距離", "長距離", "sprint", "mile", "middle", "long", "距離", "1700", "1800", "2000")),
        ("TrackCondition", ("馬場", "道悪", "重", "不良", "wet", "heavy", "soft")),
        ("Course", ("コース", "小回り", "直線", "坂", "course", "turn")),
        ("RunningStyle", ("逃げ", "先行", "差し", "追込", "脚質", "running", "style")),
        ("Growth", ("成長", "晩成", "早熟", "growth")),
    ]

    CATEGORY_KEYWORDS = [
        ("Surface", ("turf", "dirt", "surface")),
        ("Distance", ("sprint", "mile", "middle", "long", "distance", "stamina", "1700", "1800", "2000")),
        ("TrackCondition", ("wet", "heavy", "soft", "track_condition")),
        ("Course", ("course", "turn", "hill")),
        ("RunningStyle", ("running", "style", "front", "closer", "escape")),
        ("Growth", ("growth",)),
    ]

    def analyze(self, horse=None):
        item = horse if isinstance(horse, dict) else {}
        relevant = self._is_bloodline_relevant(item)
        matched = self._bloodline_matches(item)
        causes = self._causes_from_matches(item, matched)
        if not causes:
            causes = [self._knowledge_missing_cause(item)]
        causes = self._rank_causes(causes)
        primary = causes[0] if causes else self._unknown_cause("no bloodline root cause")
        secondary = causes[1:4]
        return {
            "bloodline_root_version": self.ROOT_VERSION,
            "bloodline_root_relevant": relevant,
            "bloodline_score": self._to_float(item.get("bloodline_score") or item.get("blood_score")),
            "sire": item.get("sire") or item.get("sire_name"),
            "broodmare_sire": item.get("broodmare_sire") or item.get("broodmare_sire_name"),
            "matched_sources": self._matched_sources(matched),
            "knowledge_paths": self._knowledge_paths(matched),
            "knowledge_classified": bool(matched),
            "bloodline_root_causes": causes,
            "bloodline_primary_factor": primary.get("category", "UNKNOWN"),
            "bloodline_secondary_factors": [row.get("category") for row in secondary],
            "bloodline_unknown": primary.get("category") == "UNKNOWN",
        }

    def analyze_many(self, horse_results=None):
        rows = horse_results if isinstance(horse_results, list) else []
        results = []
        for row in rows:
            if isinstance(row, dict):
                result = self.analyze(row)
                row["bloodline_root_cause"] = result
                results.append(result)
            else:
                results.append(
                    {
                        "bloodline_root_version": self.ROOT_VERSION,
                        "bloodline_root_relevant": False,
                        "bloodline_root_causes": [self._unknown_cause("non dict row")],
                        "bloodline_primary_factor": "UNKNOWN",
                        "bloodline_secondary_factors": [],
                        "bloodline_unknown": True,
                    }
                )
        return {
            "bloodline_root_version": self.ROOT_VERSION,
            "horse_bloodline_roots": results,
            "summary": self.summary(results),
            "warnings": [],
        }

    def summary(self, results):
        rows = [row for row in results if isinstance(row, dict)]
        relevant = [row for row in rows if row.get("bloodline_root_relevant")]
        category_counter = Counter(row.get("bloodline_primary_factor") or "UNKNOWN" for row in relevant)
        source_counter = Counter()
        knowledge_missing = 0
        unknown = 0
        classified = 0
        for row in relevant:
            if row.get("knowledge_classified"):
                classified += 1
            for source in row.get("matched_sources") or []:
                source_counter[source] += 1
            if row.get("bloodline_primary_factor") == "KnowledgeMissing":
                knowledge_missing += 1
            if row.get("bloodline_unknown"):
                unknown += 1
        return {
            "bloodline_root_generated": len(rows),
            "bloodline_root_relevant_count": len(relevant),
            "category_counts": dict(category_counter.most_common()),
            "source_counts": dict(source_counter.most_common()),
            "knowledge_classified_count": classified,
            "knowledge_missing_count": knowledge_missing,
            "unknown_count": unknown,
        }

    def _is_bloodline_relevant(self, item):
        root = item.get("decision_root_cause") if isinstance(item.get("decision_root_cause"), dict) else {}
        attribution = item.get("decision_attribution") if isinstance(item.get("decision_attribution"), dict) else {}
        decision = str(item.get("decision") or "").upper()
        root_primary = root.get("root_primary_candidate") == self.BLOODLINE_TARGET
        decision_gate_root = bool(root.get("decision_primary_was_gate")) and root_primary
        buy_supporter_root = decision == "BUY" and (
            root_primary or self._detail_target(attribution.get("primary_supporter")) == self.BLOODLINE_TARGET
        )
        return decision_gate_root or buy_supporter_root

    def _detail_target(self, detail):
        return detail.get("target") if isinstance(detail, dict) else None

    def _bloodline_matches(self, item):
        matches = []
        for result in item.get("matched_results") or []:
            if not isinstance(result, dict):
                continue
            summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
            source_summary = summary.get("source_type_summary") if isinstance(summary.get("source_type_summary"), dict) else {}
            source_name = str(result.get("source_name") or "")
            if (
                "bloodline" in source_summary
                or source_name.startswith(("sire_", "broodmare_sire_", "nick_"))
            ):
                matches.append(result)
        return matches

    def _causes_from_matches(self, item, matches):
        causes = []
        score = self._to_float(item.get("bloodline_score") or item.get("blood_score"))
        base_effect = self._base_effect(score)
        for match in matches:
            sources = match.get("matched_sources") or []
            summary = match.get("summary") if isinstance(match.get("summary"), dict) else {}
            reasons = summary.get("reasons") if isinstance(summary.get("reasons"), list) else []
            explains = summary.get("explains") if isinstance(summary.get("explains"), list) else []
            if not reasons and not explains:
                category = self._source_category(sources)
                causes.append(self._cause(category, ", ".join(sources), base_effect, sources, "matched bloodline source"))
                continue
            for reason in reasons:
                if not isinstance(reason, dict):
                    continue
                text = " ".join(str(reason.get(key) or "") for key in ["modifier", "reason", "source"])
                category = self._category_from_text(text) or self._source_category([reason.get("source")] + sources)
                detail = str(reason.get("modifier") or reason.get("reason") or reason.get("source") or "")
                effect = self._to_float(reason.get("score"))
                if effect is None:
                    effect = base_effect
                if score is not None and score < 20:
                    effect = -abs(effect)
                causes.append(
                    self._cause(
                        category,
                        detail,
                        effect,
                        [str(reason.get("source") or source) for source in sources[:1] or [reason.get("source")]],
                        str(reason.get("reason") or "bloodline modifier contributed to root cause"),
                    )
                )
            for explain in explains:
                if not isinstance(explain, dict):
                    continue
                text = str(explain.get("explain") or "")
                category = self._category_from_text(text) or self._source_category(sources)
                causes.append(self._cause(category, text[:60], base_effect, sources, text[:100]))
        merged = self._merge_causes(causes)
        if not merged and matches:
            sources = self._matched_sources(matches)
            merged = [self._cause(self._source_category(sources), ", ".join(sources), base_effect, sources, "matched bloodline source")]
        return merged

    def _merge_causes(self, causes):
        buckets = {}
        for cause in causes:
            category = cause.get("category") or "UNKNOWN"
            item = buckets.setdefault(
                category,
                {
                    "category": category,
                    "detail": [],
                    "effect": 0.0,
                    "importance": 0.0,
                    "confidence": "LOW",
                    "knowledge_paths": [],
                    "reason": [],
                    "rank": None,
                },
            )
            item["effect"] += float(cause.get("effect") or 0)
            item["importance"] = min(1.0, item["importance"] + float(cause.get("importance") or 0) * 0.55)
            item["detail"].extend(self._as_list(cause.get("detail")))
            item["knowledge_paths"].extend(self._as_list(cause.get("knowledge_paths")))
            item["reason"].extend(self._as_list(cause.get("reason")))
            if cause.get("confidence") == "HIGH" or item["importance"] >= 0.65:
                item["confidence"] = "HIGH"
            elif cause.get("confidence") == "MEDIUM" and item["confidence"] != "HIGH":
                item["confidence"] = "MEDIUM"
        result = []
        for item in buckets.values():
            item["detail"] = " / ".join(self._unique(item["detail"])[:5])
            item["knowledge_paths"] = self._unique(item["knowledge_paths"])[:5]
            item["reason"] = " / ".join(self._unique(item["reason"])[:3])
            item["effect"] = round(item["effect"], 3)
            item["importance"] = round(item["importance"], 3)
            result.append(item)
        return result

    def _cause(self, category, detail, effect, sources, reason):
        category = category or "UNKNOWN"
        effect = self._to_float(effect)
        if effect is None:
            effect = 0.0
        importance = min(1.0, 0.28 + abs(effect) / 12.0)
        return {
            "category": category,
            "detail": detail or category,
            "effect": round(effect, 3),
            "importance": round(importance, 3),
            "confidence": "HIGH" if importance >= 0.72 else "MEDIUM" if importance >= 0.45 else "LOW",
            "knowledge_paths": self._paths_from_sources(sources),
            "reason": reason or "bloodline root cause",
            "rank": None,
        }

    def _knowledge_missing_cause(self, item):
        sire = item.get("sire") or item.get("sire_name") or "unknown_sire"
        broodmare = item.get("broodmare_sire") or item.get("broodmare_sire_name") or "unknown_broodmare_sire"
        category = "KnowledgeMissing"
        if not sire or sire == "unknown_sire":
            detail = "sire profile missing"
        elif not broodmare or broodmare == "unknown_broodmare_sire":
            detail = "broodmare sire profile missing"
        else:
            detail = f"profile missing or insufficient: {sire} / {broodmare}"
        return {
            "category": category,
            "detail": detail,
            "effect": -1.0,
            "importance": 0.82,
            "confidence": "HIGH",
            "knowledge_paths": [
                f"knowledge/bloodlines/sire_profiles.py::{sire}",
                f"knowledge/bloodlines/broodmare.py::{broodmare}",
            ],
            "reason": "Bloodline profile not found or did not provide enough support",
            "rank": 1,
        }

    def _unknown_cause(self, reason):
        return {
            "category": "UNKNOWN",
            "detail": reason,
            "effect": 0,
            "importance": 0,
            "confidence": "LOW",
            "knowledge_paths": [],
            "reason": reason,
            "rank": 1,
        }

    def _rank_causes(self, causes):
        rows = [row for row in causes if isinstance(row, dict)]
        rows.sort(key=lambda row: (-float(row.get("importance") or 0), str(row.get("category") or "")))
        for index, row in enumerate(rows, start=1):
            row["rank"] = index
        return rows

    def _category_from_text(self, text):
        source = str(text or "").lower()
        for category, keywords in self.CATEGORY_KEYWORDS:
            if any(str(keyword).lower() in source for keyword in keywords):
                return category
        return None

    def _source_category(self, sources):
        text = " ".join(str(source or "") for source in sources)
        if "broodmare_sire_" in text:
            return "DamSire"
        if "nick_" in text:
            return "Nick"
        if "sire_" in text:
            return "Sire"
        return "KnowledgeMissing"

    def _matched_sources(self, matches):
        sources = []
        for match in matches:
            sources.extend(str(source) for source in match.get("matched_sources") or [])
            source_name = match.get("source_name")
            if source_name:
                sources.append(str(source_name))
        return self._unique(sources)

    def _knowledge_paths(self, matches):
        return self._paths_from_sources(self._matched_sources(matches))

    def _paths_from_sources(self, sources):
        paths = []
        for source in sources or []:
            text = str(source or "")
            if text.startswith("sire_"):
                paths.append(f"knowledge/bloodlines/sire_profiles.py::{text[5:]}")
            elif text.startswith("broodmare_sire_"):
                paths.append(f"knowledge/bloodlines/broodmare.py::{text[16:]}")
            elif text.startswith("nick_"):
                paths.append(f"knowledge/bloodlines/nicks.py::{text[5:]}")
            elif text:
                paths.append(f"knowledge/bloodlines::{text}")
        return self._unique(paths)

    def _base_effect(self, score):
        if score is None:
            return -1.0
        return round((float(score) - 20.0) / 5.0, 3)

    def _as_list(self, value):
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if item not in (None, "")]
        return [str(value)]

    def _unique(self, values):
        result = []
        seen = set()
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    def _to_float(self, value):
        if isinstance(value, bool) or value in (None, ""):
            return None
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return None
