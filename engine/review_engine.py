"""Compare prediction snapshots with imported race results.

ReviewEngine only creates comparison output. It does not learn, re-score, or
change predictions, decisions, confidence, snapshots, or result data.
"""

from collections import Counter
import unicodedata


class ReviewEngine:
    """Review prediction_snapshot against race_result."""

    EVALUATOR_RULES = [
        ("DistanceEvaluator", ("距離", "distance")),
        ("TrackBiasEvaluator", ("馬場バイアス", "track_bias", "内外", "前残り", "差し有利", "当日バイアス")),
        ("TrackConditionSuitabilityEvaluator", ("馬場適性", "馬場", "track_condition")),
        ("PaceStyleEvaluator", ("脚質", "pace_style", "running_style", "逃げ", "先行", "差し", "追込", "位置取り")),
        ("RaceShapeEvaluator", ("展開", "RaceShape", "shape", "ペース", "very_fast", "fast", "展開利")),
        ("CourseShapeEvaluator", ("コース形状", "CourseShape", "小回り", "直線", "course_shape", "コース")),
        ("LapSuitabilityEvaluator", ("ラップ", "Lap", "lap", "上がり")),
        ("BloodlineEvaluator", ("血統", "Bloodline", "blood")),
        ("PastPerformanceEvaluator", ("近走", "過去走", "past", "安定", "近走内容")),
        ("ConfidenceEngine", ("Confidence", "信頼度")),
        ("DecisionEngine", ("Decision", "BUY", "PASS", "CAUTION", "Risk", "Conflict")),
    ]

    SCORE_EVALUATORS = {
        "distance_score": "DistanceEvaluator",
        "track_bias_score": "TrackBiasEvaluator",
        "track_condition_score": "TrackConditionSuitabilityEvaluator",
        "track_score": "TrackConditionSuitabilityEvaluator",
        "pace_style_score": "PaceStyleEvaluator",
        "running_style_score": "PaceStyleEvaluator",
        "shape_score": "RaceShapeEvaluator",
        "course_shape_score": "CourseShapeEvaluator",
        "course_score": "CourseShapeEvaluator",
        "lap_score": "LapSuitabilityEvaluator",
        "bloodline_score": "BloodlineEvaluator",
        "blood_score": "BloodlineEvaluator",
        "past_performance_score": "PastPerformanceEvaluator",
        "past_score": "PastPerformanceEvaluator",
        "decision_score": "DecisionEngine",
        "confidence_score": "ConfidenceEngine",
        "consistency_score": "ConsistencyEngine",
    }

    IMPROVEMENT_EVALUATOR_PRIORITY = [
        "DistanceEvaluator",
        "TrackBiasEvaluator",
        "PaceStyleEvaluator",
        "RunningStyleEvaluator",
        "CourseShapeEvaluator",
        "LapSuitabilityEvaluator",
        "RaceShapeEvaluator",
        "TrackConditionSuitabilityEvaluator",
        "BloodlineEvaluator",
        "PastPerformanceEvaluator",
        "ConsistencyEngine",
        "ConfidenceEngine",
    ]

    def review(self, prediction_snapshot=None, race_result=None, review_record=None):
        """Return review_result for loaded results, or pending when unavailable."""

        snapshot = prediction_snapshot if isinstance(prediction_snapshot, dict) else {}
        result = race_result if isinstance(race_result, dict) else {}
        record = review_record if isinstance(review_record, dict) else {}

        result_rows = result.get("horse_results")
        result_loaded = result.get("result_loaded")
        if result_loaded is False:
            return self._pending()
        if result_loaded is None and not result_rows:
            result_rows = result.get("horse_results")

        if not isinstance(result_rows, list) or not result_rows:
            return self._pending()

        finish_map = self._finish_map(result_rows)
        result_map = self._result_map(result_rows)
        hits = []
        misses = []

        self._review_top_horse(snapshot, finish_map, hits, misses)
        self._review_buy_horses(snapshot, finish_map, hits, misses)
        self._review_pass_horses(record, finish_map, hits, misses)
        self._review_confidence(record, finish_map, hits, misses)
        self._review_race_decision(snapshot, finish_map, hits, misses)

        horse_reviews = self._review_horses(record, result_map)
        root_cause_summary = self._root_cause_summary(horse_reviews)
        improvement_candidate = self._improvement_candidate(root_cause_summary)

        score = self._score(hits, misses)
        level = self._level(score)
        summary = self._summary(hits, misses)
        comment = self._comment(level, hits, misses)

        return {
            "review_score": score,
            "review_level": level,
            "review_hits": hits,
            "review_misses": misses,
            "review_summary": summary,
            "review_comment": comment,
            "horse_reviews": horse_reviews,
            "root_cause_summary": root_cause_summary,
            "improvement_candidate": improvement_candidate,
            "review_flow": "Explain -> Result -> Root Cause -> Improvement Candidate",
        }

    def _pending(self):
        return {
            "review_score": None,
            "review_level": "pending",
            "review_hits": [],
            "review_misses": [],
            "review_summary": "結果未入力のためレビューを保留しています。",
            "review_comment": "レース結果が入力された後に、Explainと実結果を比較します。",
            "horse_reviews": [],
            "root_cause_summary": {},
            "improvement_candidate": None,
            "review_flow": "Explain -> Result -> Root Cause -> Improvement Candidate",
        }

    def _review_top_horse(self, snapshot, finish_map, hits, misses):
        top_horses = self._list(snapshot.get("top_horses"))
        if not top_horses:
            misses.append("TopHorse情報なし")
            return
        top = top_horses[0]
        name = top.get("horse_name")
        finish = self._lookup_finish(finish_map, name)
        if finish is None:
            misses.append("TopHorse結果なし")
        elif finish <= 3:
            hits.append("TopHorse 3着以内")
        else:
            misses.append("TopHorse凡走")

    def _review_buy_horses(self, snapshot, finish_map, hits, misses):
        buy_horses = self._list(snapshot.get("buy_horses"))
        if not buy_horses:
            misses.append("BUY馬なし")
            return
        in_money = 0
        missing = 0
        for horse in buy_horses:
            finish = self._lookup_finish(finish_map, horse.get("horse_name"))
            if finish is None:
                missing += 1
            elif finish <= 3:
                in_money += 1
        if in_money:
            hits.append(f"BUY馬3着以内: {in_money}頭")
        if in_money == 0 and missing < len(buy_horses):
            misses.append("BUY馬全滅")
        if missing:
            misses.append(f"BUY馬の結果なし: {missing}頭")

    def _review_pass_horses(self, review_record, finish_map, hits, misses):
        pass_horses = [
            horse for horse in self._list(review_record.get("horses"))
            if horse.get("decision") == "PASS"
        ]
        if not pass_horses:
            return
        good_pass = []
        for horse in pass_horses:
            finish = self._lookup_finish(finish_map, horse.get("horse_name"))
            if finish is not None and finish <= 3:
                good_pass.append(horse.get("horse_name"))
        if good_pass:
            misses.append(f"PASS馬好走: {', '.join(str(name) for name in good_pass[:5])}")
        else:
            hits.append("PASS馬の好走なし")

    def _review_confidence(self, review_record, finish_map, hits, misses):
        horses = self._list(review_record.get("horses"))
        high_confidence = [
            horse for horse in horses
            if str(self._nested_get(horse, ["confidence", "level"]) or "").lower()
            in {"very_high", "high"}
        ]
        if not high_confidence:
            return
        bad = 0
        good = 0
        for horse in high_confidence:
            finish = self._lookup_finish(finish_map, horse.get("horse_name"))
            if finish is None:
                continue
            if finish <= 3:
                good += 1
            elif finish >= 8:
                bad += 1
        if good:
            hits.append(f"Confidence高評価馬好走: {good}頭")
        if bad >= max(1, len(high_confidence) // 2):
            misses.append("Confidence過大評価")

    def _review_race_decision(self, snapshot, finish_map, hits, misses):
        race_decision = str(snapshot.get("race_decision") or "").upper()
        buy_horses = self._list(snapshot.get("buy_horses"))
        top_horses = self._list(snapshot.get("top_horses"))
        top_finish = None
        if top_horses:
            top_finish = self._lookup_finish(finish_map, top_horses[0].get("horse_name"))
        buy_hit = any(
            self._lookup_finish(finish_map, horse.get("horse_name")) is not None
            and self._lookup_finish(finish_map, horse.get("horse_name")) <= 3
            for horse in buy_horses
        )
        if race_decision == "PLAY" and (buy_hit or (top_finish is not None and top_finish <= 3)):
            hits.append("RaceDecision一致")
        elif race_decision == "PLAY":
            misses.append("RaceDecision過信")
        elif race_decision == "PASS" and not buy_hit:
            hits.append("RaceDecision慎重判断")

    def _review_horses(self, review_record, result_map):
        horse_reviews = []
        for horse in self._list(review_record.get("horses")):
            if not isinstance(horse, dict):
                continue
            result = self._lookup_result(result_map, horse.get("horse_name"))
            horse_reviews.append(self._review_horse(horse, result))
        return horse_reviews

    def _review_horse(self, horse, result):
        finish = self._to_int((result or {}).get("finish_position"))
        decision = str(horse.get("decision") or "").upper()
        evaluator_contributions = self._evaluator_contributions(horse)
        correct, wrong = self._judgment_items(horse, result, evaluator_contributions)
        root_causes = self._root_causes(decision, finish, wrong, horse)
        return {
            "horse_name": horse.get("horse_name"),
            "ai_rank": self._to_int(horse.get("rank")),
            "decision": decision,
            "confidence": horse.get("confidence", {}),
            "adjusted_score": horse.get("adjusted_score"),
            "explain_summary": horse.get("summary") or "",
            "explain_factors": {
                "strengths": self._list(horse.get("strengths")),
                "weaknesses": self._list(horse.get("weaknesses")),
                "risks": self._list(horse.get("risks")),
                "warnings": self._list(horse.get("warnings")),
            },
            "evaluator_contributions": evaluator_contributions,
            "result_comparison": self._result_comparison(result),
            "correct_judgments": correct,
            "wrong_judgments": wrong,
            "root_causes": root_causes,
            "review_status": self._horse_review_status(decision, finish),
        }

    def _evaluator_contributions(self, horse):
        contributions = []
        factor_fields = [
            ("strength", horse.get("strengths")),
            ("weakness", horse.get("weaknesses")),
            ("risk", horse.get("risks")),
            ("warning", horse.get("warnings")),
        ]
        for factor_type, values in factor_fields:
            for text in self._list(values):
                contributions.append(
                    {
                        "evaluator": self._infer_evaluator(text),
                        "type": factor_type,
                        "text": str(text),
                    }
                )

        for key, evaluator in self.SCORE_EVALUATORS.items():
            value = horse.get(key)
            if value not in (None, ""):
                contributions.append(
                    {
                        "evaluator": evaluator,
                        "type": "score",
                        "score_key": key,
                        "value": value,
                    }
                )
        return contributions

    def _judgment_items(self, horse, result, evaluator_contributions):
        finish = self._to_int((result or {}).get("finish_position"))
        decision = str(horse.get("decision") or "").upper()
        correct = []
        wrong = []

        if finish is None:
            wrong.append(
                {
                    "item": "Result",
                    "evaluator": "ReviewEngine",
                    "reason": "結果が結合できませんでした。",
                }
            )
            return correct, wrong

        if decision == "BUY":
            target = correct if finish <= 3 else wrong
            target.append(
                {
                    "item": "Decision",
                    "evaluator": "DecisionEngine",
                    "reason": f"BUY判定と実着順{finish}着の比較",
                }
            )
        elif decision == "PASS":
            target = wrong if finish <= 3 else correct
            target.append(
                {
                    "item": "Decision",
                    "evaluator": "DecisionEngine",
                    "reason": f"PASS判定と実着順{finish}着の比較",
                }
            )
        elif decision == "CAUTION":
            target = correct if finish <= 5 else wrong
            target.append(
                {
                    "item": "Decision",
                    "evaluator": "DecisionEngine",
                    "reason": f"CAUTION判定と実着順{finish}着の比較",
                }
            )

        for contribution in evaluator_contributions:
            ctype = contribution.get("type")
            if ctype == "strength":
                target = correct if finish <= 3 else wrong
            elif ctype in {"weakness", "risk", "warning"}:
                target = wrong if finish <= 3 else correct
            else:
                continue
            target.append(
                {
                    "item": ctype,
                    "evaluator": contribution.get("evaluator"),
                    "reason": contribution.get("text"),
                }
            )
        return correct, wrong

    def _result_comparison(self, result):
        item = result if isinstance(result, dict) else {}
        return {
            "finish_position": self._to_int(item.get("finish_position")),
            "frame_number": self._to_int(item.get("frame_number")),
            "horse_number": self._to_int(item.get("horse_number")),
            "corner_positions": item.get("corner_positions") or item.get("passing_order") or "",
            "fourth_corner_position": self._to_int(item.get("fourth_corner_position")),
            "last_3f": item.get("last_3f") or item.get("last3f") or "",
            "finish_time": item.get("finish_time") or item.get("official_time") or "",
            "margin": item.get("margin") or "",
            "popularity": item.get("popularity"),
            "odds": item.get("odds"),
            "pace": item.get("pace") or item.get("race_pace"),
            "track_condition": item.get("track_condition"),
        }

    def _root_causes(self, decision, finish, wrong_items, horse):
        if finish is None:
            return ["ResultJoin"]
        if not wrong_items:
            return []
        counter = Counter(item.get("evaluator") or "ReviewEngine" for item in wrong_items)
        evaluator_causes = [
            name
            for name, _count in counter.most_common()
            if self._is_evaluator_cause(name)
        ]
        causes = evaluator_causes[:3]
        if not causes:
            causes = [name for name, _count in counter.most_common(3)]
        if decision == "BUY" and finish >= 4 and not causes:
            causes.append("DecisionEngine")
        if decision == "PASS" and finish <= 3 and not causes:
            causes.append("DecisionEngine")
        if self._list(horse.get("warnings")) and "Warning" not in causes:
            causes.append("Warning")
        return causes

    def _root_cause_summary(self, horse_reviews):
        counter = Counter()
        for review in horse_reviews:
            for cause in self._list(review.get("root_causes")):
                counter[cause] += 1
        return dict(counter.most_common())

    def _improvement_candidate(self, root_cause_summary):
        if not root_cause_summary:
            return {
                "target": "None",
                "comment": "大きな改善候補はありません。",
            }
        target = self._select_improvement_target(root_cause_summary)
        return {
            "target": target,
            "comment": f"Improvement Candidate - {target}を見直す",
        }

    def _select_improvement_target(self, root_cause_summary):
        for evaluator in self.IMPROVEMENT_EVALUATOR_PRIORITY:
            if evaluator in root_cause_summary:
                return evaluator
        for name in root_cause_summary:
            if self._is_evaluator_cause(name):
                return name
        return "DecisionEngine"

    def _is_evaluator_cause(self, name):
        return str(name or "").endswith("Evaluator") or name in {
            "RunningStyleEvaluator",
            "ConsistencyEngine",
            "ConfidenceEngine",
        }

    def _horse_review_status(self, decision, finish):
        if finish is None:
            return "result_missing"
        if decision == "BUY" and finish <= 3:
            return "buy_success"
        if decision == "BUY":
            return "buy_miss"
        if decision == "PASS" and finish <= 3:
            return "pass_miss"
        if decision == "PASS":
            return "pass_success"
        if decision == "CAUTION" and finish <= 5:
            return "caution_success"
        if decision == "CAUTION":
            return "caution_miss"
        return "reviewed"

    def _finish_map(self, rows):
        mapping = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = row.get("horse_name")
            finish = self._to_int(row.get("finish_position"))
            if name and finish is not None:
                mapping[self._normalize_name(name)] = finish
                mapping[name] = finish
        return mapping

    def _result_map(self, rows):
        mapping = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = row.get("horse_name")
            if name:
                mapping[self._normalize_name(name)] = row
                mapping[name] = row
        return mapping

    def _lookup_finish(self, finish_map, name):
        if name in finish_map:
            return finish_map.get(name)
        return finish_map.get(self._normalize_name(name))

    def _lookup_result(self, result_map, name):
        if name in result_map:
            return result_map.get(name)
        return result_map.get(self._normalize_name(name), {})

    def _score(self, hits, misses):
        total = len(hits) + len(misses)
        if total == 0:
            return 0.55
        score = len(hits) / total
        return round(max(0, min(1, score)), 2)

    def _level(self, score):
        if score is None:
            return "pending"
        if score >= 0.9:
            return "excellent"
        if score >= 0.75:
            return "good"
        if score >= 0.55:
            return "normal"
        if score >= 0.3:
            return "poor"
        return "bad"

    def _summary(self, hits, misses):
        if not hits and not misses:
            return "比較材料が不足しています。"
        if hits and not misses:
            return "予測評価は概ね結果と一致しました。"
        if hits and misses:
            return "当たった評価と外れた評価が混在しています。"
        return "主要な評価が結果と噛み合いませんでした。"

    def _comment(self, level, hits, misses):
        if level in {"excellent", "good"}:
            return "構造評価は良好です。"
        if level == "normal":
            return "一部の評価は妥当ですが、改善余地があります。"
        if level == "poor":
            return "展開またはConfidence評価に見直し余地があります。"
        if level == "bad":
            return "予測根拠と結果のズレが大きく、重点的なレビューが必要です。"
        return "結果未入力のためレビュー保留です。"

    def _infer_evaluator(self, text):
        value = str(text or "")
        for evaluator, keywords in self.EVALUATOR_RULES:
            if any(keyword in value for keyword in keywords):
                return evaluator
        return "ReviewEngine"

    def _to_int(self, value):
        if isinstance(value, bool) or value in {None, ""}:
            return None
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return None

    def _normalize_name(self, value):
        text = unicodedata.normalize("NFKC", str(value or "")).strip()
        return text.replace(" ", "").replace("　", "")

    def _nested_get(self, value, keys):
        current = value
        for key in keys:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    def _list(self, value):
        return value if isinstance(value, list) else []


if __name__ == "__main__":
    engine = ReviewEngine()
    print(engine.review({}, {"result_loaded": False}))
