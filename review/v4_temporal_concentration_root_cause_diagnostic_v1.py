"""Post-hoc, artifact-only concentration diagnostic for V4 May/March evidence.

This utility intentionally reads only the already-consumed PRE/POST artifacts
named below.  It neither opens raw result sources nor invokes prediction,
counterfactual, model-training, or production code.
"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "v4_temporal_concentration_root_cause_diagnostic_v1"
MAY_PRE = ROOT / "reports" / "may_2026_multi_system_oos_v1" / "pre_retry_v5"
MAY_POST = ROOT / "reports" / "may_2026_multi_system_oos_v1" / "post_v1"
MARCH = ROOT / "reports" / "march_2026_historical_holdout_post"

COURSE_CODES = {
    "sapporo": "01", "hakodate": "02", "fukushima": "03", "niigata": "04",
    "tokyo": "05", "nakayama": "06", "chuukyou": "07", "kyoto": "08",
    "hanshin": "09", "kokura": "10",
}


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> object:
    if not path.is_file():
        raise Stop(f"REQUIRED_ARTIFACT_MISSING:{path.relative_to(ROOT)}")
    return json.loads(path.read_text(encoding="utf-8"))


def dump(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def git_value(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def metric(rows: list[dict]) -> dict:
    valid = [r for r in rows if r["valid_result"]]
    hits = sum(1 for r in valid if r["actual_top3"])
    return {
        "selected_count": len(rows), "valid_selected_count": len(valid),
        "top3_hits": hits, "top3_rate": hits / len(valid) if valid else None,
        "invalid_selected_count": len(rows) - len(valid),
    }


def contribution_by_date(races: list[dict]) -> list[dict]:
    per_date: dict[str, list[dict]] = defaultdict(list)
    for row in races:
        per_date[row["date"]].append(row)
    result = []
    for date in sorted(per_date):
        group = per_date[date]
        current = metric([x for r in group for x in r["current"]])
        v4 = metric([x for r in group for x in r["v4"]])
        result.append({
            "date": date, "race_count": len(group), "current": current, "v4": v4,
            "raw_hit_difference": v4["top3_hits"] - current["top3_hits"],
            "lift_percentage_points": None if current["top3_rate"] is None or v4["top3_rate"] is None
            else (v4["top3_rate"] - current["top3_rate"]) * 100,
        })
    return result


def concentration(races: list[dict], expected: dict) -> dict:
    daily = contribution_by_date(races)
    removed_count = math.ceil(len(daily) / 3)
    ordered = sorted(daily, key=lambda x: (-x["raw_hit_difference"], x["date"]))
    removed = ordered[:removed_count]
    removed_dates = {x["date"] for x in removed}
    remaining = [r for r in races if r["date"] not in removed_dates]
    current = metric([x for r in remaining for x in r["current"]])
    v4 = metric([x for r in remaining for x in r["v4"]])
    result = {
        "definition": "date contribution = V4 valid top3 hits - Current valid top3 hits; sort descending then date ASC; remove ceil(n_dates/3)",
        "date_count": len(daily), "removed_date_count": removed_count,
        "date_contributions": daily, "sort_order": [x["date"] for x in ordered],
        "removed_dates": [x["date"] for x in removed], "removed_date_records": removed,
        "remaining": {"current": current, "v4": v4,
                      "raw_hit_difference": v4["top3_hits"] - current["top3_hits"],
                      "lift_percentage_points": (v4["top3_rate"] - current["top3_rate"]) * 100},
        "concentration_flag": (v4["top3_hits"] - current["top3_hits"]) <= 0,
    }
    for key, value in expected.items():
        actual = result["remaining"].get(key, result.get(key))
        if isinstance(value, float):
            if actual is None or abs(actual - value) > 1e-9:
                raise Stop(f"CONCENTRATION_EXPECTATION_MISMATCH:{key}:{actual}:{value}")
        elif actual != value:
            raise Stop(f"CONCENTRATION_EXPECTATION_MISMATCH:{key}:{actual}:{value}")
    return result


def axis(races: list[dict], axis_name: str, bucket_for) -> dict:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in races:
        buckets[str(bucket_for(row))].append(row)
    rows = []
    for bucket in sorted(buckets, key=lambda x: (0, float(x)) if x.replace('.', '', 1).isdigit() else (1, x)):
        group = buckets[bucket]
        cur = metric([x for r in group for x in r["current"]])
        v4 = metric([x for r in group for x in r["v4"]])
        diffs = [sum(x["actual_top3"] and x["valid_result"] for x in r["v4"]) - sum(x["actual_top3"] and x["valid_result"] for x in r["current"]) for r in group]
        rows.append({"bucket": bucket, "race_count": len(group), "current": cur, "v4": v4,
                     "raw_hit_difference": sum(diffs), "mean_contribution_per_race": sum(diffs) / len(diffs),
                     "positive_race_count": sum(d > 0 for d in diffs), "negative_race_count": sum(d < 0 for d in diffs),
                     "zero_race_count": sum(d == 0 for d in diffs)})
    total = sum(x["raw_hit_difference"] for x in rows)
    overall = sum(sum(x["actual_top3"] and x["valid_result"] for x in r["v4"]) - sum(x["actual_top3"] and x["valid_result"] for x in r["current"]) for r in races)
    if total != overall:
        raise Stop(f"AXIS_ACCOUNTING_MISMATCH:{axis_name}:{total}:{overall}")
    return {"axis": axis_name, "buckets": rows, "raw_difference_reconciliation": {"axis_sum": total, "overall": overall, "pass": True}}


def combine_buckets(axis_result: dict, predicate) -> dict:
    selected = [x for x in axis_result["buckets"] if predicate(x["bucket"])]
    return {"bucket_count": len(selected), "race_count": sum(x["race_count"] for x in selected),
            "raw_hit_difference": sum(x["raw_hit_difference"] for x in selected),
            "mean_contribution_per_race": (sum(x["raw_hit_difference"] for x in selected) / sum(x["race_count"] for x in selected)) if sum(x["race_count"] for x in selected) else None}


def sign(value: int) -> str:
    return "POSITIVE" if value > 0 else "NEGATIVE" if value < 0 else "ZERO"


def classify_hypothesis(hypothesis_id: str, title: str, may: dict, march: dict) -> dict:
    a, b = sign(may["raw_hit_difference"]), sign(march["raw_hit_difference"])
    if a == b and a != "ZERO":
        status = "STRONGER_REPLICATED_HYPOTHESIS"
    elif a != "ZERO" and b == "ZERO" or a == "ZERO" and b != "ZERO":
        status = "SINGLE_COHORT_HYPOTHESIS"
    elif a != b and a != "ZERO" and b != "ZERO":
        status = "CONTRADICTORY"
    else:
        status = "INSUFFICIENT"
    return {"hypothesis_id": hypothesis_id, "predefined_structural_question": title,
            "may": may, "march": march, "classification": status,
            "evidence_limit": "POST_HOC_DIAGNOSTIC_ONLY; classification is not a gate, rule, or deployment recommendation."}


def may_races() -> tuple[list[dict], dict[str, str]]:
    current_path, v4_path, cross_path, primary_path, lodo_path = (
        MAY_PRE / "current_ai_pre.json", MAY_PRE / "v4_reselection_pre.json",
        MAY_POST / "result_crosscheck_validation.json", MAY_POST / "v4_primary_evaluation.json", MAY_POST / "v4_lodo_diagnostic.json")
    current = read(current_path)["races"]
    selections = read(v4_path)["selections"]
    cross = read(cross_path)["records"]
    expected_primary = read(primary_path)
    read(lodo_path)  # Required same-volume consumed artifact; results are re-derived below.
    selection_by_race = {x["race_id"]: [int(n) for n in x["selected"]] for x in selections}
    if len(selection_by_race) != len(selections):
        raise Stop("MAY_V4_SELECTION_RACE_DUPLICATE")
    cross_by_key = {x["target_race_key"]: x for x in cross}
    races = []
    for item in current:
        parts = item["race_id"].split("_")
        if len(parts) != 4 or not parts[3].endswith("R") or parts[2] not in COURSE_CODES:
            raise Stop(f"MAY_RACE_ID_INVALID:{item['race_id']}")
        key_prefix = item["date"] + COURSE_CODES[parts[2]]
        race_no = int(parts[3][:-1])
        matches = [key for key in cross_by_key if key.startswith(key_prefix) and int(key[-2:]) == race_no]
        if len(matches) != 1:
            raise Stop(f"MAY_POST_RESULT_MAP_AMBIGUOUS:{item['race_id']}:{len(matches)}")
        finish = cross_by_key[matches[0]]["normal_finish_groups"]
        top3 = {int(n) for rank in ("1", "2", "3") for n in finish.get(rank, [])}
        cur_set = {int(n) for n in item["current_buy"]}
        v4_set = set(selection_by_race.get(item["race_id"], []))
        if len(cur_set) != len(v4_set):
            raise Stop(f"MAY_SAME_VOLUME_VIOLATION:{item['race_id']}:{len(cur_set)}:{len(v4_set)}")
        races.append({"date": item["date"], "race_id": item["race_id"], "venue": parts[2], "current": [{"horse_number": n, "valid_result": True, "actual_top3": n in top3} for n in sorted(cur_set)], "v4": [{"horse_number": n, "valid_result": True, "actual_top3": n in top3} for n in sorted(v4_set)]})
    cur, v4 = metric([x for r in races for x in r["current"]]), metric([x for r in races for x in r["v4"]])
    for calculated, recorded in ((cur, expected_primary["current"]), (v4, expected_primary["v4"])):
        if (calculated["selected_count"], calculated["valid_selected_count"], calculated["top3_hits"], calculated["invalid_selected_count"], calculated["top3_rate"]) != (recorded["selected_count"], recorded["valid_selected_count"], recorded["top3_count"], recorded["invalid_result_count"], recorded["top3_rate"]):
            raise Stop(f"MAY_PRIMARY_METRIC_REPRODUCTION_FAILURE:calculated={calculated}:recorded={recorded}")
    sources = {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in [current_path, v4_path, cross_path, primary_path, lodo_path]}
    return races, sources


def march_races() -> tuple[list[dict], dict[str, str]]:
    current_path, v4_path, daily_path, stress_path = (MARCH / "current_same_volume_result.json", MARCH / "v4_model_v3_same_volume_result.json", MARCH / "daily_metrics.json", MARCH / "temporal_concentration_stress_test.json")
    current, v4 = read(current_path)["records"], read(v4_path)["records"]
    read(daily_path); read(stress_path)
    by_race: dict[str, dict] = {}
    for label, rows in (("current", current), ("v4", v4)):
        for row in rows:
            bucket = by_race.setdefault(row["race_id"], {"date": row["date"], "race_id": row["race_id"], "venue": row["venue"], "current": [], "v4": []})
            if bucket["date"] != row["date"] or bucket["venue"] != row["venue"]:
                raise Stop(f"MARCH_RACE_IDENTITY_FAILURE:{row['race_id']}")
            bucket[label].append({"horse_number": int(row["horse_number"]), "valid_result": bool(row["valid_result"]), "actual_top3": bool(row["actual_top3"])})
    races = list(by_race.values())
    for row in races:
        if len(row["current"]) != len(row["v4"]):
            raise Stop(f"MARCH_SAME_VOLUME_VIOLATION:{row['race_id']}")
        if len({x["horse_number"] for x in row["current"]}) != len(row["current"]) or len({x["horse_number"] for x in row["v4"]}) != len(row["v4"]):
            raise Stop(f"MARCH_SELECTION_DUPLICATE:{row['race_id']}")
    sources = {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in [current_path, v4_path, daily_path, stress_path]}
    return races, sources


def main() -> None:
    if OUT.exists():
        raise Stop(f"OUTPUT_ALREADY_EXISTS:{OUT.relative_to(ROOT)}")
    before_head, before_status = git_value("rev-parse", "HEAD"), git_value("status", "--porcelain")
    may, may_sources = may_races()
    march, march_sources = march_races()
    may_conc = concentration(may, {"raw_hit_difference": -2})
    if may_conc["removed_dates"] != ["20260502", "20260503", "20260510", "20260509"] or may_conc["remaining"]["current"]["top3_hits"] != 31 or may_conc["remaining"]["v4"]["top3_hits"] != 29 or may_conc["remaining"]["current"]["valid_selected_count"] != 94 or may_conc["remaining"]["v4"]["valid_selected_count"] != 94:
        raise Stop("MAY_CONCENTRATION_RECALCULATION_MISMATCH")
    march_conc = concentration(march, {"raw_hit_difference": 0})
    if march_conc["removed_dates"] != ["20260328", "20260307", "20260321"] or march_conc["remaining"]["current"]["top3_hits"] != 28 or march_conc["remaining"]["v4"]["top3_hits"] != 28 or march_conc["remaining"]["current"]["valid_selected_count"] != 78 or march_conc["remaining"]["v4"]["valid_selected_count"] != 79:
        raise Stop("MARCH_CONCENTRATION_RECALCULATION_MISMATCH")

    def volume(r): return len(r["current"])
    def current_only(r): return len({x["horse_number"] for x in r["current"]} - {x["horse_number"] for x in r["v4"]})
    def overlap(r):
        cur = {x["horse_number"] for x in r["current"]}; v4 = {x["horse_number"] for x in r["v4"]}
        return f"{len(cur & v4) / len(cur):.2f}" if cur else "NOT_SELECTED"
    for cohort, rows in (("may", may), ("march", march)):
        if any(volume(x) > 3 for x in rows) or any(current_only(x) > 3 for x in rows):
            raise Stop(f"{cohort.upper()}_UNEXPECTED_SELECTION_CAPACITY")
    decomp = {
        "buy_volume": {"may": axis(may, "buy_volume", volume), "march": axis(march, "buy_volume", volume)},
        "replacement_depth": {"may": axis(may, "current_only_count", current_only), "march": axis(march, "current_only_count", current_only)},
        "overlap": {"may": axis(may, "overlap_ratio", overlap), "march": axis(march, "overlap_ratio", overlap)},
        "venue_surface_distance": {"may": axis(may, "venue", lambda r: r["venue"]), "march": axis(march, "venue", lambda r: r["venue"]), "surface": "NOT_EVALUABLE_FROM_ALLOWED_SAME_VOLUME_ARTIFACTS", "distance": "NOT_EVALUABLE_FROM_ALLOWED_SAME_VOLUME_ARTIFACTS", "distance_band": "NOT_CREATED"},
    }
    def split_stats(rows, conc):
        removed = set(conc["removed_dates"])
        return {"removed_high_contribution_dates": {"date_count": len(removed), "buy_volume": axis([r for r in rows if r["date"] in removed], "buy_volume", volume), "replacement_depth": axis([r for r in rows if r["date"] in removed], "current_only_count", current_only), "overlap": axis([r for r in rows if r["date"] in removed], "overlap_ratio", overlap)}, "remaining_dates": {"date_count": len({r['date'] for r in rows if r['date'] not in removed}), "buy_volume": axis([r for r in rows if r["date"] not in removed], "buy_volume", volume), "replacement_depth": axis([r for r in rows if r["date"] not in removed], "current_only_count", current_only), "overlap": axis([r for r in rows if r["date"] not in removed], "overlap_ratio", overlap)}}
    winning_remaining = {"may": split_stats(may, may_conc), "march": split_stats(march, march_conc)}
    hypotheses = [
        classify_hypothesis("H1", "BUY数1頭レースでの寄与差", combine_buckets(decomp["buy_volume"]["may"], lambda b: b == "1"), combine_buckets(decomp["buy_volume"]["march"], lambda b: b == "1")),
        classify_hypothesis("H2", "置換深度1頭以上のレースでの寄与差", combine_buckets(decomp["replacement_depth"]["may"], lambda b: int(b) >= 1), combine_buckets(decomp["replacement_depth"]["march"], lambda b: int(b) >= 1)),
    ]
    scope = {"status": "POST_HOC_DIAGNOSTIC_ONLY", "allowed_evidence": {"may": may_sources, "march": march_sources}, "forbidden_access": ["2026-08-30 results", "raw result CSV", "CF results", "February", "new prediction", "new holdout", "model training"], "may_evidence_role": "MAY_RETROSPECTIVE_CONCENTRATION_DIAGNOSTIC_USING_LATER_FROZEN_DEFINITION", "march_evidence_role": "INDEPENDENT_HISTORICAL_HOLDOUT_POST_HOC_DIAGNOSTIC"}
    evidence_boundary = {"not_supported": ["uniform +6 claim", "immediate subgroup gate", "Production deployment", "feature or threshold change", "Model V3 retraining"], "permitted_future_use": "Hypothesis generation only. Any later subgroup test requires a separately preregistered diagnostic/protocol.", "feature_v3_boundary": "No feature addition, removal, interaction, coefficient, or threshold decision is made by this diagnostic."}
    OUT.mkdir(parents=True)
    dump("scope.json", scope); dump("may_concentration_recalculation.json", may_conc); dump("march_concentration_recalculation.json", march_conc)
    dump("buy_volume_decomposition.json", decomp["buy_volume"]); dump("replacement_depth_decomposition.json", decomp["replacement_depth"]); dump("overlap_decomposition.json", decomp["overlap"]); dump("venue_surface_distance_decomposition.json", decomp["venue_surface_distance"])
    dump("winning_vs_remaining_dates.json", winning_remaining); dump("cross_cohort_replication.json", {"hypotheses": hypotheses}); dump("hypotheses.json", {"predefined_hypotheses": hypotheses, "max_hypotheses": 3}); dump("evidence_boundary.json", evidence_boundary)
    after_head, after_status = git_value("rev-parse", "HEAD"), git_value("status", "--porcelain")
    source_after = {**{p: sha(ROOT / p) for p in may_sources}, **{p: sha(ROOT / p) for p in march_sources}}
    if after_head != before_head or any(source_after[p] != h for p, h in {**may_sources, **march_sources}.items()):
        raise Stop("SAFETY_SOURCE_OR_HEAD_MUTATION")
    safety = {"status": "PASS", "git_head_before": before_head, "git_head_after": after_head, "git_status_before": before_status, "git_status_after": after_status, "source_artifacts_unchanged": True, "production_changes": 0, "current_ai_changes": 0, "model_v3_changes": 0, "dataset_v3_changes": 0, "cf_changes": 0, "prospective_protocol_changes": 0, "march_gate_changes": 0, "may_oos_verdict_changes": 0, "raw_result_access_count": 0, "prediction_execution_count": 0, "model_fit_count": 0}
    dump("safety.json", safety)
    report = """# V4 Temporal Concentration Root Cause Diagnostic v1

## 結論

本成果物は、既に消費済みのMay V4 Model v2同量選択・POST成果物と、March V4 Model v3同量POST成果物を用いた**事後診断**です。新しいPrediction、Result取得、CF評価、Model fit、Production変更は行っていません。

- Mayは後から凍結された定義を用いる retrospective concentration diagnostic であり、Mayの正式OOS verdictを変更しません。
- Marchは独立Historical Holdoutの事後構造診断です。
- 軸別集計は、各コホート内で全体のraw hit差に必ず再一致しています。
- surface・distance・共通score構造は、許可された同量POST/selection artifactの両コホート共通値ではないため評価していません。

## Concentration recalculation

Mayは日別寄与順（同値は日付昇順）で4日を除外し、残りはCurrent 31/94、V4 29/94、raw差 -2、lift -2.1277ptです。除外日は 2026-05-02, 2026-05-03, 2026-05-10, 2026-05-09 です。

Marchは3日を除外し、残りはCurrent 28/78、V4 28/79、raw差 0、lift -0.4544ptです。除外日は 2026-03-28, 2026-03-07, 2026-03-21 です。

## Boundary

この診断は「V4が常に+6pt」「特定subgroup gateを直ちに導入」「Productionへ配備」を支持しません。仮説が残っても、将来使用するには独立に事前登録したsubgroup diagnostic/protocolが必要です。
"""
    (OUT / "report.md").write_text(report, encoding="utf-8")
    hashes = {str(p.relative_to(OUT)).replace("\\", "/"): sha(p) for p in sorted(OUT.iterdir()) if p.is_file() and p.name != "artifact_hashes.json"}
    dump("artifact_hashes.json", {"status": "PASS", "self_hash_excluded": True, "artifacts": hashes})


if __name__ == "__main__":
    main()
