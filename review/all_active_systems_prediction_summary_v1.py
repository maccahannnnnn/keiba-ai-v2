"""Result-free, human-readable matrix over already frozen PRE artifacts."""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEMS = ("CURRENT", "INDEPENDENT_V5", "TRACKCONDITION_SEMANTIC", "DAILY_V5_SAME_VOLUME", "FORMAL_V5", "FORMAL_V6")
FAMILY = {"CURRENT": "CURRENT", "INDEPENDENT_V5": "V5_FAMILY", "TRACKCONDITION_SEMANTIC": "TRACKCONDITION", "DAILY_V5_SAME_VOLUME": "V5_FAMILY", "FORMAL_V5": "V5_FAMILY", "FORMAL_V6": "V6_FAMILY"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def identity(race_id: str) -> tuple[str, int]:
    bits = race_id.split("_")
    return bits[-2], int(bits[-1].removesuffix("R"))


def label(horses: list[dict]) -> str:
    return "NO_BUY" if not horses else ", ".join(f"#{x['horse_number']} {x.get('horse_name', '')}" for x in horses)


def build(date: str, output: Path) -> Path:
    if output.exists():
        raise RuntimeError("STOP_OUTPUT_EXISTS")
    current_root = ROOT / f"reports/daily_pre_analysis_{date}/current_frozen"
    independent_root = ROOT / f"reports/independent_race_selection_prospective/{date}_pre"
    tc_root = ROOT / f"reports/track_condition_semantic_shadow_prospective/{date}_pre"
    daily_root = ROOT / f"reports/daily_v5_same_volume_prospective/{date}_pre"
    formal_root = ROOT / f"reports/selection_authority_protocol_v1_v6_forward_shadow/pre/{date}"
    roots = {"CURRENT": current_root, "INDEPENDENT_V5": independent_root, "TRACKCONDITION_SEMANTIC": tc_root,
             "DAILY_V5_SAME_VOLUME": daily_root, "FORMAL": formal_root}
    current = {item["race_id"]: read(current_root / item["artifact"]) for item in read(current_root / "race_index.json")["race_index"]}
    selections: dict[str, dict[str, list[dict]]] = {name: {} for name in SYSTEMS}
    status: dict[str, dict[str, str]] = {name: {} for name in SYSTEMS}
    for race_id, payload in current.items():
        selections["CURRENT"][race_id] = payload["buys"]
        status["CURRENT"][race_id] = "ELIGIBLE"
    for row in read(independent_root / "selection_manifest.json")["races"]:
        selections["INDEPENDENT_V5"][row["race_id"]] = row["selected_horses"]
        status["INDEPENDENT_V5"][row["race_id"]] = "ELIGIBLE"
    for row in read(tc_root / "horse_level_trace.json")["rows"]:
        if row["shadow_selected"]:
            selections["TRACKCONDITION_SEMANTIC"].setdefault(row["race_id"], []).append({"horse_number": row["horse_number"], "horse_name": row["horse_name"]})
        status["TRACKCONDITION_SEMANTIC"][row["race_id"]] = "ELIGIBLE"
    for row in read(daily_root / "selection.json")["races"]:
        selections["DAILY_V5_SAME_VOLUME"][row["race_id"]] = row["selected_horses"]
        status["DAILY_V5_SAME_VOLUME"][row["race_id"]] = "OUT_OF_SCOPE" if row["scope_status"] == "NOT_ELIGIBLE_RACE_STATE_OR_CURRENT_BUY_ZERO" else row["scope_status"]
    for outer in read(formal_root / "dual_pre_semantic.json")["races"]:
        for system, key in (("FORMAL_V5", "v5"), ("FORMAL_V6", "v6")):
            row = outer[key]
            selections[system][row["race_id"]] = [x for x in row["horses"] if x["selected_by_protocol"]]
            status[system][row["race_id"]] = "ELIGIBLE" if outer["eligible_evidence_race"] else "OUT_OF_SCOPE"
    race_ids = sorted(current, key=lambda item: (*identity(item), item))
    matrix, horse_rows = [], []
    for race_id in race_ids:
        venue, race_number = identity(race_id)
        row = {"date": date, "venue": venue, "race_number": race_number, "race_id": race_id}
        numbers: dict[int, str] = {}
        for system in SYSTEMS:
            values = selections[system].get(race_id, [])
            row[system] = label(values) if status[system].get(race_id) == "ELIGIBLE" else status[system].get(race_id, "OUT_OF_SCOPE")
            for horse in values:
                numbers[int(horse["horse_number"])] = horse.get("horse_name", "")
        matrix.append(row)
        for number, name in sorted(numbers.items()):
            selected = {system: any(int(x["horse_number"]) == number for x in selections[system].get(race_id, [])) for system in SYSTEMS}
            horse_rows.append({**row, "horse_number": number, "horse_name": name, **selected,
                               "selected_system_count": sum(selected.values()), "unique_model_family_count": len({FAMILY[s] for s, value in selected.items() if value})})
    def sets(system: str) -> set[tuple[str, int]]:
        return {(race_id, int(horse["horse_number"])) for race_id in race_ids for horse in selections[system].get(race_id, [])}
    diffs = {}
    for left, right in (("CURRENT", "INDEPENDENT_V5"), ("CURRENT", "TRACKCONDITION_SEMANTIC"), ("CURRENT", "DAILY_V5_SAME_VOLUME"), ("FORMAL_V5", "FORMAL_V6")):
        a, b = sets(left), sets(right)
        diffs[f"{left}_VS_{right}"] = {"common_horses": len(a & b), f"{left}_only_horses": len(a - b), f"{right}_only_horses": len(b - a),
            "common_races": len({x[0] for x in a} & {x[0] for x in b}), f"{left}_only_races": len({x[0] for x in a} - {x[0] for x in b}), f"{right}_only_races": len({x[0] for x in b} - {x[0] for x in a})}
    current_state = {race_id: payload["buy_gate_trace"]["race"]["shadow_race_state"] for race_id, payload in current.items()}
    independent_only = sets("INDEPENDENT_V5") - sets("CURRENT")
    diffs["CURRENT_VS_INDEPENDENT_V5"]["independent_only_by_current_race_state"] = dict(Counter(current_state[race_id] for race_id, _ in independent_only))
    tc_races = read(tc_root / "race_level_trace.json")["rows"]
    diffs["CURRENT_VS_TRACKCONDITION_SEMANTIC"]["race_state_transitions"] = dict(Counter(row["transition"] for row in tc_races))
    sources = read(current_root / "input_manifest.json")["sources"]
    system_summary = {system: {"selected_races": sum(bool(selections[system].get(race_id)) for race_id in race_ids), "selected_horses": len(sets(system)), "artifact_root": str((roots.get(system, formal_root)).relative_to(ROOT))} for system in SYSTEMS}
    daily_equal = all(len(selections["CURRENT"].get(race_id, [])) == len(selections["DAILY_V5_SAME_VOLUME"].get(race_id, [])) for race_id in race_ids if status["DAILY_V5_SAME_VOLUME"].get(race_id) == "ELIGIBLE")
    output.mkdir(parents=True)
    fields = ["date", "venue", "race_number", "race_id", *SYSTEMS]
    with (output / "prediction_matrix.csv").open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields); writer.writeheader(); writer.writerows(matrix)
    (output / "race_by_race_summary.json").write_text(json.dumps({"date": date, "races": matrix, "horse_level_agreement": horse_rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "system_summary.json").write_text(json.dumps({"date": date, "source_sha256": sources, "systems": system_summary, "daily_v5_same_volume_race_equality": daily_equal, "daily_v5_not_comparable_races": [race_id for race_id in race_ids if status["DAILY_V5_SAME_VOLUME"].get(race_id) == "NOT_COMPARABLE"]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "system_difference_summary.json").write_text(json.dumps(diffs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [f"# {date} Active PRE Prediction Matrix", "", "| Venue | R | Current | Independent V5 | TrackCondition | Daily V5 | Formal V5 | Formal V6 |", "|---|---:|---|---|---|---|---|---|"]
    lines += [f"| {x['venue']} | {x['race_number']} | {x['CURRENT']} | {x['INDEPENDENT_V5']} | {x['TRACKCONDITION_SEMANTIC']} | {x['DAILY_V5_SAME_VOLUME']} | {x['FORMAL_V5']} | {x['FORMAL_V6']} |" for x in matrix]
    (output / "prediction_matrix.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    share = [f"# {date} PRE — Claude Share", "", "- Result access: 0", "- All values are frozen PRE selections; no hit/rate fields are present.", "", "## System totals"]
    share += [f"- {system}: {item['selected_races']} races / {item['selected_horses']} horses" for system, item in system_summary.items()]
    share += ["", "## Matrix", *lines[2:]]
    (output / "claude_share_summary.md").write_text("\n".join(share) + "\n", encoding="utf-8")
    files = [path for path in output.iterdir() if path.is_file()]
    (output / "artifact_hashes.json").write_text(json.dumps({"self_hash_excluded": True, "indexed_artifacts": {path.name: sha(path) for path in files}}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output
