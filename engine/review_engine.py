"""Compare prediction snapshots with imported race results.

ReviewEngine only creates comparison output. It does not learn, re-score, or
change predictions, decisions, confidence, snapshots, or result data.
"""


class ReviewEngine:
    """Review prediction_snapshot against race_result."""

    def review(self, prediction_snapshot=None, race_result=None, review_record=None):
        """Return review_result for loaded results, or pending when unavailable."""

        snapshot = prediction_snapshot if isinstance(prediction_snapshot, dict) else {}
        result = race_result if isinstance(race_result, dict) else {}
        record = review_record if isinstance(review_record, dict) else {}

        if not result.get("result_loaded"):
            return self._pending()

        result_rows = result.get("horse_results")
        if not isinstance(result_rows, list) or not result_rows:
            return self._pending()

        finish_map = self._finish_map(result_rows)
        hits = []
        misses = []

        self._review_top_horse(snapshot, finish_map, hits, misses)
        self._review_buy_horses(snapshot, finish_map, hits, misses)
        self._review_pass_horses(record, finish_map, hits, misses)
        self._review_confidence(record, finish_map, hits, misses)
        self._review_race_decision(snapshot, finish_map, hits, misses)

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
        }

    def _pending(self):
        return {
            "review_score": None,
            "review_level": "pending",
            "review_hits": [],
            "review_misses": [],
            "review_summary": "結果未入力",
            "review_comment": "レース結果が未入力のため、レビューは保留です。",
        }

    def _review_top_horse(self, snapshot, finish_map, hits, misses):
        top_horses = self._list(snapshot.get("top_horses"))
        if not top_horses:
            misses.append("Top評価馬情報なし")
            return
        top = top_horses[0]
        name = top.get("horse_name")
        finish = finish_map.get(name)
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
            finish = finish_map.get(horse.get("horse_name"))
            if finish is None:
                missing += 1
            elif finish <= 3:
                in_money += 1
        if in_money:
            hits.append(f"BUY馬が3着以内: {in_money}頭")
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
            finish = finish_map.get(horse.get("horse_name"))
            if finish is not None and finish <= 3:
                good_pass.append(horse.get("horse_name"))
        if good_pass:
            misses.append(f"PASS馬好走: {', '.join(str(name) for name in good_pass[:5])}")
        else:
            hits.append("PASS馬の激走なし")

    def _review_confidence(self, review_record, finish_map, hits, misses):
        horses = self._list(review_record.get("horses"))
        high_confidence = [
            horse for horse in horses
            if str(horse.get("confidence", {}).get("level") or "").lower() in {"very_high", "high"}
        ]
        if not high_confidence:
            return
        bad = 0
        good = 0
        for horse in high_confidence:
            finish = finish_map.get(horse.get("horse_name"))
            if finish is None:
                continue
            if finish <= 3:
                good += 1
            elif finish >= 8:
                bad += 1
        if good:
            hits.append(f"Confidence高評価馬が好走: {good}頭")
        if bad >= max(1, len(high_confidence) // 2):
            misses.append("Confidence過大評価")

    def _review_race_decision(self, snapshot, finish_map, hits, misses):
        race_decision = str(snapshot.get("race_decision") or "").upper()
        buy_horses = self._list(snapshot.get("buy_horses"))
        top_horses = self._list(snapshot.get("top_horses"))
        top_finish = None
        if top_horses:
            top_finish = finish_map.get(top_horses[0].get("horse_name"))
        buy_hit = any(
            finish_map.get(horse.get("horse_name")) is not None
            and finish_map.get(horse.get("horse_name")) <= 3
            for horse in buy_horses
        )
        if race_decision == "PLAY" and (buy_hit or (top_finish is not None and top_finish <= 3)):
            hits.append("RaceDecision一致")
        elif race_decision == "PLAY":
            misses.append("RaceDecision過信")
        elif race_decision == "PASS" and not buy_hit:
            hits.append("RaceDecision慎重判断")

    def _finish_map(self, rows):
        mapping = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = row.get("horse_name")
            finish = self._to_int(row.get("finish_position"))
            if name and finish is not None:
                mapping[name] = finish
        return mapping

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
            return "予想評価は概ね結果と一致しました。"
        if hits and misses:
            return "当たった評価と外れた評価が混在しています。"
        return "主要な評価が結果と噛み合いませんでした。"

    def _comment(self, level, hits, misses):
        if level in {"excellent", "good"}:
            return "構造評価は良好。"
        if level == "normal":
            return "一部の評価は妥当だが、改善余地があります。"
        if level == "poor":
            return "展開またはConfidence評価に見直し余地があります。"
        if level == "bad":
            return "予想根拠と結果のズレが大きく、重点的な見直しが必要です。"
        return "結果未入力のためレビュー保留。"

    def _to_int(self, value):
        if isinstance(value, bool) or value in {None, ""}:
            return None
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return None

    def _list(self, value):
        return value if isinstance(value, list) else []


if __name__ == "__main__":
    engine = ReviewEngine()
    print(engine.review({}, {"result_loaded": False}))
