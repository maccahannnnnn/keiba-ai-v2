"""Frozen-primary-gated, development-only December/January check."""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from review.candidate_generation_training_dataset_readiness_v1 import JAPANESE_VENUE, outcome, parse_race_id, result_rows
from review.current_k_play_failure_decomposition_v1 import OUT, ROOT, dump, group_metric, hit, rank_current, rate, sha, stats, topk_metric

FROZEN_SHA = "39b9debf4db4f189488ac6a1ed92e70ac0a32a7c281a6144a7cd84786b88b4cd"
SOURCE_ROOT = ROOT / "reports/consumed_holdout_bounded_reproduction_v1"


def check(month: str, expected_races: int, expected_horses: int) -> dict:
    # No outcome file may be read before these gates have passed.
    frozen = OUT / "primary_findings_951_frozen.json"
    if sha(frozen) != FROZEN_SHA or frozen.with_suffix(".sha256").read_text(encoding="ascii").strip() != FROZEN_SHA:
        raise RuntimeError("STOP_PRIMARY_FINDINGS_FREEZE_SHA")
    policy = ROOT / "docs/CONSUMED_HOLDOUT_DEVELOPMENT_REUSE_POLICY_V1.json"
    if sha(policy) != "68ac7033ad74effabcb0844a061bdc3e485f32072b153c58723dcf8f34674ec3":
        raise RuntimeError("STOP_REUSE_POLICY_SHA")
    meta = json.loads((SOURCE_ROOT / "summary.json").read_text(encoding="utf-8"))["months"][month]
    if meta["verdict"] != "PASS" or meta["regenerated_races"] != expected_races or meta["regenerated_horses"] != expected_horses:
        raise RuntimeError("STOP_SECONDARY_PRE_READINESS")
    pre_path = SOURCE_ROOT / month / "run_a/runtime_pre_only_output.json"
    if sha(pre_path) != meta["run_a_sha256"]:
        raise RuntimeError("STOP_SECONDARY_PRE_SHA")
    rows = json.loads(pre_path.read_text(encoding="utf-8"))["generated_rows"]
    if len(rows) != expected_horses:
        raise RuntimeError("STOP_SECONDARY_PRE_ROW_COUNT")
    by_date = {}
    result_sources = []
    for date in meta["source_dates"]:
        primary = ROOT / f"data/raw/target/daily_result_list/馬番順着順_{date}.csv"
        auxiliary = ROOT / f"data/raw/target/daily_result_list/着順馬番_{date}.csv"
        for path in (primary, auxiliary):
            if not path.is_file():
                raise RuntimeError("STOP_SECONDARY_RESULT_MISSING:" + str(path))
            result_sources.append({"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path)})
        by_date[date] = result_rows(date)
    by_race = defaultdict(list)
    for pre in rows:
        date, venue_key, race_number = parse_race_id(pre["race_id"])
        if date not in by_date or venue_key not in JAPANESE_VENUE:
            raise RuntimeError("STOP_SECONDARY_PRE_DATE_OR_VENUE")
        race_result = by_date[date].get((JAPANESE_VENUE[venue_key], race_number))
        if race_result is None:
            raise RuntimeError("STOP_SECONDARY_RESULT_RACE_MISSING:" + pre["race_id"])
        valid_result, finish, actual_top3 = outcome(race_result, int(pre["horse_number"]))
        v = pre["values"]
        row = {"date": date, "race_id": pre["race_id"], "horse_number": int(pre["horse_number"]),
               "horse_name": pre["horse_name"], "current_rank": int(pre["rank"]),
               "adjusted_score": v["adjusted_score"], "race_state": v["race_state"],
               "candidate": v["shadow_buy_candidate"] is True,
               "current_buy": v["post_rc1_decision"] == "BUY",
               "valid_result": valid_result, "finish": finish, "actual_top3": actual_top3}
        by_race[pre["race_id"]].append(row)
    groups = []
    for race_id, field in sorted(by_race.items()):
        state_set = {row["race_state"] for row in field}
        if len(state_set) != 1 or len({row["horse_number"] for row in field}) != len(field):
            raise RuntimeError("STOP_SECONDARY_RACE_INTEGRITY:" + race_id)
        state = next(iter(state_set))
        candidate = [row for row in field if row["candidate"]]
        buy = [row for row in field if row["current_buy"]]
        if not ((state == "PLAY_CONVERGED" and 1 <= len(candidate) <= 3 and {r["horse_number"] for r in candidate} == {r["horse_number"] for r in buy})
                or (state == "PLAY_UNCONVERGED_4PLUS" and len(candidate) >= 4 and not buy)
                or (state == "SKIP" and not buy)):
            raise RuntimeError("STOP_SECONDARY_STAGE_B:" + race_id)
        score = rank_current(field)
        if any(score[i]["adjusted_score"] < score[i + 1]["adjusted_score"] for i in range(len(score) - 1)):
            raise RuntimeError("STOP_SECONDARY_SCORE_ORDER:" + race_id)
        groups.append({"race_id": race_id, "date": field[0]["date"], "month": field[0]["date"][:6],
                       "venue": race_id.split("_")[2], "state": state, "field": field,
                       "candidate": candidate, "buy": buy, "score": score,
                       "score_candidate": rank_current(candidate),
                       "candidate_hits": sum(hit(r) for r in candidate), "field_hits": sum(hit(r) for r in field)})
    if len(groups) != expected_races:
        raise RuntimeError("STOP_SECONDARY_RACE_COUNT")
    states = {s: [g for g in groups if g["state"] == s] for s in ("PLAY_CONVERGED", "PLAY_UNCONVERGED_4PLUS", "SKIP")}
    converged = states["PLAY_CONVERGED"]
    buy = topk_metric(converged, "buy", "actual_k")
    score = topk_metric(converged, "score", "actual_k")
    paired = Counter()
    for g in converged:
        delta = sum(hit(r) for r in g["score"][:len(g["buy"])]) - sum(hit(r) for r in g["buy"])
        paired["score_wins" if delta > 0 else "buy_wins" if delta < 0 else "tie"] += 1
    frozen_primary = json.loads(frozen.read_text(encoding="utf-8"))
    primary_loss = frozen_primary["mechanism_findings"]
    loss = {"candidate_generation_failure_races": sum(g["candidate_hits"] == 0 for g in groups),
            "unconverged_discard_loss_races": sum(g["candidate_hits"] > 0 for g in states["PLAY_UNCONVERGED_4PLUS"]),
            "unconverged_discard_loss_top3": sum(g["candidate_hits"] for g in states["PLAY_UNCONVERGED_4PLUS"]),
            "skip_gate_loss_races": sum(g["candidate_hits"] > 0 for g in states["SKIP"]),
            "selection_failure_score_only_races": sum(not any(hit(r) for r in g["buy"]) and any(hit(r) for r in g["score"][:len(g["buy"])]) for g in converged)}
    comparisons = {
        "candidate_failure_rate_primary": frozen_primary["candidate_generation_failure_rate"],
        "candidate_failure_rate_secondary": rate(loss["candidate_generation_failure_races"], len(groups)),
        "unconverged_loss_fraction_primary": rate(primary_loss["unconverged_discard_loss_races"], frozen_primary["state_counts"]["PLAY_UNCONVERGED_4PLUS"]),
        "unconverged_loss_fraction_secondary": rate(loss["unconverged_discard_loss_races"], len(states["PLAY_UNCONVERGED_4PLUS"])),
        "score_ordering_hit_delta_primary": frozen_primary["ordering"]["current_score_topk"]["raw_hit_difference_vs_current_buy"],
        "score_ordering_hit_delta_secondary": score["top3_hits"] - buy["top3_hits"],
        "frozen_pl_secondary": "NOT_AVAILABLE_AS_CONTEMPORANEOUS_FROZEN_OUTPUT"}
    repeated = (loss["candidate_generation_failure_races"] > 0 and loss["unconverged_discard_loss_races"] > 0
                and (score["top3_hits"] - buy["top3_hits"]) >= 0)
    return {"role": "REUSED_CONSUMED_HOLDOUT_FOR_DEVELOPMENT_ONLY", "evidence_credit": 0,
            "block": month, "primary_findings_sha256_verified_before_result": FROZEN_SHA,
            "pre_source": {"path": pre_path.relative_to(ROOT).as_posix(), "sha256": sha(pre_path)},
            "result_sources": result_sources, "population": {"dates": len(by_date), "races": len(groups), "horses": len(rows)},
            "state_counts": {s: len(v) for s, v in states.items()},
            "by_state": {s: group_metric(v) for s, v in states.items()},
            "candidate_count_distribution": dict(Counter(len(g["candidate"]) for g in groups)),
            "mechanism_loss": loss, "converged_same_race_same_k": {"current_buy": buy, "current_score_topk": score, "paired": dict(paired)},
            "primary_comparison": comparisons,
            "replication": "PARTIALLY_REPEAT" if repeated else "CONTRADICT",
            "replication_note": "Primary candidate/unconverged/score definitions repeated; PL ordering unavailable as contemporaneous frozen output. No new PL inference was run."}


def main() -> None:
    for month, races, horses in (("december", 146, 2093), ("january", 149, 2045)):
        obj = check(month, races, horses)
        dump(OUT / f"secondary_{month}_check.json", obj)
        print(json.dumps({"block": month, "population": obj["population"], "states": obj["state_counts"],
                          "loss": obj["mechanism_loss"], "ordering": obj["converged_same_race_same_k"],
                          "replication": obj["replication"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
