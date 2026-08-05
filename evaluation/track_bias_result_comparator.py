"""Compare manual TrackBias trial outputs against official result rows.

This module only compares already produced prediction outputs with imported
race results.  It does not score, re-score, learn, or mutate evaluator output.
"""


class TrackBiasResultComparator:
    """Create TrackBias comparison summaries from neutral and bias runs."""

    FORWARD_THRESHOLD = 4
    CLOSER_THRESHOLD = 5

    def compare(
        self,
        race_id=None,
        baseline_result=None,
        bias_results=None,
        official_results=None,
    ):
        """Return a comparison result without changing any inputs."""

        baseline = baseline_result if isinstance(baseline_result, dict) else {}
        bias_map = bias_results if isinstance(bias_results, dict) else {}
        official = official_results if isinstance(official_results, dict) else {}
        rows = self._result_rows(official)
        resolved_race_id = race_id or official.get("race_id") or baseline.get("race_id")
        warnings = []
        if not resolved_race_id:
            warnings.append("race_id missing; fallback matching may be ambiguous.")

        baseline_horses = self._horse_map(baseline)
        result_map = self._official_map(rows)
        unmatched_results = []
        for row in rows:
            if not self._match_horse(row, baseline_horses, resolved_race_id):
                unmatched_results.append(row)

        all_comparisons = []
        bias_summaries = {}
        for bias_name, bias_result in bias_map.items():
            comparisons, unmatched_predictions = self._compare_bias(
                resolved_race_id,
                str(bias_name),
                baseline_horses,
                bias_result if isinstance(bias_result, dict) else {},
                result_map,
            )
            all_comparisons.extend(comparisons)
            bias_summaries[str(bias_name)] = self._bias_summary(comparisons, rows)
            if unmatched_predictions:
                warnings.append(
                    f"{bias_name}: unmatched predictions {len(unmatched_predictions)}"
                )

        buy_promotion_diagnostics = self._buy_promotion_diagnostics(all_comparisons)
        promotion_summary = self._promotion_summary(buy_promotion_diagnostics)
        race_decision_promotion_diagnostics = self._race_decision_promotion_diagnostics(
            baseline,
            bias_map,
            buy_promotion_diagnostics,
        )
        summary = self._race_summary(rows, all_comparisons)
        summary.update(promotion_summary)

        return {
            "race_id": resolved_race_id,
            "summary": summary,
            "bias_summaries": bias_summaries,
            "horse_comparisons": all_comparisons,
            "buy_promotion_diagnostics": buy_promotion_diagnostics,
            "race_decision_promotion_diagnostics": race_decision_promotion_diagnostics,
            "track_bias_sensitive_buy_count": promotion_summary["track_bias_sensitive_buy_count"],
            "track_bias_only_buy_count": promotion_summary["track_bias_only_buy_count"],
            "rank_unchanged_buy_count": promotion_summary["rank_unchanged_buy_count"],
            "low_rank_promoted_buy_count": promotion_summary["low_rank_promoted_buy_count"],
            "effective_adjustment_candidates": self._effective_candidates(all_comparisons),
            "over_adjustment_candidates": self._over_candidates(all_comparisons),
            "unmatched_predictions": self._unique_unmatched(all_comparisons),
            "unmatched_results": unmatched_results,
            "warnings": warnings,
        }

    def format_report(self, comparison_result):
        """Create a compact human-readable comparison report."""

        data = comparison_result if isinstance(comparison_result, dict) else {}
        lines = [
            "====================",
            "TrackBias Result Comparison",
            "====================",
            f"RaceID: {data.get('race_id') or '-'}",
        ]
        summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
        for key in [
            "starter_count",
            "matched_result_count",
            "unmatched_result_count",
            "actual_top3_count",
            "actual_top3_average_fourth_corner",
            "actual_top3_inner_count",
            "actual_top3_outer_count",
        ]:
            lines.append(f"{key}: {summary.get(key)}")

        lines.append("")
        lines.append("Bias Summaries")
        bias_summaries = data.get("bias_summaries")
        if isinstance(bias_summaries, dict):
            for bias_name, item in bias_summaries.items():
                if not isinstance(item, dict):
                    item = {}
                lines.append(
                    f"- {bias_name}: new_buy={item.get('new_buy_count')}, "
                    f"top3_in={item.get('top3_enter_count')}, "
                    f"avg_rank_diff={item.get('average_rank_diff')}, "
                    f"promoted_buy={item.get('promoted_buy_count')}, "
                    f"rank_unchanged_buy={item.get('rank_unchanged_buy_count')}, "
                    f"low_rank_promoted_buy={item.get('low_rank_promoted_buy_count')}"
                )

        lines.append("")
        lines.append("Promotion Diagnostics")
        lines.append(
            f"track_bias_sensitive_buy_count: {data.get('track_bias_sensitive_buy_count')}"
        )
        lines.append(f"track_bias_only_buy_count: {data.get('track_bias_only_buy_count')}")
        lines.append(f"rank_unchanged_buy_count: {data.get('rank_unchanged_buy_count')}")
        lines.append(f"low_rank_promoted_buy_count: {data.get('low_rank_promoted_buy_count')}")
        race_diag = data.get("race_decision_promotion_diagnostics")
        if isinstance(race_diag, dict):
            lines.append(
                f"RaceDecision baseline: {race_diag.get('baseline_race_decision')}"
            )
            bias_items = race_diag.get("bias_results")
            if isinstance(bias_items, dict):
                for bias_name, item in bias_items.items():
                    if not isinstance(item, dict):
                        item = {}
                    lines.append(
                        f"- {bias_name}: decision={item.get('race_decision')}, "
                        f"promoted={item.get('promoted')}, "
                        f"types={self._join(item.get('promotion_type'))}"
                    )

        lines.append("")
        lines.append("Over Adjustment Candidates")
        for row in self._list(data.get("over_adjustment_candidates")):
            lines.append(
                f"- {row.get('bias_name')} {row.get('horse_name')}: "
                f"score={row.get('track_bias_score')}, finish={row.get('finish_position')}, "
                f"rank_diff={row.get('rank_diff')}, new_buy={row.get('new_buy')}"
            )
        if not self._list(data.get("over_adjustment_candidates")):
            lines.append("- none")

        lines.append("")
        lines.append("Warnings")
        for warning in self._list(data.get("warnings")):
            lines.append(f"- {warning}")
        if not self._list(data.get("warnings")):
            lines.append("- none")
        return "\n".join(lines)

    def _compare_bias(self, race_id, bias_name, baseline_horses, bias_result, result_map):
        bias_horses = self._horse_map(bias_result)
        comparisons = []
        unmatched = []
        seen = set()
        for bias_horse in bias_horses.values():
            identity = id(bias_horse)
            if identity in seen:
                continue
            seen.add(identity)
            base_horse = self._match_horse(bias_horse, baseline_horses, race_id)
            official = self._match_horse(bias_horse, result_map, race_id)
            if base_horse is None or official is None:
                unmatched.append(bias_horse)
                continue
            comparisons.append(
                self._horse_comparison(race_id, bias_name, base_horse, bias_horse, official)
            )
        return comparisons, unmatched

    def _horse_comparison(self, race_id, bias_name, baseline, bias, official):
        baseline_rank = self._rank(baseline)
        bias_rank = self._rank(bias)
        baseline_score = self._score(baseline)
        bias_score = self._score(bias)
        finish_position = self._to_int(official.get("finish_position"))
        baseline_decision = baseline.get("decision")
        bias_decision = bias.get("decision")
        weighted_track_bias_score = self._weighted_track_bias_score(bias)
        baseline_decision_score = self._optional_number(baseline.get("decision_score"))
        bias_decision_score = self._optional_number(bias.get("decision_score"))
        baseline_consistency_score = self._optional_number(baseline.get("consistency_score"))
        bias_consistency_score = self._optional_number(bias.get("consistency_score"))
        baseline_risks = self._risk_items(baseline)
        bias_risks = self._risk_items(bias)
        baseline_conflicts = self._list(baseline.get("conflict_factors"))
        bias_conflicts = self._list(bias.get("conflict_factors"))
        new_buy = baseline_decision != "BUY" and bias_decision == "BUY"
        baseline_final = self._optional_number(baseline.get("final_score"))
        bias_final = self._optional_number(bias.get("final_score"))
        baseline_adjusted = self._optional_number(baseline.get("adjusted_score"))
        bias_adjusted = self._optional_number(bias.get("adjusted_score"))
        promotion_type = self._promotion_types(
            baseline_decision_score,
            bias_decision_score,
            baseline_rank,
            bias_rank,
            self._number(bias.get("track_bias_score")),
            weighted_track_bias_score,
            baseline_consistency_score,
            bias_consistency_score,
            baseline.get("consistency_level"),
            bias.get("consistency_level"),
            baseline_risks,
            bias_risks,
            new_buy,
        )
        return {
            "race_id": race_id,
            "horse_name": bias.get("horse_name") or baseline.get("horse_name"),
            "horse_number": self._to_int(
                bias.get("horse_number")
                or baseline.get("horse_number")
                or official.get("horse_number")
            ),
            "frame_number": self._to_int(
                bias.get("frame_number")
                or baseline.get("frame_number")
                or official.get("frame_number")
            ),
            "finish_position": finish_position,
            "corner_positions": official.get("corner_positions") or official.get("passing_order"),
            "fourth_corner_position": self._to_int(official.get("fourth_corner_position")),
            "last_3f": official.get("last_3f") or official.get("last3f"),
            "last_3f_rank": self._to_int(official.get("last_3f_rank")),
            "pace_style": bias.get("pace_style") or baseline.get("pace_style"),
            "bias_name": bias_name,
            "track_bias_score": self._number(bias.get("track_bias_score")),
            "weighted_track_bias_score": weighted_track_bias_score,
            "baseline_final_score": baseline_score,
            "bias_final_score": bias_score,
            "final_score_diff": self._round(bias_score - baseline_score),
            "baseline_raw_final_score": baseline_final,
            "bias_raw_final_score": bias_final,
            "raw_final_score_diff": self._diff(baseline_final, bias_final),
            "baseline_adjusted_score": baseline_adjusted,
            "bias_adjusted_score": bias_adjusted,
            "adjusted_score_diff": self._diff(baseline_adjusted, bias_adjusted),
            "baseline_rank": baseline_rank,
            "bias_rank": bias_rank,
            "rank_diff": self._rank_diff(baseline_rank, bias_rank),
            "baseline_decision": baseline_decision,
            "bias_decision": bias_decision,
            "baseline_decision_score": baseline_decision_score,
            "bias_decision_score": bias_decision_score,
            "decision_score_diff": self._diff(baseline_decision_score, bias_decision_score),
            "baseline_consistency_score": baseline_consistency_score,
            "bias_consistency_score": bias_consistency_score,
            "consistency_score_diff": self._diff(baseline_consistency_score, bias_consistency_score),
            "baseline_consistency_level": baseline.get("consistency_level"),
            "bias_consistency_level": bias.get("consistency_level"),
            "baseline_risk_count": len(baseline_risks),
            "bias_risk_count": len(bias_risks),
            "risk_count_diff": len(bias_risks) - len(baseline_risks),
            "removed_risks": self._list_diff(baseline_risks, bias_risks),
            "added_risks": self._list_diff(bias_risks, baseline_risks),
            "baseline_conflict_count": len(baseline_conflicts),
            "bias_conflict_count": len(bias_conflicts),
            "decision_changed": baseline_decision != bias_decision,
            "baseline_buy": baseline_decision == "BUY",
            "bias_buy": bias_decision == "BUY",
            "new_buy": new_buy,
            "buy_promoted_by_track_bias": new_buy,
            "promotion_type": promotion_type,
            "promotion_reasons": self._promotion_reasons(
                baseline_decision_score,
                bias_decision_score,
                baseline_rank,
                bias_rank,
                self._number(bias.get("track_bias_score")),
                weighted_track_bias_score,
                self._list_diff(baseline_risks, bias_risks),
                baseline_consistency_score,
                bias_consistency_score,
                promotion_type,
            ),
            "actual_result_class": self._actual_result_class(finish_position),
            "top3_actual": finish_position is not None and finish_position <= 3,
            "top5_actual": finish_position is not None and finish_position <= 5,
        }

    def _race_summary(self, rows, comparisons):
        top3 = [
            row for row in rows
            if self._to_int(row.get("finish_position")) is not None
            and self._to_int(row.get("finish_position")) <= 3
        ]
        corners = [
            self._to_int(row.get("fourth_corner_position"))
            for row in top3
            if self._to_int(row.get("fourth_corner_position")) is not None
        ]
        frames = [
            self._to_int(row.get("frame_number"))
            for row in top3
            if self._to_int(row.get("frame_number")) is not None
        ]
        return {
            "starter_count": len(rows),
            "matched_result_count": len({row.get("horse_name") for row in comparisons}),
            "unmatched_result_count": max(0, len(rows) - len({row.get("horse_name") for row in comparisons})),
            "actual_top3_count": len(top3),
            "actual_top3_average_fourth_corner": self._average(corners),
            "actual_top3_inner_count": sum(1 for frame in frames if frame <= 3),
            "actual_top3_middle_count": sum(1 for frame in frames if 4 <= frame <= 6),
            "actual_top3_outer_count": sum(1 for frame in frames if frame >= 7),
        }

    def _bias_summary(self, comparisons, rows):
        rank_diffs = [
            abs(row.get("rank_diff"))
            for row in comparisons
            if row.get("rank_diff") is not None
        ]
        top3_entries = [
            row for row in comparisons
            if row.get("bias_rank") is not None
            and row.get("bias_rank") <= 3
            and (row.get("baseline_rank") is None or row.get("baseline_rank") > 3)
        ]
        return {
            "starter_count": len(rows),
            "matched_count": len(comparisons),
            "new_buy_count": sum(1 for row in comparisons if row.get("new_buy")),
            "new_buy_top3_actual_count": sum(
                1 for row in comparisons if row.get("new_buy") and row.get("top3_actual")
            ),
            "buy_removed_count": sum(
                1 for row in comparisons if row.get("baseline_buy") and not row.get("bias_buy")
            ),
            "top3_enter_count": len(top3_entries),
            "top3_enter_actual_top3_count": sum(1 for row in top3_entries if row.get("top3_actual")),
            "average_rank_diff": self._average(rank_diffs),
            "score_plus_8_count": sum(1 for row in comparisons if row.get("track_bias_score", 0) >= 8),
            "score_minus_8_count": sum(1 for row in comparisons if row.get("track_bias_score", 0) <= -8),
            "promoted_buy_count": sum(1 for row in comparisons if row.get("buy_promoted_by_track_bias")),
            "promoted_buy_top3_count": sum(
                1 for row in comparisons
                if row.get("buy_promoted_by_track_bias") and row.get("actual_result_class") == "top3"
            ),
            "promoted_buy_top5_count": sum(
                1 for row in comparisons
                if row.get("buy_promoted_by_track_bias") and row.get("actual_result_class") == "top5"
            ),
            "promoted_buy_sixth_or_worse_count": sum(
                1 for row in comparisons
                if row.get("buy_promoted_by_track_bias") and row.get("actual_result_class") == "sixth_or_worse"
            ),
            "rank_unchanged_buy_count": sum(
                1 for row in comparisons
                if row.get("buy_promoted_by_track_bias") and row.get("baseline_rank") == row.get("bias_rank")
            ),
            "low_rank_promoted_buy_count": sum(
                1 for row in comparisons
                if row.get("buy_promoted_by_track_bias")
                and row.get("bias_rank") is not None
                and row.get("bias_rank") > 5
            ),
            "score_threshold_cross_count": sum(
                1 for row in comparisons
                if row.get("buy_promoted_by_track_bias")
                and "score_threshold_cross" in self._list(row.get("promotion_type"))
            ),
            "risk_removed_promotion_count": sum(
                1 for row in comparisons
                if row.get("buy_promoted_by_track_bias")
                and "risk_removed" in self._list(row.get("promotion_type"))
            ),
            "consistency_boosted_promotion_count": sum(
                1 for row in comparisons
                if row.get("buy_promoted_by_track_bias")
                and "consistency_boosted" in self._list(row.get("promotion_type"))
            ),
            "weighted_bias_boost_count": sum(
                1 for row in comparisons
                if row.get("buy_promoted_by_track_bias")
                and "weighted_bias_boost" in self._list(row.get("promotion_type"))
            ),
        }

    def _buy_promotion_diagnostics(self, comparisons):
        diagnostics = []
        for row in comparisons:
            if not row.get("buy_promoted_by_track_bias"):
                continue
            diagnostics.append(
                {
                    "race_id": row.get("race_id"),
                    "bias_name": row.get("bias_name"),
                    "horse_name": row.get("horse_name"),
                    "horse_number": row.get("horse_number"),
                    "frame_number": row.get("frame_number"),
                    "baseline_decision": row.get("baseline_decision"),
                    "bias_decision": row.get("bias_decision"),
                    "baseline_decision_score": row.get("baseline_decision_score"),
                    "bias_decision_score": row.get("bias_decision_score"),
                    "decision_score_diff": row.get("decision_score_diff"),
                    "baseline_final_score": row.get("baseline_final_score"),
                    "bias_final_score": row.get("bias_final_score"),
                    "final_score_diff": row.get("final_score_diff"),
                    "baseline_adjusted_score": row.get("baseline_adjusted_score"),
                    "bias_adjusted_score": row.get("bias_adjusted_score"),
                    "adjusted_score_diff": row.get("adjusted_score_diff"),
                    "baseline_rank": row.get("baseline_rank"),
                    "bias_rank": row.get("bias_rank"),
                    "rank_diff": row.get("rank_diff"),
                    "track_bias_score": row.get("track_bias_score"),
                    "weighted_track_bias_score": row.get("weighted_track_bias_score"),
                    "baseline_consistency_score": row.get("baseline_consistency_score"),
                    "bias_consistency_score": row.get("bias_consistency_score"),
                    "consistency_score_diff": row.get("consistency_score_diff"),
                    "baseline_consistency_level": row.get("baseline_consistency_level"),
                    "bias_consistency_level": row.get("bias_consistency_level"),
                    "baseline_risk_count": row.get("baseline_risk_count"),
                    "bias_risk_count": row.get("bias_risk_count"),
                    "risk_count_diff": row.get("risk_count_diff"),
                    "removed_risks": row.get("removed_risks", []),
                    "added_risks": row.get("added_risks", []),
                    "baseline_conflict_count": row.get("baseline_conflict_count"),
                    "bias_conflict_count": row.get("bias_conflict_count"),
                    "finish_position": row.get("finish_position"),
                    "fourth_corner_position": row.get("fourth_corner_position"),
                    "actual_result_class": row.get("actual_result_class"),
                    "buy_promoted_by_track_bias": True,
                    "promotion_type": row.get("promotion_type", []),
                    "promotion_reasons": row.get("promotion_reasons", []),
                }
            )
        return diagnostics

    def _promotion_summary(self, diagnostics):
        return {
            "track_bias_sensitive_buy_count": len(diagnostics),
            "track_bias_only_buy_count": sum(
                1 for row in diagnostics
                if row.get("baseline_rank") == row.get("bias_rank")
                and self._number(row.get("track_bias_score")) > 0
            ),
            "rank_unchanged_buy_count": sum(
                1 for row in diagnostics if row.get("baseline_rank") == row.get("bias_rank")
            ),
            "low_rank_promoted_buy_count": sum(
                1 for row in diagnostics
                if row.get("bias_rank") is not None and row.get("bias_rank") > 5
            ),
        }

    def _race_decision_promotion_diagnostics(self, baseline, bias_map, buy_diagnostics):
        baseline_decision = self._race_decision(baseline)
        baseline_score = self._race_decision_score(baseline)
        baseline_stats = self._race_stats(baseline)
        baseline_complexity = self._race_value(baseline, "race_complexity")
        baseline_volatility = self._race_value(baseline, "race_volatility")
        baseline_confidence = self._race_value(baseline, "race_confidence")
        buy_by_bias = {}
        for item in buy_diagnostics:
            buy_by_bias.setdefault(item.get("bias_name"), []).append(item)

        bias_results = {}
        for bias_name, result in bias_map.items():
            if not isinstance(result, dict):
                result = {}
            name = str(bias_name)
            decision = self._race_decision(result)
            score = self._race_decision_score(result)
            stats = self._race_stats(result)
            complexity = self._race_value(result, "race_complexity")
            volatility = self._race_value(result, "race_volatility")
            confidence = self._race_value(result, "race_confidence")
            promotion_type = self._race_promotion_types(
                baseline_decision,
                decision,
                baseline_score,
                score,
                baseline_stats,
                stats,
                baseline_complexity,
                complexity,
                baseline_confidence,
                confidence,
            )
            promoted = baseline_decision != "PLAY" and decision == "PLAY"
            bias_results[name] = {
                "race_decision": decision,
                "promoted": promoted,
                "promotion_type": promotion_type,
                "baseline_buy_count": baseline_stats.get("buy_count"),
                "bias_buy_count": stats.get("buy_count"),
                "buy_count_diff": self._diff(
                    baseline_stats.get("buy_count"),
                    stats.get("buy_count"),
                ),
                "track_bias_promoted_buy_count": len(buy_by_bias.get(name, [])),
                "baseline_race_score": baseline_score,
                "bias_race_score": score,
                "race_score_diff": self._diff(baseline_score, score),
                "baseline_complexity": baseline_complexity,
                "bias_complexity": complexity,
                "baseline_volatility": baseline_volatility,
                "bias_volatility": volatility,
                "baseline_confidence": baseline_confidence,
                "bias_confidence": confidence,
                "promotion_reasons": self._race_promotion_reasons(
                    baseline_decision,
                    decision,
                    baseline_score,
                    score,
                    baseline_complexity,
                    complexity,
                    baseline_confidence,
                    confidence,
                    baseline_stats,
                    stats,
                    len(buy_by_bias.get(name, [])),
                    promotion_type,
                ),
            }
        return {
            "baseline_race_decision": baseline_decision,
            "baseline_race_score": baseline_score,
            "baseline_complexity": baseline_complexity,
            "baseline_volatility": baseline_volatility,
            "baseline_confidence": baseline_confidence,
            "baseline_stats": baseline_stats,
            "bias_results": bias_results,
        }

    def _effective_candidates(self, comparisons):
        candidates = []
        for row in comparisons:
            if row.get("top3_actual") and (
                self._entered_top5(row)
                or row.get("new_buy")
                or (
                    row.get("track_bias_score", 0) > 0
                    and row.get("rank_diff") is not None
                    and row.get("rank_diff") < 0
                )
            ):
                candidates.append(row)
        return candidates

    def _over_candidates(self, comparisons):
        candidates = []
        for row in comparisons:
            finish = row.get("finish_position")
            if row.get("track_bias_score", 0) >= 8 and finish is not None and finish >= 6:
                candidates.append(row)
            elif row.get("new_buy") and finish is not None and finish >= 6:
                candidates.append(row)
            elif (
                row.get("rank_diff") is not None
                and row.get("rank_diff") <= -3
                and finish is not None
                and finish > self._starter_lower_half(comparisons)
            ):
                candidates.append(row)
        return candidates

    def _promotion_types(
        self,
        baseline_decision_score,
        bias_decision_score,
        baseline_rank,
        bias_rank,
        track_bias_score,
        weighted_track_bias_score,
        baseline_consistency_score,
        bias_consistency_score,
        baseline_consistency_level,
        bias_consistency_level,
        baseline_risks,
        bias_risks,
        new_buy,
    ):
        if not new_buy:
            return []
        types = []
        if (
            baseline_decision_score is not None
            and bias_decision_score is not None
            and baseline_decision_score < 0.8
            and bias_decision_score >= 0.8
        ):
            types.append("score_threshold_cross")
        if baseline_rank is not None and baseline_rank == bias_rank:
            types.append("rank_unchanged")
        if bias_rank is not None and bias_rank > 5:
            types.append("low_rank_promotion")
        if len(bias_risks) < len(baseline_risks) or self._list_diff(baseline_risks, bias_risks):
            types.append("risk_removed")
        if self._consistency_boosted(
            baseline_consistency_score,
            bias_consistency_score,
            baseline_consistency_level,
            bias_consistency_level,
        ):
            types.append("consistency_boosted")
        if (
            weighted_track_bias_score is not None
            and weighted_track_bias_score > track_bias_score
        ):
            types.append("weighted_bias_boost")
        return types

    def _promotion_reasons(
        self,
        baseline_decision_score,
        bias_decision_score,
        baseline_rank,
        bias_rank,
        track_bias_score,
        weighted_track_bias_score,
        removed_risks,
        baseline_consistency_score,
        bias_consistency_score,
        promotion_type,
    ):
        reasons = []
        if "score_threshold_cross" in promotion_type:
            reasons.append(
                "decision_score crossed BUY threshold "
                f"({baseline_decision_score} -> {bias_decision_score})."
            )
        if "rank_unchanged" in promotion_type:
            reasons.append(f"rank stayed unchanged at {bias_rank}.")
        if "low_rank_promotion" in promotion_type:
            reasons.append(f"promoted to BUY outside Top5 at rank {bias_rank}.")
        if "risk_removed" in promotion_type:
            if removed_risks:
                reasons.append(f"risks removed after bias input: {', '.join(map(str, removed_risks[:3]))}.")
            else:
                reasons.append("risk count decreased after bias input.")
        if "consistency_boosted" in promotion_type:
            reasons.append(
                "consistency improved "
                f"({baseline_consistency_score} -> {bias_consistency_score})."
            )
        if "weighted_bias_boost" in promotion_type:
            reasons.append(
                "track_bias_score was weighted "
                f"({track_bias_score} -> {weighted_track_bias_score})."
            )
        if not reasons:
            reasons.append("BUY appeared only in the bias comparison output.")
        return reasons

    def _race_promotion_types(
        self,
        baseline_decision,
        bias_decision,
        baseline_score,
        bias_score,
        baseline_stats,
        bias_stats,
        baseline_complexity,
        bias_complexity,
        baseline_confidence,
        bias_confidence,
    ):
        types = []
        if baseline_decision == "PASS" and bias_decision == "CAUTION":
            types.append("pass_to_caution")
        if baseline_decision == "PASS" and bias_decision == "PLAY":
            types.append("pass_to_play")
        if baseline_decision == "CAUTION" and bias_decision == "PLAY":
            types.append("caution_to_play")
        if self._number(bias_stats.get("buy_count")) > self._number(baseline_stats.get("buy_count")):
            types.append("buy_count_increased")
        if self._level_reduced(baseline_complexity, bias_complexity, {"high": 3, "medium": 2, "low": 1}):
            types.append("complexity_reduced")
        if self._level_increased(baseline_confidence, bias_confidence, {"unknown": 0, "low": 1, "medium": 2, "high": 3}):
            types.append("confidence_increased")
        if (
            baseline_score is not None
            and bias_score is not None
            and baseline_score < 0.8
            and bias_score >= 0.8
        ):
            types.append("score_threshold_cross")
        return types

    def _race_promotion_reasons(
        self,
        baseline_decision,
        bias_decision,
        baseline_score,
        bias_score,
        baseline_complexity,
        bias_complexity,
        baseline_confidence,
        bias_confidence,
        baseline_stats,
        bias_stats,
        promoted_buy_count,
        promotion_type,
    ):
        reasons = []
        if baseline_decision != bias_decision:
            reasons.append(f"RaceDecision changed {baseline_decision} -> {bias_decision}.")
        if "score_threshold_cross" in promotion_type:
            reasons.append(f"race_decision_score crossed PLAY threshold ({baseline_score} -> {bias_score}).")
        if "complexity_reduced" in promotion_type:
            reasons.append(f"race_complexity reduced {baseline_complexity} -> {bias_complexity}.")
        if "buy_count_increased" in promotion_type:
            reasons.append(
                "BUY count changed "
                f"{baseline_stats.get('buy_count')} -> {bias_stats.get('buy_count')}."
            )
        if promoted_buy_count:
            reasons.append(f"{promoted_buy_count} BUY promotions were detected under this bias.")
        if "confidence_increased" in promotion_type:
            reasons.append(f"race_confidence increased {baseline_confidence} -> {bias_confidence}.")
        return reasons

    def _actual_result_class(self, finish_position):
        if finish_position is None:
            return "special_or_unknown"
        if finish_position <= 3:
            return "top3"
        if finish_position <= 5:
            return "top5"
        return "sixth_or_worse"

    def _weighted_track_bias_score(self, row):
        breakdown = row.get("weighted_score_breakdown")
        if not isinstance(breakdown, dict):
            return None
        item = breakdown.get("track_bias_score")
        if isinstance(item, dict):
            value = item.get("weighted_value")
            return self._optional_number(value)
        return None

    def _risk_items(self, row):
        risks = []
        for key in ["decision_risks", "final_risks", "risk_factors", "risks"]:
            for value in self._list(row.get(key)):
                if value not in risks:
                    risks.append(value)
        return risks

    def _list_diff(self, left, right):
        return [item for item in self._list(left) if item not in self._list(right)]

    def _consistency_boosted(self, baseline_score, bias_score, baseline_level, bias_level):
        if baseline_score is not None and bias_score is not None and bias_score > baseline_score:
            return True
        levels = {"conflict": 0, "low": 1, "medium": 2, "high": 3}
        return levels.get(str(bias_level or "").lower(), -1) > levels.get(
            str(baseline_level or "").lower(),
            -1,
        )

    def _race_decision(self, result):
        value = result.get("race_decision")
        if value:
            return value
        detail = result.get("race_decision_result")
        if isinstance(detail, dict):
            return detail.get("race_decision")
        return None

    def _race_decision_score(self, result):
        value = self._optional_number(result.get("race_decision_score"))
        if value is not None:
            return value
        detail = result.get("race_decision_result")
        if isinstance(detail, dict):
            return self._optional_number(detail.get("race_decision_score"))
        return None

    def _race_value(self, result, key):
        value = result.get(key)
        if value not in (None, ""):
            return value
        detail = result.get("race_decision_result")
        if isinstance(detail, dict):
            return detail.get(key)
        return None

    def _race_stats(self, result):
        detail = result.get("race_decision_result")
        if isinstance(detail, dict) and isinstance(detail.get("race_stats"), dict):
            return dict(detail.get("race_stats"))
        rows = self._trial_horses(result)
        decisions = {"BUY": 0, "CAUTION": 0, "PASS": 0}
        for row in rows:
            decision = str(row.get("decision") or "CAUTION").upper()
            if decision not in decisions:
                decision = "CAUTION"
            decisions[decision] += 1
        return {
            "horse_count": len(rows),
            "buy_count": decisions["BUY"],
            "caution_count": decisions["CAUTION"],
            "pass_count": decisions["PASS"],
        }

    def _level_reduced(self, before, after, order):
        if before is None or after is None:
            return False
        return order.get(str(after).lower(), 0) < order.get(str(before).lower(), 0)

    def _level_increased(self, before, after, order):
        if before is None or after is None:
            return False
        return order.get(str(after).lower(), 0) > order.get(str(before).lower(), 0)

    def _entered_top5(self, row):
        return (
            row.get("bias_rank") is not None
            and row.get("bias_rank") <= 5
            and (row.get("baseline_rank") is None or row.get("baseline_rank") > 5)
        )

    def _starter_lower_half(self, comparisons):
        finishes = [
            row.get("finish_position")
            for row in comparisons
            if row.get("finish_position") is not None
        ]
        if not finishes:
            return 999
        return max(1, max(finishes) // 2)

    def _horse_map(self, trial_result):
        rows = self._trial_horses(trial_result)
        mapping = {}
        for row in rows:
            for key in self._keys(row, trial_result.get("race_id")):
                mapping[key] = row
        return mapping

    def _official_map(self, rows):
        mapping = {}
        for row in rows:
            for key in self._keys(row, row.get("race_id")):
                mapping[key] = row
        return mapping

    def _match_horse(self, row, mapping, race_id):
        for key in [
            self._key(row, race_id),
            self._number_key(row),
            self._name_key(row),
        ]:
            if key and key in mapping:
                return mapping[key]
        return None

    def _keys(self, row, race_id):
        keys = []
        for key in [self._key(row, race_id), self._number_key(row), self._name_key(row)]:
            if key and key not in keys:
                keys.append(key)
        return keys

    def _key(self, row, race_id):
        race = race_id or row.get("race_id")
        number = self._to_int(row.get("horse_number"))
        if race and number is not None:
            return f"{race}#num#{number}"
        name = self._normalize_name(row.get("horse_name"))
        if race and name:
            return f"{race}#name#{name}"
        return self._number_key(row) or self._name_key(row)

    def _number_key(self, row):
        number = self._to_int(row.get("horse_number"))
        if number is None:
            return None
        return f"num#{number}"

    def _name_key(self, row):
        name = self._normalize_name(row.get("horse_name"))
        if not name:
            return None
        return f"name#{name}"

    def _trial_horses(self, result):
        for key in ["horses", "ranked_results", "final_outputs"]:
            value = result.get(key)
            if isinstance(value, list):
                return value
        return []

    def _result_rows(self, official_results):
        if isinstance(official_results, dict):
            rows = official_results.get("horse_results")
            if isinstance(rows, list):
                return rows
            race_result = official_results.get("race_result")
            if isinstance(race_result, dict) and isinstance(race_result.get("horse_results"), list):
                return race_result.get("horse_results")
        if isinstance(official_results, list):
            return official_results
        return []

    def _rank(self, row):
        return self._to_int(row.get("rank") or row.get("final_rank"))

    def _score(self, row):
        for key in ["adjusted_score", "integrated_score", "weighted_score", "final_score"]:
            value = row.get(key)
            if value not in (None, ""):
                return self._number(value)
        score_view = row.get("score_view") or row.get("final_score_view")
        if isinstance(score_view, dict):
            for key in ["adjusted_score", "integrated_score", "weighted_score", "final_score"]:
                value = score_view.get(key)
                if value not in (None, ""):
                    return self._number(value)
        return 0

    def _rank_diff(self, baseline_rank, bias_rank):
        if baseline_rank is None or bias_rank is None:
            return None
        return bias_rank - baseline_rank

    def _unique_unmatched(self, comparisons):
        return []

    def _average(self, values):
        items = [self._number(value) for value in values if value is not None]
        if not items:
            return None
        return self._round(sum(items) / len(items))

    def _normalize_name(self, value):
        return str(value or "").strip().replace(" ", "").replace("　", "")

    def _number(self, value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0

    def _optional_number(self, value):
        if value in (None, "") or isinstance(value, bool):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _to_int(self, value):
        if value in (None, "") or isinstance(value, bool):
            return None
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return None

    def _round(self, value):
        return round(float(value), 2)

    def _list(self, value):
        return value if isinstance(value, list) else []

    def _join(self, value):
        items = self._list(value)
        return ", ".join(str(item) for item in items) if items else "-"

    def _diff(self, before, after):
        if before is None or after is None:
            return None
        return self._round(after - before)


if __name__ == "__main__":
    comparator = TrackBiasResultComparator()
    baseline = {
        "race_id": "race_20260712_kokura_11R",
        "horses": [
            {"horse_name": "A", "horse_number": 1, "rank": 2, "adjusted_score": 100, "decision": "PASS"},
            {"horse_name": "B", "horse_number": 2, "rank": 1, "adjusted_score": 110, "decision": "BUY"},
        ],
    }
    front = {
        "race_id": "race_20260712_kokura_11R",
        "horses": [
            {
                "horse_name": "A",
                "horse_number": 1,
                "rank": 1,
                "adjusted_score": 108,
                "decision": "BUY",
                "track_bias_score": 8,
            },
            {
                "horse_name": "B",
                "horse_number": 2,
                "rank": 2,
                "adjusted_score": 110,
                "decision": "BUY",
                "track_bias_score": 0,
            },
        ],
    }
    official = {
        "race_id": "race_20260712_kokura_11R",
        "horse_results": [
            {
                "race_id": "race_20260712_kokura_11R",
                "horse_name": "A",
                "horse_number": 1,
                "finish_position": 3,
                "corner_positions": "2-2",
                "fourth_corner_position": 2,
            }
        ],
    }
    result = comparator.compare(
        race_id="race_20260712_kokura_11R",
        baseline_result=baseline,
        bias_results={"front": front},
        official_results=official,
    )
    print(comparator.format_report(result))
