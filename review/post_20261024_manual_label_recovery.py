"""Additive 2026-10-24 POST classification from human-attested pre-Result notes."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from review.post_20261024_multi_ai_family_manual import ROOT, OUT, metrics, sha


AUTHORITY = Path(r"C:\Users\hikar\.codex\attachments\385a3a12-f30d-4d04-b46f-37d5a82b1208\貼り付けたテキスト.txt")
DEST = OUT / "manual_recovery_v1"

GROUPS = {
    "STRONG_SUPPORT": {
        "kyoto_6R": {1: "ダイヤモンド"}, "kyoto_7R": {10: "エイコーンドリーム"},
        "kyoto_8R": {4: "アーリーハーベスト"}, "kyoto_12R": {2: "セイントホース"},
        "tokyo_10R": {12: "サムシャイン"}, "niigata_12R": {16: "ノアールビーナス"},
    },
    "SUPPORT": {
        "kyoto_6R": {12: "カネコメファミリー"},
        "kyoto_7R": {7: "リーチグローリー", 4: "アンリーベイビー"},
        "kyoto_8R": {7: "ウインリベラシオン", 3: "ユメハハテシナク"},
        "kyoto_12R": {1: "ソウルアンドジャズ", 6: "エアアルチーナ"},
        "tokyo_10R": {10: "リフレックス"},
        "niigata_6R": {3: "ヴァカンツァ", 8: "シスター", 12: "メリフルアス"},
        "niigata_10R": {11: "ヴァイヴァーイ"}, "niigata_12R": {1: "リアライズリバティ"},
    },
    "SUPPORTED_WITH_EXPLICIT_CAUTION": {
        "niigata_10R": {6: "ファルコンミノル"}, "niigata_12R": {12: "ジョワイユノエル"},
    },
    "NEXT_CANDIDATE_WITH_CAUTION": {
        "kyoto_6R": {9: "ジーティームッシュ"}, "niigata_10R": {2: "ベルイストワール"},
    },
    "EXPLICIT_DISCOUNT": {
        "kyoto_12R": {5: "トモジャザーン"}, "kyoto_7R": {3: "エレーデサンライズ"},
        "niigata_6R": {2: "セヴェンヌ", 5: "ジャーナーリア"},
        "niigata_10R": {15: "ルーナディサングエ"},
    },
}
SHORTLIST_STANCES = {"STRONG_SUPPORT", "SUPPORT", "SUPPORTED_WITH_EXPLICIT_CAUTION"}
SUPPORT_STANCES = {"STRONG_SUPPORT", "SUPPORT"}
CAUTION_STANCES = {"SUPPORTED_WITH_EXPLICIT_CAUTION", "NEXT_CANDIDATE_WITH_CAUTION", "EXPLICIT_DISCOUNT"}


def dump(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def format_metric(m):
    return f"{m['top3_hits']}/{m['valid_n']} ({m['top3_rate']:.2%})" if m["top3_rate"] is not None else "0/0 (N/A)"


def main():
    if not AUTHORITY.is_file():
        raise RuntimeError("MANUAL_PRE_AUTHORITY_MISSING")
    pre_path = OUT / "pre_selection_snapshot.json"
    joined_path = OUT / "joined_horses.csv"
    post_path = OUT / "post_diagnostic.json"
    pre = json.loads(pre_path.read_text(encoding="utf-8"))
    post = json.loads(post_path.read_text(encoding="utf-8"))
    if pre["date"] != "20261024" or len(pre["horses"]) != 269 or post["pre_snapshot_sha256"] != sha(pre_path):
        raise RuntimeError("BASE_POST_OR_PRE_IDENTITY_MISMATCH")
    label_map = {}
    for stance, races in GROUPS.items():
        for race, horses in races.items():
            for number, name in horses.items():
                k = (f"race_20261024_{race}", number)
                if k in label_map:
                    raise RuntimeError(f"DUPLICATE_LABEL:{k}")
                label_map[k] = (name, stance)
    result_map = {}
    with joined_path.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            k = (r["race_id"], int(r["horse_number"]))
            if k in result_map:
                raise RuntimeError(f"DUPLICATE_JOIN_ROW:{k}")
            result_map[k] = r
    if len(result_map) != 269:
        raise RuntimeError("JOIN_POPULATION_NOT_269")
    rows = []
    for source in pre["horses"]:
        k = (source["race_id"], source["horse_number"])
        rr = result_map[k]
        name, stance = label_map.get(k, (source["horse_name"], "NOT_FORMALLY_CLASSIFIED"))
        if name != source["horse_name"] or rr["horse_name"] != name:
            raise RuntimeError(f"PRE_IDENTITY_MISMATCH:{k}:{name}:{source['horse_name']}")
        row = dict(source)
        row["manual_stance"] = stance
        row["manual_shortlist_included"] = stance in SHORTLIST_STANCES
        row["manual_next_candidate"] = stance == "NEXT_CANDIDATE_WITH_CAUTION"
        row["valid_result"] = rr["valid_result"] == "True"
        row["finish"] = int(rr["finish"]) if rr["finish"] else None
        row["actual_top3"] = (rr["actual_top3"] == "True") if row["valid_result"] else None
        rows.append(row)
    if len([r for r in rows if r["manual_shortlist_included"]]) != 21 or len([r for r in rows if r["manual_next_candidate"]]) != 2:
        raise RuntimeError("MANUAL_SHORTLIST_COUNTS_MISMATCH")
    def block(predicate):
        subset = [r for r in rows if predicate(r)]
        return {"metrics": metrics(subset),
                "horses": [{"race_id": r["race_id"], "horse_number": r["horse_number"],
                            "horse_name": r["horse_name"], "manual_stance": r["manual_stance"],
                            "manual_shortlist_included": r["manual_shortlist_included"],
                            "family_votes": r["family_votes"], "aj_rank": r["rank"]["ADAPTIVE_PL_JOCKEY"],
                            "finish": r["finish"], "actual_top3": r["actual_top3"]} for r in subset]}
    groups = {
        "A_3F_ALL": block(lambda r: r["family_votes"] == 3),
        "B1_3F_AND_PRIMARY_SHORTLIST": block(lambda r: r["family_votes"] == 3 and r["manual_shortlist_included"]),
        "B2_3F_AND_STRONG_OR_SUPPORT": block(lambda r: r["family_votes"] == 3 and r["manual_stance"] in SUPPORT_STANCES),
        "C_3F_AND_CAUTION_OR_DISCOUNT": block(lambda r: r["family_votes"] == 3 and r["manual_stance"] in CAUTION_STANCES),
        "D_2F_AND_STRONG_OR_SUPPORT": block(lambda r: r["family_votes"] == 2 and r["manual_stance"] in SUPPORT_STANCES),
        "E_1F_0F_MANUAL_ELEVATED": block(lambda r: r["family_votes"] <= 1 and r["manual_stance"] in SUPPORT_STANCES | {"NEXT_CANDIDATE_WITH_CAUTION"}),
        "E_NEXT_CANDIDATE_ONLY": block(lambda r: r["family_votes"] <= 1 and r["manual_next_candidate"]),
        "F_AJ_RANK1_AND_STRONG_OR_SUPPORT": block(lambda r: r["rank"]["ADAPTIVE_PL_JOCKEY"] == 1 and r["manual_stance"] in SUPPORT_STANCES),
        "G_AJ_TOP3_AND_STRONG_OR_SUPPORT": block(lambda r: r["rank"]["ADAPTIVE_PL_JOCKEY"] <= 3 and r["manual_stance"] in SUPPORT_STANCES),
        "MANUAL_PRIMARY_SHORTLIST": block(lambda r: r["manual_shortlist_included"]),
        "MANUAL_NEXT_CANDIDATE": block(lambda r: r["manual_next_candidate"]),
        "SPECIAL_3F_SUPPORT_SIDE": block(lambda r: r["family_votes"] == 3 and (r["race_id"], r["horse_number"]) in {
            ("race_20261024_kyoto_6R", 1), ("race_20261024_kyoto_6R", 12),
            ("race_20261024_tokyo_10R", 12), ("race_20261024_niigata_12R", 16)}),
        "SPECIAL_3F_CAUTION_SIDE": block(lambda r: r["family_votes"] == 3 and (r["race_id"], r["horse_number"]) in {
            ("race_20261024_kyoto_6R", 9), ("race_20261024_niigata_10R", 6),
            ("race_20261024_niigata_12R", 12)}),
    }
    stance_results = {stance: block(lambda r, stance=stance: r["manual_stance"] == stance)
                      for stance in (*GROUPS.keys(), "NOT_FORMALLY_CLASSIFIED")}
    race_ids = {f"race_20261024_{r}" for r in (
        "kyoto_6R", "kyoto_7R", "kyoto_8R", "kyoto_12R", "tokyo_10R", "niigata_6R", "niigata_10R", "niigata_12R")}
    same_8 = {
        "CURRENT": block(lambda r: r["race_id"] in race_ids and r["family"]["CURRENT"])["metrics"],
        "V5_FAMILY": block(lambda r: r["race_id"] in race_ids and r["family"]["V5"])["metrics"],
        "PL_FAMILY_EXP024": block(lambda r: r["race_id"] in race_ids and r["family"]["PL"])["metrics"],
        "ADAPTIVE_RANK1": block(lambda r: r["race_id"] in race_ids and r["rank"]["ADAPTIVE_PL"] == 1)["metrics"],
        "ADAPTIVE_TOP3": block(lambda r: r["race_id"] in race_ids and r["rank"]["ADAPTIVE_PL"] <= 3)["metrics"],
        "ADAPTIVE_JOCKEY_RANK1": block(lambda r: r["race_id"] in race_ids and r["rank"]["ADAPTIVE_PL_JOCKEY"] == 1)["metrics"],
        "ADAPTIVE_JOCKEY_TOP3": block(lambda r: r["race_id"] in race_ids and r["rank"]["ADAPTIVE_PL_JOCKEY"] <= 3)["metrics"],
        "MANUAL_PRIMARY_SHORTLIST": groups["MANUAL_PRIMARY_SHORTLIST"]["metrics"],
    }
    rank1_a = post["rankings"]["ADAPTIVE_PL"]["rank1"]
    rank1_j = post["rankings"]["ADAPTIVE_PL_JOCKEY"]["rank1"]
    top3_a = post["rankings"]["ADAPTIVE_PL"]["rank1_to_3"]
    top3_j = post["rankings"]["ADAPTIVE_PL_JOCKEY"]["rank1_to_3"]
    if (rank1_a["top3_hits"], rank1_a["valid_n"], rank1_j["top3_hits"], rank1_j["valid_n"],
        top3_a["top3_hits"], top3_a["valid_n"], top3_j["top3_hits"], top3_j["valid_n"]) != (3, 21, 9, 21, 22, 63, 19, 62):
        raise RuntimeError("JOCKEY_FROZEN_METRIC_REPRODUCTION_FAIL")
    jockey = {"role": "ONE_DATE_RESEARCH_DIAGNOSTIC_ONLY",
              "adaptive_rank1": rank1_a, "jockey_rank1": rank1_j,
              "rank1_hit_difference": 6, "rank1_rate_difference_pt": 100 * (rank1_j["top3_rate"] - rank1_a["top3_rate"]),
              "adaptive_rank1_to_3": top3_a, "jockey_rank1_to_3": top3_j,
              "top3_hit_difference": -3, "top3_rate_difference_pt": 100 * (top3_j["top3_rate"] - top3_a["top3_rate"])}
    DEST.mkdir(parents=True, exist_ok=True)
    prior = DEST / "manual_pre_labels.json"
    labels = {"source": "PRE_CONVERSATION_BEFORE_RESULT_HUMAN_ATTESTED", "authority_attachment_sha256": sha(AUTHORITY),
              "shortlist_stances": sorted(SHORTLIST_STANCES), "stance_groups": GROUPS,
              "unlisted_stance": "NOT_FORMALLY_CLASSIFIED"}
    if prior.exists():
        if json.loads(prior.read_text(encoding="utf-8")) != json.loads(json.dumps(labels, ensure_ascii=False)):
            raise RuntimeError("MANUAL_PRE_LABELS_FROZEN_MISMATCH")
    else:
        dump(prior, labels)
    dump(DEST / "manual_recovery_post.json", {"status": "COMPLETE", "base_pre_sha256": sha(pre_path),
         "base_post_sha256": sha(post_path), "manual_pre_labels_sha256": sha(prior), "groups": groups,
         "manual_stance_result": stance_results,
         "same_8_race_comparison": same_8, "adaptive_vs_jockey": jockey,
         "no_model_change": True, "formal_prospective_evidence_credit_for_adaptive_jockey": 0})
    lines = ["# 2026-10-24 manual PRE label recovery", "", "Labels are human-attested as pre-Result interpretation. Two independent dimensions are preserved: shortlist inclusion and stance.",
             "", "| Group | Raw N | Valid N | Hits | Rate |", "|---|---:|---:|---:|---:|"]
    for name, g in groups.items():
        m = g["metrics"]
        lines.append(f"| {name} | {m['raw_n']} | {m['valid_n']} | {m['top3_hits']} | {m['top3_rate']:.2%} |" if m["top3_rate"] is not None else f"| {name} | 0 | 0 | 0 | N/A |")
    lines += ["", "## Manual stance (all 269 PRE horses)", "", "| Stance | Raw N | Valid N | Hits | Rate |", "|---|---:|---:|---:|---:|"]
    for name, g in stance_results.items():
        m = g["metrics"]
        lines.append(f"| {name} | {m['raw_n']} | {m['valid_n']} | {m['top3_hits']} | {m['top3_rate']:.2%} |")
    lines += ["", "## Same eight-race comparison", "", "| Frozen condition | Hits / valid N | Rate |", "|---|---:|---:|"]
    for name, m in same_8.items():
        lines.append(f"| {name} | {m['top3_hits']}/{m['valid_n']} | {m['top3_rate']:.2%} |")
    lines += ["", "## Jockey research diagnostic", "", f"Adaptive Rank1: {format_metric(rank1_a)}. Adaptive+Jockey Rank1: {format_metric(rank1_j)}. Hit difference +6; rate difference {jockey['rank1_rate_difference_pt']:+.2f}pt.",
              f"Adaptive Rank1-3: {format_metric(top3_a)}. Adaptive+Jockey Rank1-3: {format_metric(top3_j)}. Hit difference -3; rate difference {jockey['top3_rate_difference_pt']:+.2f}pt.",
              "", "No new winner, BUY rule, model change, or formal prospective evidence is claimed."]
    (DEST / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    dump(DEST / "artifact_hashes.json", {p.name: sha(p) for p in DEST.iterdir() if p.name != "artifact_hashes.json"})
    print(json.dumps({"groups": {k: v["metrics"] for k, v in groups.items()}, "same_8_race": same_8,
                      "jockey": jockey, "manual_label_sha256": sha(prior)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
