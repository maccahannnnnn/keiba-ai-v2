"""Build the 2026-11-01 PRE-only human analysis fact pack.

This is a reporting extractor. It does not invoke prediction or read results.
"""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
import re
import unicodedata
from collections import Counter
from pathlib import Path

from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1


ROOT = Path(__file__).resolve().parents[1]
DATE = "20261101"
SOURCES = {kind: ROOT / "data/raw/prediction_input" / f"{kind}261101.CSV" for kind in ("DG", "DE", "DS")}
CONSENSUS = ROOT / "reports/20261101_multi_lane_pre_v1/consensus_20261101.json"
OUT = ROOT / "reports/20261101_human_analysis_pack_v1"
VENUES = {"tokyo": "東京", "kyoto": "京都"}
PRIORITY = {
    ("tokyo", 6, 1): "PL_JOCKEY_E1",
    ("tokyo", 7, 4): "PL_JOCKEY_E1",
    ("tokyo", 7, 11): "PL_JOCKEY_E1",
    ("tokyo", 8, 1): "PL_JOCKEY_E1",
    ("tokyo", 8, 2): "PL_JOCKEY_E1",
    ("tokyo", 12, 8): "PL_JOCKEY_E1",
    ("tokyo", 12, 13): "PL_JOCKEY_E1",
    ("kyoto", 12, 2): "ADDITIONAL",
    ("kyoto", 9, 6): "E1_ONLY",
    ("kyoto", 9, 8): "E1_ONLY",
    ("kyoto", 10, 1): "E1_ONLY",
    ("kyoto", 10, 2): "E1_ONLY",
    ("tokyo", 10, 9): "E1_ONLY",
}
LANES = ("CURRENT", "EXP024", "CURRENT_RANK1", "PL_JOCKEY", "A_NEW", "E1", "INDEPENDENT_V5")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text(value: object) -> str:
    value = str(value or "").strip()
    return value or "NOT_AVAILABLE"


def maybe_int(value: str) -> int | None:
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return None


def style_from_history(rows: list[list[str]]) -> tuple[str, str]:
    """Descriptive, approximate early-position bucket; never a prediction."""
    ratios = []
    evidence = []
    for row in rows:
        field_size = maybe_int(row[21])
        corners = [maybe_int(row[i]) for i in range(31, 35)]
        first = next((value for value in corners if value is not None and value > 0), None)
        if field_size and first and field_size > 0:
            ratios.append(first / field_size)
            evidence.append(f"{row[0]}/{row[1]}/{row[2]} {first}/{field_size}")
    if not ratios:
        return "不明", "過去走の通過順なし"
    ratio = statistics.median(ratios)
    bucket = "逃げ候補" if ratio <= 0.20 else "先行候補" if ratio <= 0.45 else "差し候補" if ratio <= 0.75 else "追込候補"
    return bucket, "; ".join(evidence)


def class_tier(label: str) -> int | None:
    normalized = unicodedata.normalize("NFKC", label)
    if "新馬" in normalized or "未勝利" in normalized:
        return 0
    match = re.search(r"([123])勝", normalized)
    if match:
        return int(match.group(1))
    return None


def past_run(row: list[str], today_venue: str, today_surface: str, today_distance: int, today_class: str) -> dict:
    # DS field positions follow the existing TargetBulkPredictionInputAdapterV1 mapping.
    corners = [row[i].strip() for i in range(31, 35) if row[i].strip() and row[i].strip() != "0"]
    previous_distance = maybe_int(row[14])
    past_class = row[8].strip()
    today_tier, past_tier = class_tier(today_class), class_tier(past_class)
    if today_tier is None or past_tier is None:
        class_relation = "判定不能(階級不明)"
    elif today_tier > past_tier:
        class_relation = "今回昇級"
    elif today_tier < past_tier:
        class_relation = "今回降級"
    else:
        class_relation = "同級"
    return {
        "date": f"20{row[0].strip()}-{int(row[1]):02d}-{int(row[2]):02d}",
        "venue": text(row[4]),
        "surface": text(row[12]),
        "distance_m": previous_distance,
        "track_condition": text(row[15]),
        "class": text(past_class),
        "field_size": maybe_int(row[21]),
        "finish": maybe_int(row[23]),
        "running_positions": "-".join(corners) if corners else "NOT_AVAILABLE",
        "final_3f": text(row[35]),
        "race_time": text(row[29]),
        "margin": text(row[26]),
        "carried_weight": text(row[20]),
        "body_weight": text(row[37]),
        "body_weight_change": text(row[38]),
        "distance_change_to_today_m": today_distance - previous_distance if previous_distance is not None else None,
        "course_relation": "同競馬場" if row[4].strip() == today_venue else "別競馬場",
        "surface_relation": "同馬場種" if row[12].strip() == today_surface else "別馬場種",
        "class_relation": class_relation,
    }


def md(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def run() -> dict:
    if OUT.exists() and {p.name for p in OUT.iterdir()} - {"priority_horses_20261101.md", "race_structure_20261101.md", "priority_horses_20261101.csv"}:
        raise RuntimeError("STOP_UNEXPECTED_OUTPUT_FILE")
    for path in (*SOURCES.values(), CONSENSUS):
        if not path.is_file():
            raise RuntimeError(f"STOP_SOURCE_MISSING:{path}")
    adapter = TargetBulkPredictionInputAdapterV1()
    bundle = adapter.load(SOURCES["DG"], SOURCES["DE"], SOURCES["DS"])
    if bundle.date != DATE:
        raise RuntimeError("STOP_DATE_MISMATCH")
    pre = json.loads(CONSENSUS.read_text(encoding="utf-8"))
    if pre["target_date"] != "2026-11-01" or pre["result_access"] != 0:
        raise RuntimeError("STOP_PRE_AUTHORITY_MISMATCH")
    if pre["total_races"] != len(bundle.races) or pre["total_horses"] != sum(len(r.today_entries) for r in bundle.races.values()):
        raise RuntimeError("STOP_PRE_POPULATION_MISMATCH")
    pre_by = {(h["race_id"], int(h["horse_number"])): h for h in pre["horses"]}
    if len(pre_by) != pre["total_horses"]:
        raise RuntimeError("STOP_DUPLICATE_PRE_HORSE")
    with SOURCES["DE"].open("r", encoding="cp932", newline="") as file:
        de_by = {(row[1].strip(), int(row[2]), int(row[3])): row for row in csv.reader(file)}
    with SOURCES["DG"].open("r", encoding="cp932", newline="") as file:
        dg_by = {(row[3].strip(), int(row[4])): row for row in csv.reader(file)}
    details = []
    race_sections = []
    missing = Counter()
    for venue_key, race_number in sorted({(v, r) for v, r, _ in PRIORITY}, key=lambda x: (x[0], x[1])):
        venue = VENUES[venue_key]
        race_id = f"race_{DATE}_{venue_key}_{race_number}R"
        race = bundle.races[race_id]
        dg = dg_by[(venue, race_number)]
        today_surface = "芝" if dg[7].strip() == "芝" else "ダ"
        today_distance = int(dg[8])
        today_class = dg[5].strip()
        field = []
        for entry in sorted(race.today_entries, key=lambda x: x.horse_number):
            key = (race_id, entry.horse_number)
            p = pre_by.get(key)
            if p is None or p["horse_name"] != entry.horse_name:
                raise RuntimeError(f"STOP_HORSE_IDENTITY_MISMATCH:{key}")
            de = de_by[(venue, race_number, entry.horse_number)]
            if de[7].replace(" ", "").replace("　", "") != entry.horse_name:
                raise RuntimeError(f"STOP_DE_HORSE_IDENTITY_MISMATCH:{key}")
            history = adapter.valid_history_rows(race.history_rows_by_horse[entry.horse_name])
            style, style_evidence = style_from_history(history)
            field.append((entry.horse_number, entry.horse_name, style, style_evidence))
            priority_group = PRIORITY.get((venue_key, race_number, entry.horse_number))
            if priority_group is None:
                continue
            runs = [past_run(row, venue, today_surface, today_distance, today_class) for row in history]
            if not runs:
                missing["past_runs"] += 1
            missing["current_body_weight"] += 1
            missing["current_track_condition"] += 1
            if any(x["class_relation"].startswith("判定不能") for x in runs):
                missing["class_transition_not_authoritatively_determined"] += 1
            record = {
                "group": priority_group, "date": "2026-11-01", "venue": venue,
                "race_number": race_number, "race_id": race_id,
                "horse_number": entry.horse_number, "horse_name": entry.horse_name,
                "registration_id": text(de[18]), "frame_number": entry.frame_number,
                "sex": text(de[8]), "age": maybe_int(de[9]),
                "assigned_weight": entry.weight, "jockey": text(de[10]),
                "trainer": text(de[12]), "sire": text(de[16]),
                "dam": text(de[17]), "maternal_grandsire": text(de[20]),
                "current_surface": today_surface, "current_distance_m": today_distance,
                "current_class": today_class, "current_field_size": len(race.today_entries),
                "current_body_weight": "NOT_AVAILABLE_IN_PRE_SOURCE",
                "current_track_condition": "NOT_AVAILABLE_IN_PRE_SOURCE",
                "running_style_estimate": style,
                "running_style_evidence": style_evidence,
                "past_runs": runs,
                "same_distance_history": sum(x["distance_m"] == today_distance for x in runs),
                "same_venue_history": sum(x["venue"] == venue for x in runs),
                "same_surface_history": sum(x["surface"] == today_surface for x in runs),
                "past_track_condition_counts": dict(Counter(x["track_condition"] for x in runs)),
                "ai": {lane: bool(p[lane]) for lane in LANES},
                "current_rank": p.get("current_rank"),
                "pl_jockey_rank": p.get("pl_jockey_rank"),
                "pl_jockey_p_top3": p.get("pl_jockey_p_top3"),
                "a_new_rank": p.get("a_new_rank"),
                "a_new_p_top3": p.get("a_new_p_top3"),
                "e1_global_allocation_rank": p.get("e1_global_allocation_rank"),
                "independent_v5_rank": p.get("independent_v5_rank"),
                "independent_v5_p_top3": p.get("independent_v5_p_top3"),
            }
            details.append(record)
        if len(field) != len(race.today_entries):
            raise RuntimeError(f"STOP_FIELD_COUNT_MISMATCH:{race_id}")
        race_sections.append((venue, race_number, race_id, dg, field))
    if len(details) != len(PRIORITY):
        raise RuntimeError("STOP_PRIORITY_COUNT_MISMATCH")
    if any(r["group"] == "PL_JOCKEY_E1" and not (r["ai"]["PL_JOCKEY"] and r["ai"]["E1"]) for r in details):
        raise RuntimeError("STOP_PL_JOCKEY_E1_GROUP_MISMATCH")
    if any(r["group"] == "E1_ONLY" and not (r["ai"]["E1"] and not r["ai"]["PL_JOCKEY"]) for r in details):
        raise RuntimeError("STOP_E1_ONLY_GROUP_MISMATCH")

    OUT.mkdir(parents=True, exist_ok=True)
    csv_path = OUT / "priority_horses_20261101.csv"
    columns = ["group", "date", "venue", "race_number", "race_id", "horse_number", "horse_name",
               "registration_id", "frame_number", "sex", "age", "assigned_weight", "jockey", "trainer",
               "sire", "dam", "maternal_grandsire", "current_surface", "current_distance_m", "current_class",
               "current_field_size", "current_body_weight", "current_track_condition", "running_style_estimate",
               "running_style_evidence", "same_distance_history", "same_venue_history", "same_surface_history", "past_track_condition_counts",
               *LANES, "current_rank", "pl_jockey_rank", "pl_jockey_p_top3", "a_new_rank", "a_new_p_top3",
               "e1_global_allocation_rank", "independent_v5_rank", "independent_v5_p_top3", "past_runs_json"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        for r in details:
            row = {k: r.get(k) for k in columns}
            row.update(r["ai"])
            row["past_runs_json"] = json.dumps(r["past_runs"], ensure_ascii=False, separators=(",", ":"))
            row["past_track_condition_counts"] = json.dumps(r["past_track_condition_counts"], ensure_ascii=False, separators=(",", ":"))
            writer.writerow(row)

    source_info = ", ".join(f"{kind}={sha(path)}" for kind, path in SOURCES.items())
    lines = ["# 2026-11-01 Human race analysis: priority horses", "",
             "PRE-only factual extraction. Result, odds, popularity, and marks are not used. AI flags are context, not a recommendation.", "",
             f"Source SHA256: {source_info}", f"Frozen PRE consensus SHA256: {sha(CONSENSUS)}", "",
             "Current body weight and track condition are absent from the PRE source. Class rise/drop uses only explicit 新馬/未勝利/1勝/2勝/3勝 labels; other classes remain undetermined.",
             "Running-style buckets are approximate descriptions from the median of each horse's earliest recorded corner position / field size over up to five recent valid DS runs; no pace prediction is made.", ""]
    for r in details:
        lines += [f"## {r['venue']}{r['race_number']}R #{r['horse_number']} {r['horse_name']} ({r['group']})", "",
                  f"枠 {r['frame_number']} / {r['sex']}{r['age']}歳 / 斤量 {r['assigned_weight']}kg / 騎手 {r['jockey']} / 調教師 {r['trainer']} / 登録番号 {r['registration_id']}", "",
                  f"今回: {r['current_surface']}{r['current_distance_m']}m / {r['current_class']} / {r['current_field_size']}頭。父 {r['sire']} / 母 {r['dam']} / 母父 {r['maternal_grandsire']}。", "",
                  f"近走位置取り: {r['running_style_estimate']}（{r['running_style_evidence']}）。直近{len(r['past_runs'])}走内の同距離 {r['same_distance_history']}走、同競馬場 {r['same_venue_history']}走、同馬場種 {r['same_surface_history']}走。過去馬場状態内訳: {r['past_track_condition_counts']}。", "",
                  "AI PRE context: " + ", ".join(f"{lane}={'YES' if r['ai'][lane] else 'NO'}" for lane in LANES), "",
                  f"Current rank={r['current_rank']}; PL_JOCKEY rank/p_top3={r['pl_jockey_rank']}/{r['pl_jockey_p_top3']}; A_NEW rank/p_top3={r['a_new_rank']}/{r['a_new_p_top3']}; E1 global allocation rank={r['e1_global_allocation_rank']}; Independent V5 rank/p_top3={r['independent_v5_rank']}/{r['independent_v5_p_top3']}。p_top3は3着内包含確率。", "",
                  "| 日付 | 場 | 芝/ダ | 距離 | 馬場 | クラス | 頭数 | 着順 | 通過順 | 上がり | 時計 | 着差 | 斤量 | 馬体重(増減) | 今回との差 |",
                  "|---|---|---|---:|---|---|---:|---:|---|---|---|---|---|---|---|"]
        for p in r["past_runs"]:
            lines.append("| " + " | ".join(md(x) for x in (p["date"], p["venue"], p["surface"], p["distance_m"], p["track_condition"], p["class"], p["field_size"], p["finish"], p["running_positions"], p["final_3f"], p["race_time"], p["margin"], p["carried_weight"], f"{p['body_weight']} ({p['body_weight_change']})", f"距離 {p['distance_change_to_today_m']}m / {p['course_relation']} / {p['surface_relation']} / {p['class_relation']}")) + " |")
        if not r["past_runs"]:
            lines.append("| 過去走記録なし | | | | | | | | | | | | | | |")
        lines.append("")
    priority_path = OUT / "priority_horses_20261101.md"
    priority_path.write_text("\n".join(lines), encoding="utf-8")

    lines = ["# 2026-11-01 Target-race structure", "",
             "PRE-only full-field inventory for eight requested races. The running-style grouping is a descriptive approximation from historical corner positions, not a forecast. PACE_STRUCTURE is UNCERTAIN for every race; no mechanical slow/normal/fast call is made.", ""]
    for venue, number, race_id, dg, field in race_sections:
        counts = Counter(style for _, _, style, _ in field)
        lines += [f"## {venue}{number}R — {dg[7].strip()}{dg[8].strip()}m / {dg[5].strip()} / {len(field)}頭", "",
                  f"PACE_STRUCTURE = UNCERTAIN。脚質構成: 逃げ候補 {counts['逃げ候補']} / 先行候補 {counts['先行候補']} / 差し候補 {counts['差し候補']} / 追込候補 {counts['追込候補']} / 不明 {counts['不明']}。", "",
                  "| 馬番 | 馬名 | 推定脚質 | 根拠（過去走の初期通過順位/頭数） |", "|---:|---|---|---|"]
        for no, name, style, evidence in field:
            lines.append(f"| {no} | {md(name)} | {style} | {md(evidence)} |")
        lines.append("")
    structure_path = OUT / "race_structure_20261101.md"
    structure_path.write_text("\n".join(lines), encoding="utf-8")
    return {"horses": len(details), "races": len(race_sections), "past_runs": sum(len(r["past_runs"]) for r in details),
            "full_field_horses": sum(len(field) for _, _, _, _, field in race_sections),
            "missing": dict(missing), "output_sha256": {p.name: sha(p) for p in (priority_path, structure_path, csv_path)}}


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
