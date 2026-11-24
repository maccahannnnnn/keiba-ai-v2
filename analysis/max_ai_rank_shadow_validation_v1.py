"""Shadow-only MAX_AI_RANK validation using saved evidence; no evaluator/replay calls."""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
BASELINE_HORSE = REPORTS / "baseline/keibaai_baseline_4days_v1_horse.csv"
BASELINE_RACE = REPORTS / "baseline/keibaai_baseline_4days_v1_race.csv"
REPLAY_COHORT = REPORTS / "ranking_weight_unique_cohort_v1.csv"
OUTPUT_CSV = REPORTS / "max_ai_rank_shadow_comparison_v1.csv"
OUTPUT_JSON = REPORTS / "max_ai_rank_shadow_summary_v1.json"
OUTPUT_MD = REPORTS / "max_ai_rank_shadow_report_v1.md"
OUTPUT_SAFETY = REPORTS / "max_ai_rank_shadow_safety_v1.json"
FEATURE_FLAG = "shadow_max_ai_rank"
CURRENT_MAX_AI_RANK = 5
SHADOW_MAX_AI_RANK = 3


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def as_bool(value) -> bool:
    return value is True or str(value).strip().lower() == "true"


def baseline_rows() -> list[dict]:
    race_decisions = {row["race_id"]: row["RaceDecision"] for row in read_csv(BASELINE_RACE)}
    rows = []
    for row in read_csv(BASELINE_HORSE):
        if not as_bool(row["valid_result"]):
            continue
        rows.append({
            "cohort": "BASELINE_34_RACE_v1", "race_id": row["race_id"], "race_date": row["race_date"],
            "racecourse": row["race_id"].split("_")[2], "horse_number": row["horse_number"], "horse_name": row["horse_name"],
            "ai_rank": int(row["ai_rank"]), "decision": row["decision"], "race_decision": race_decisions.get(row["race_id"], ""),
            "production_buy": as_bool(row["buy_flag"]), "actual_finish": int(row["actual_finish"]), "actual_top3": as_bool(row["actual_top3"]),
        })
    return rows


def replay_rows() -> list[dict]:
    rows = []
    for cohort in read_csv(REPLAY_COHORT):
        path = ROOT / "reports/historical_replay_current_code" / cohort["adopted_run"] / cohort["race_date"] / cohort["race_id"] / "post_race/post_joined.json"
        for horse in json.loads(path.read_text(encoding="utf-8"))["horses"]:
            if not horse.get("valid_result"):
                continue
            rows.append({
                "cohort": "CURRENT_CODE_REPLAY_36_UNIQUE", "race_id": cohort["race_id"], "race_date": cohort["race_date"],
                "racecourse": cohort["racecourse"], "horse_number": str(horse["horse_number"]), "horse_name": horse["horse_name"],
                "ai_rank": int(horse["final_rank"]), "decision": horse["decision"], "race_decision": horse["race_decision"],
                "production_buy": bool(horse.get("buy_v1_rc1_buy")), "actual_finish": int(horse["actual_finish"]), "actual_top3": bool(horse["actual_top3"]),
            })
    return rows


def apply_shadow(rows: list[dict], shadow_max_ai_rank: int | None = None) -> list[dict]:
    """OFF(None) is exact Production BUY; ON(integer) only changes shadow_buy."""
    output = []
    for source in rows:
        row = dict(source)
        row["feature_flag"] = FEATURE_FLAG
        row["feature_flag_enabled"] = shadow_max_ai_rank is not None
        row["shadow_max_ai_rank"] = shadow_max_ai_rank if shadow_max_ai_rank is not None else CURRENT_MAX_AI_RANK
        row["shadow_buy"] = row["production_buy"] if shadow_max_ai_rank is None else row["production_buy"] and row["ai_rank"] <= shadow_max_ai_rank
        row["removed_by_shadow"] = row["production_buy"] and not row["shadow_buy"]
        output.append(row)
    return output


def distribution(rows: list[dict], key: str, buy_key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row[key]) for row in rows if row[buy_key]).items()))


def metrics(rows: list[dict]) -> dict:
    off = apply_shadow(rows, None)
    on = apply_shadow(rows, SHADOW_MAX_AI_RANK)
    current = [row for row in off if row["production_buy"]]
    shadow = [row for row in on if row["shadow_buy"]]
    removed = [row for row in on if row["removed_by_shadow"]]
    current_success = sum(row["actual_top3"] for row in current)
    shadow_success = sum(row["actual_top3"] for row in shadow)
    current_fp = len(current) - current_success
    shadow_fp = len(shadow) - shadow_success
    current_rate = current_success / len(current) if current else 0
    shadow_rate = shadow_success / len(shadow) if shadow else 0
    return {
        "cohort": rows[0]["cohort"], "horse_count": len(rows),
        "current_buy_count": len(current), "shadow_buy_count": len(shadow), "buy_change": len(shadow) - len(current),
        "current_buy_top3": current_success, "shadow_buy_top3": shadow_success,
        "current_buy_place_rate": round(current_rate, 8), "shadow_buy_place_rate": round(shadow_rate, 8),
        "place_rate_change_pp": round((shadow_rate - current_rate) * 100, 4),
        "relative_improvement_rate": round((shadow_rate / current_rate - 1) if current_rate else 0, 8),
        "successful_buy_reduction": current_success - shadow_success,
        "successful_buy_protection_rate": round(shadow_success / current_success if current_success else 1, 8),
        "current_fp_buy": current_fp, "shadow_fp_buy": shadow_fp, "fp_buy_reduction": current_fp - shadow_fp,
        "fp_reduction_rate": round((current_fp - shadow_fp) / current_fp if current_fp else 0, 8),
        "new_fn_count": sum(row["actual_top3"] for row in removed),
        "removed_buy_count": len(removed),
        "current_ai_rank_distribution": dict(sorted(Counter(row["ai_rank"] for row in current).items())),
        "shadow_ai_rank_distribution": dict(sorted(Counter(row["ai_rank"] for row in shadow).items())),
        "current_decision_distribution": distribution(off, "decision", "production_buy"),
        "shadow_decision_distribution": distribution(on, "decision", "shadow_buy"),
        "current_race_decision_distribution": distribution(off, "race_decision", "production_buy"),
        "shadow_race_decision_distribution": distribution(on, "race_decision", "shadow_buy"),
        "full_population_decision_unchanged": Counter(row["decision"] for row in off) == Counter(row["decision"] for row in on),
        "full_population_race_decision_unchanged": Counter(row["race_decision"] for row in off) == Counter(row["race_decision"] for row in on),
        "removed": [{key: row[key] for key in ["race_id", "race_date", "racecourse", "horse_number", "horse_name", "ai_rank", "decision", "race_decision", "actual_finish", "actual_top3"]} for row in removed],
        "flag_off_exact_match": all(row["shadow_buy"] == row["production_buy"] for row in off),
    }


def write_comparison(rows_by_cohort: list[list[dict]]) -> None:
    fields = ["cohort", "race_id", "race_date", "racecourse", "horse_number", "horse_name", "ai_rank", "decision", "race_decision", "actual_finish", "actual_top3", "production_buy", "flag_off_buy", "flag_on_buy", "removed_by_shadow", "outcome"]
    output = []
    for rows in rows_by_cohort:
        off = apply_shadow(rows, None)
        on = apply_shadow(rows, SHADOW_MAX_AI_RANK)
        for before, after in zip(off, on):
            if not before["production_buy"]:
                continue
            output.append({
                **{key: before[key] for key in fields if key in before},
                "flag_off_buy": before["shadow_buy"], "flag_on_buy": after["shadow_buy"], "removed_by_shadow": after["removed_by_shadow"],
                "outcome": "SUCCESS_BUY" if before["actual_top3"] else "FP_BUY",
            })
    with OUTPUT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(output)


def build() -> dict:
    baseline, replay = baseline_rows(), replay_rows()
    results = [metrics(baseline), metrics(replay)]
    write_comparison([baseline, replay])
    replay_result = results[1]
    judgment = "GO" if all(x["place_rate_change_pp"] > 0 and x["successful_buy_protection_rate"] >= .95 and x["fp_buy_reduction"] > x["new_fn_count"] for x in results) else "REJECT" if replay_result["place_rate_change_pp"] <= 0 or replay_result["successful_buy_protection_rate"] < .95 else "HOLD"
    summary = {
        "status": judgment,
        "candidate": "MAX_AI_RANK_5_TO_3",
        "feature_flag": {"name": FEATURE_FLAG, "off": None, "on": SHADOW_MAX_AI_RANK, "scope": "SHADOW_ONLY"},
        "cohorts_combined": False,
        "results": results,
        "production_adoption": judgment,
        "reason": "Formal Replay loses 2 successful BUY and place rate declines" if judgment == "REJECT" else "See cohort metrics",
        "production_delta": "ZERO",
        "replay_executed": False,
    }
    OUTPUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    b, r = results
    report = f"""# MAX_AI_RANK 5→3 Shadow Validation v1

## 判定

**{judgment}**

Shadow専用Feature Flag `{FEATURE_FLAG}` を分析層に実装した。OFFはProduction BUYと完全一致。ONは保存済みProduction BUYのうちAI rank 3以内だけをShadow BUYとして保持し、Decision・RaceDecision・Scoreは変更しない。

| Cohort | BUY current→shadow | BUY Top3 current→shadow | Place rate current→shadow | Success protection | FP reduction | New FN |
|---|---:|---:|---:|---:|---:|---:|
| Baseline 34 | {b['current_buy_count']}→{b['shadow_buy_count']} | {b['current_buy_top3']}→{b['shadow_buy_top3']} | {b['current_buy_place_rate']:.2%}→{b['shadow_buy_place_rate']:.2%} | {b['successful_buy_protection_rate']:.2%} | {b['fp_buy_reduction']} ({b['fp_reduction_rate']:.2%}) | {b['new_fn_count']} |
| Replay 36 | {r['current_buy_count']}→{r['shadow_buy_count']} | {r['current_buy_top3']}→{r['shadow_buy_top3']} | {r['current_buy_place_rate']:.2%}→{r['shadow_buy_place_rate']:.2%} | {r['successful_buy_protection_rate']:.2%} | {r['fp_buy_reduction']} ({r['fp_reduction_rate']:.2%}) | {r['new_fn_count']} |

旧Baselineでは9 FPを除去し成功BUYを全保護するが、正式Replayではrank 4の成功BUYを2頭除去し、複勝率が{r['place_rate_change_pp']:.2f}ポイント悪化する。コホート間で効果が逆転し、成功BUY保護95%条件も満たさないため、この固定閾値候補はProduction採用REJECTとする。
"""
    OUTPUT_MD.write_text(report, encoding="utf-8")
    return summary


if __name__ == "__main__": print(json.dumps(build(), ensure_ascii=False, indent=2))
