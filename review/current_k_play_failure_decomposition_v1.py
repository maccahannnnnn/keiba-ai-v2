"""Development-only Current k/PLAY mechanism diagnostic.

The primary command reads no December/January outcome artifact. A separate
secondary command may run only after the primary findings SHA is frozen.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/current_k_play_failure_decomposition_v1"
POP = ROOT / "reports/current_population_audit_v1/diagnostic_population_final_proposal.csv"
PRE = ROOT / "reports/full_field_redesign_iter0_v1_retry6/pre_only_regeneration/shards"
JOINED = ROOT / "reports/full_field_redesign_iteration2_recovery_inputs_v1/run_a_frozen.json"
JOINED_SHA = "48401e556f28f5625d85dfa315153a6dbba84e3114e3a9752e17b25e50f71c22"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def csv_out(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def rate(hits: int, n: int):
    return hits / n if n else None


def hit(row: dict) -> bool:
    return row["valid_result"] is True and row["actual_top3"] is True


def valid(row: dict) -> bool:
    return row["valid_result"] is True


def stats(rows: list[dict]) -> dict:
    n = sum(valid(row) for row in rows)
    hits = sum(hit(row) for row in rows)
    return {"selected_raw": len(rows), "selected_valid": n, "top3_hits": hits, "top3_rate": rate(hits, n)}


def rank_current(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda row: (int(row["current_rank"]), int(row["horse_number"])))


def rank_pl(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda row: (-float(row["p_hgb"]), int(row["horse_number"])))


def group_metric(groups: list[dict]) -> dict:
    field = [r for g in groups for r in g["field"]]
    cand = [r for g in groups for r in g["candidate"]]
    buy = [r for g in groups for r in g["buy"]]
    field_hits = sum(hit(r) for r in field)
    candidate_hits = sum(hit(r) for r in cand)
    return {"races": len(groups), "field_horses": len(field), "field_actual_top3": field_hits,
            "candidate_horses": len(cand), "candidate_top3_hits": candidate_hits,
            "candidate_recall": rate(candidate_hits, field_hits),
            "buy": stats(buy), "candidate_hit_race_counts": dict(Counter(min(3, g["candidate_hits"]) for g in groups))}


def load_primary() -> tuple[list[dict], dict]:
    if sha(JOINED) != JOINED_SHA:
        raise RuntimeError("STOP_ITERATION2_FROZEN_INPUT_SHA")
    population = list(csv.DictReader(POP.open(encoding="utf-8-sig", newline="")))
    ids = {r["race_id"] for r in population}
    if len(ids) != 951 or len(population) != 951:
        raise RuntimeError("STOP_PRIMARY_951_POPULATION")
    pre = {}
    shards = sorted(PRE.glob("run_c_*/runtime_pre_only_output.json"))
    if len(shards) != 31:
        raise RuntimeError("STOP_RUN_C_SHARDS")
    for path in shards:
        for row in json.loads(path.read_text(encoding="utf-8"))["generated_rows"]:
            if row["race_id"] in ids:
                key = (row["race_id"], int(row["horse_number"]))
                if key in pre:
                    raise RuntimeError("STOP_PRE_DUPLICATE_KEY")
                pre[key] = row
    joined = json.loads(JOINED.read_text(encoding="utf-8"))["rows"]
    post = {(row["race_id"], int(row["horse_number"])): row for row in joined}
    if set(pre) != set(post) or len(post) != len(joined) or len(post) != 12661:
        raise RuntimeError("STOP_PRE_POST_POPULATION_KEY_MISMATCH")
    if any((row["values"]["post_rc1_decision"] == "BUY") != bool(post[key]["current_buy"]) for key, row in pre.items()):
        raise RuntimeError("STOP_CURRENT_BUY_PRE_POST_MISMATCH")
    if any(int(row["rank"]) != int(post[key]["current_rank"]) for key, row in pre.items()):
        raise RuntimeError("STOP_CURRENT_RANK_PRE_POST_MISMATCH")
    if any(not isinstance(row["p_hgb"], (int, float)) or not math.isfinite(row["p_hgb"]) for row in joined):
        raise RuntimeError("STOP_FROZEN_PL_SCORE_UNAVAILABLE")
    by = defaultdict(list)
    for key, old in post.items():
        pre_row = pre[key]
        row = dict(old)
        row["candidate"] = pre_row["values"].get("shadow_buy_candidate") is True
        row["race_state"] = pre_row["values"]["race_state"]
        row["current_buy"] = pre_row["values"]["post_rc1_decision"] == "BUY"
        row["adjusted_score"] = pre_row["values"]["adjusted_score"]
        by[key[0]].append(row)
    groups = []
    for race_id, field in sorted(by.items()):
        states = {r["race_state"] for r in field}
        if len(states) != 1:
            raise RuntimeError("STOP_INCONSISTENT_RACE_STATE")
        state = next(iter(states))
        candidate = [r for r in field if r["candidate"]]
        buy = [r for r in field if r["current_buy"]]
        if not ((state == "PLAY_CONVERGED" and 1 <= len(candidate) <= 3 and {r["horse_number"] for r in candidate} == {r["horse_number"] for r in buy})
                or (state == "PLAY_UNCONVERGED_4PLUS" and len(candidate) >= 4 and not buy)
                or (state == "SKIP" and not buy)):
            raise RuntimeError("STOP_STAGE_B_SEMANTICS:" + race_id)
        score = rank_current(field)
        # Frozen Current rank is authoritative for score ties; horse-number
        # sorting would silently replace the PRE tie semantics.
        if any(score[i]["adjusted_score"] < score[i + 1]["adjusted_score"] for i in range(len(score) - 1)):
            raise RuntimeError("STOP_CURRENT_SCORE_RANK_DISAGREEMENT:" + race_id)
        pl = rank_pl(field)
        g = {"race_id": race_id, "date": field[0]["date"], "month": field[0]["date"][:6],
             "venue": race_id.split("_")[2], "race_number": race_id.split("_")[3], "state": state,
             "field": field, "candidate": candidate, "buy": buy, "score": score, "pl": pl,
             "score_candidate": rank_current(candidate), "pl_candidate": rank_pl(candidate),
             "candidate_hits": sum(hit(r) for r in candidate), "field_hits": sum(hit(r) for r in field)}
        groups.append(g)
    counts = Counter(g["state"] for g in groups)
    if counts != {"PLAY_CONVERGED": 432, "PLAY_UNCONVERGED_4PLUS": 228, "SKIP": 291}:
        raise RuntimeError("STOP_PRIMARY_STATE_COUNTS")
    return groups, {"population_sha256": sha(POP), "joined_sha256": sha(JOINED),
                    "pre_shards": [{"path": p.relative_to(ROOT).as_posix(), "sha256": sha(p)} for p in shards],
                    "frozen_pl_column": "p_hgb", "frozen_pl_mapping_authority": "reports/pl_current_race_selection_dev_diagnostic_v1/diagnostic_summary.md"}


def topk_metric(groups: list[dict], pool: str, k: int | str) -> dict:
    selected = [row for g in groups for row in g[pool][: (len(g["buy"]) if k == "actual_k" else k)]]
    return stats(selected)


def topk_by_race(groups: list[dict], pool: str, k: int | str) -> dict:
    metric = topk_metric(groups, pool, k)
    metric["race_hit_count"] = sum(bool(any(hit(row) for row in g[pool][: (len(g["buy"]) if k == "actual_k" else k)])) for g in groups)
    return metric


def primary() -> None:
    if OUT.exists():
        raise RuntimeError("STOP_OUTPUT_ROOT_EXISTS")
    groups, authority = load_primary()
    OUT.mkdir(parents=True)
    rows = []
    for g in groups:
        rows.append({"date": g["date"], "venue": g["venue"], "race_id": g["race_id"], "race_number": g["race_number"],
                     "race_state": g["state"], "field_size": len(g["field"]), "candidate_count": len(g["candidate"]),
                     "current_k": len(g["buy"]), "candidate_horse_numbers": ";".join(str(r["horse_number"]) for r in rank_current(g["candidate"])),
                     "buy_horse_numbers": ";".join(str(r["horse_number"]) for r in rank_current(g["buy"])),
                     "current_score_order": ";".join(str(r["horse_number"]) for r in g["score"]),
                     "frozen_pl_order": ";".join(str(r["horse_number"]) for r in g["pl"]),
                     "valid_result_horses": sum(valid(r) for r in g["field"]),
                     "invalid_result_horses": sum(not valid(r) for r in g["field"]),
                     "actual_top3_horses": g["field_hits"], "candidate_top3_horses": g["candidate_hits"],
                     "current_buy_top3_horses": sum(hit(r) for r in g["buy"])})
    csv_out(OUT / "primary_race_diagnostic.csv", list(rows[0]), rows)

    by_state = {s: [g for g in groups if g["state"] == s] for s in ("PLAY_CONVERGED", "PLAY_UNCONVERGED_4PLUS", "SKIP")}
    candidate = {"all": group_metric(groups), "by_state": {s: group_metric(v) for s, v in by_state.items()},
                 "candidate_count_distribution": dict(Counter(len(g["candidate"]) for g in groups)),
                 "candidate_hit_race_distribution": dict(Counter(min(3, g["candidate_hits"]) for g in groups)),
                 "zero_candidate_top3_races": sum(g["candidate_hits"] == 0 for g in groups)}
    dump(OUT / "candidate_generation_diagnostic.json", candidate)

    unconverged = {}
    for bucket in (4, 5, 6, "7+"):
        subset = [g for g in by_state["PLAY_UNCONVERGED_4PLUS"] if (len(g["candidate"]) == bucket if isinstance(bucket, int) else len(g["candidate"]) >= 7)]
        unconverged[str(bucket)] = {"scope": group_metric(subset),
                                    "current_candidate_score_top1": topk_by_race(subset, "score_candidate", 1),
                                    "current_candidate_score_top2": topk_by_race(subset, "score_candidate", 2),
                                    "current_candidate_score_top3": topk_by_race(subset, "score_candidate", 3),
                                    "pl_within_candidates_top1": topk_by_race(subset, "pl_candidate", 1),
                                    "pl_within_candidates_top2": topk_by_race(subset, "pl_candidate", 2),
                                    "pl_within_candidates_top3": topk_by_race(subset, "pl_candidate", 3),
                                    "pl_full_field_top1": topk_by_race(subset, "pl", 1),
                                    "pl_full_field_top2": topk_by_race(subset, "pl", 2),
                                    "pl_full_field_top3": topk_by_race(subset, "pl", 3)}
    dump(OUT / "unconverged_4plus_diagnostic.json", {"role": "COUNTERFACTUAL_DEVELOPMENT_ONLY_NOT_BUY", "by_candidate_count": unconverged})

    converged = {}
    for k in (1, 2, 3):
        subset = [g for g in by_state["PLAY_CONVERGED"] if len(g["buy"]) == k]
        converged[str(k)] = {"scope": group_metric(subset), "current_buy": topk_by_race(subset, "buy", "actual_k"),
                             "current_score_topk": topk_by_race(subset, "score", "actual_k"),
                             "pl_topk": topk_by_race(subset, "pl", "actual_k"),
                             "actual_top3_recall_current_buy": rate(sum(hit(r) for g in subset for r in g["buy"]), sum(g["field_hits"] for g in subset))}
    dump(OUT / "play_converged_k_diagnostic.json", converged)

    skip = {}
    for reason, subset in {"ZERO_CANDIDATES_CODE_PATH": [g for g in by_state["SKIP"] if not g["candidate"]],
                           "NONZERO_CANDIDATES_EXACT_REASON_NOT_RECORDED": [g for g in by_state["SKIP"] if g["candidate"]]}.items():
        skip[reason] = {"scope": group_metric(subset), "candidate_count_distribution": dict(Counter(len(g["candidate"]) for g in subset)),
                        "current_score_rank1": topk_by_race(subset, "score", 1), "pl_rank1": topk_by_race(subset, "pl", 1),
                        "counterfactual_k": "NOT_DEFINED_FOR_SKIP"}
    dump(OUT / "skip_diagnostic.json", {"exact_runtime_skip_reason": "NOT_RECORDED_IN_RUN_C", "reason_groups": skip})

    loss = {"candidate_generation_failure_races": sum(g["candidate_hits"] == 0 for g in groups),
            "candidate_generation_failure_field_top3": sum(g["field_hits"] for g in groups if g["candidate_hits"] == 0),
            "unconverged_discard_loss_races": sum(g["candidate_hits"] > 0 for g in by_state["PLAY_UNCONVERGED_4PLUS"]),
            "unconverged_discard_loss_top3": sum(g["candidate_hits"] for g in by_state["PLAY_UNCONVERGED_4PLUS"]),
            "skip_gate_loss_races": sum(g["candidate_hits"] > 0 for g in by_state["SKIP"]),
            "skip_gate_loss_top3": sum(g["candidate_hits"] for g in by_state["SKIP"]),
            "selection_failure_races": sum(not any(hit(r) for r in g["buy"]) and (any(hit(r) for r in g["score"][:len(g["buy"])]) or any(hit(r) for r in g["pl"][:len(g["buy"])])) for g in by_state["PLAY_CONVERGED"]),
            "no_available_signal_races": sum(g["candidate_hits"] == 0 and not hit(g["score"][0]) and not hit(g["pl"][0]) for g in groups),
            "classification_note": "Mechanisms overlap; counts are not a mutually exclusive partition. No new rule is implied."}
    dump(OUT / "gate_loss_decomposition.json", loss)

    same = by_state["PLAY_CONVERGED"]
    paired = {}
    for comparator in ("score", "pl"):
        wins = losses = ties = 0
        for g in same:
            k = len(g["buy"])
            delta = sum(hit(r) for r in g[comparator][:k]) - sum(hit(r) for r in g["buy"])
            wins += delta > 0
            losses += delta < 0
            ties += delta == 0
        paired[comparator] = {"comparator_wins": wins, "current_buy_wins": losses, "ties": ties}
    current_buy = topk_metric(same, "buy", "actual_k")
    ordering = {"same_race_same_k_population_races": len(same), "current_buy": current_buy,
                "current_score_topk": topk_metric(same, "score", "actual_k"),
                "pl_topk": topk_metric(same, "pl", "actual_k"), "race_level_paired": paired,
                "all_race": {"current_rank1": topk_metric(groups, "score", 1), "pl_rank1": topk_metric(groups, "pl", 1),
                             "current_rank1_to_3": topk_metric(groups, "score", 3), "pl_rank1_to_3": topk_metric(groups, "pl", 3)},
                "metric_note": "Rates use valid selected horses as denominator. PL is corrected frozen p_hgb, not p_pl."}
    for comparator in ("current_score_topk", "pl_topk"):
        ordering[comparator]["raw_hit_difference_vs_current_buy"] = ordering[comparator]["top3_hits"] - current_buy["top3_hits"]
        ordering[comparator]["rate_difference_pt_vs_current_buy"] = 100 * (ordering[comparator]["top3_rate"] - current_buy["top3_rate"])
    dump(OUT / "current_vs_pl_ordering.json", ordering)

    stability = {}
    for dimension, key in (("month", lambda g: g["month"]), ("venue", lambda g: g["venue"]),
                           ("candidate_count_bucket", lambda g: str(len(g["candidate"])) if len(g["candidate"]) <= 6 else "7+"),
                           ("race_state", lambda g: g["state"])):
        values = defaultdict(list)
        for g in groups:
            values[key(g)].append(g)
        stability[dimension] = {k: {**group_metric(v), "unconverged_discard_loss_races": sum(x["state"] == "PLAY_UNCONVERGED_4PLUS" and x["candidate_hits"] > 0 for x in v)} for k, v in sorted(values.items())}
    dump(OUT / "temporal_stability.json", stability)

    # Freeze descriptive primary findings before any secondary outcome access.
    root_counts = [{"category": "UNCONVERGED_4PLUS_SEMANTICS", "affected_races": loss["unconverged_discard_loss_races"], "observed_candidate_top3": loss["unconverged_discard_loss_top3"]},
                   {"category": "CANDIDATE_GENERATION", "affected_races": loss["candidate_generation_failure_races"], "field_top3_outside_candidate_only_races": loss["candidate_generation_failure_field_top3"]},
                   {"category": "HORSE_ORDERING", "affected_races": loss["selection_failure_races"], "same_k_pl_hit_difference": ordering["pl_topk"]["raw_hit_difference_vs_current_buy"]},
                   {"category": "SKIP_LOGIC", "affected_races": loss["skip_gate_loss_races"], "observed_candidate_top3": loss["skip_gate_loss_top3"]}]
    findings = {"role": "DEVELOPMENT_MECHANISM_DIAGNOSTIC_ONLY", "population": {"races": 951, "dates": 53},
                "source_authority": authority, "state_counts": {s: len(v) for s, v in by_state.items()},
                "candidate_generation_failure_rate": rate(loss["candidate_generation_failure_races"], len(groups)),
                "mechanism_findings": loss, "ordering": ordering,
                "provisional_root_cause_ranking": sorted(root_counts, key=lambda x: -x["affected_races"]),
                "candidate_hypotheses": ["Current candidate generation can omit actual Top3 horses before Stage B.",
                                         "The 4+ convergence gate can discard races containing useful Current candidates.",
                                         "Within BUY-positive races, ranking differences may alter same-volume Top3 coverage."],
                "new_rule": None, "new_threshold": None, "implementation_proposal": None,
                "secondary_outcomes_accessed_before_this_freeze": False, "formal_evidence_credit": 0}
    frozen = OUT / "primary_findings_951_frozen.json"
    dump(frozen, findings)
    (OUT / "primary_findings_951_frozen.sha256").write_text(sha(frozen) + "\n", encoding="ascii")
    print(json.dumps({"primary_findings_sha256": sha(frozen), "states": findings["state_counts"],
                      "candidate_failure_rate": findings["candidate_generation_failure_rate"],
                      "loss": loss, "ordering": ordering}, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] != "--primary":
        raise SystemExit("Only --primary is implemented in this entry point")
    primary()
