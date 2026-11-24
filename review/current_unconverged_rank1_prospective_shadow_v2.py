"""Prior-day execution window for the frozen Current Rank1 v1 PRE selector.

This wrapper reuses v1.build_pre without changing selection. It reads only
Current/EXP-024 PRE authorities and the three frozen prediction inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from review import current_unconverged_rank1_prospective_shadow_v1 as v1


ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
V1_RUNNER = ROOT / "review/current_unconverged_rank1_prospective_shadow_v1.py"
V1_RUNNER_SHA = "81e0a473675994fce64ccaac2709c1a417a662c75ac6a6242ab0070f2bfeda70"
PROTOCOL_VERSION = "CURRENT_UNCONVERGED_RANK1_PROSPECTIVE_SHADOW_V1"
RUNNER_VERSION = "CURRENT_RANK1_PRIOR_DAY_PRE_V2"
HUMAN_APPROVAL = "APPROVE_PRIOR_DAY_PRE_EXECUTION_WINDOW_V1"


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf8"))


def canonical(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf8")


def timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise Stop("STOP_FIRST_START_AUTHORITY_INVALID")
    return parsed


def check_window(target_date: str, first_start_at: str, now: datetime) -> bool:
    if now.tzinfo is None:
        raise Stop("STOP_EXECUTION_CLOCK_NAIVE")
    target = date.fromisoformat(f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:8]}")
    local_date = now.astimezone(JST).date()
    if local_date < target - timedelta(days=1):
        raise Stop("STOP_PRE_TOO_EARLY")
    if local_date > target or now >= timestamp(first_start_at):
        raise Stop("STOP_PRE_WINDOW_CLOSED")
    return local_date == target - timedelta(days=1)


def check_current_authority(current_sha: str, exp024_current_sha: str) -> None:
    if current_sha != exp024_current_sha:
        raise Stop("STOP_CURRENT_AUTHORITY_MISMATCH")


def check_input_authority(expected: dict[str, str], observed: dict[str, str]) -> None:
    if set(expected) != {"DG", "DE", "DS"} or expected != observed:
        raise Stop("STOP_INPUT_AUTHORITY_MISMATCH")


def check_output_absent(path: Path) -> None:
    if path.exists():
        raise Stop("STOP_FORMAL_PRE_ALREADY_EXISTS")


def verify_bindings(target_date: str, current_root: Path, exp024_root: Path) -> dict:
    if sha(V1_RUNNER) != V1_RUNNER_SHA:
        raise Stop("STOP_V1_RUNNER_SHA_MISMATCH")
    v1.verify_authority()
    expected_current = ROOT / f"reports/prospective_prediction_{target_date}_formal_trace_v1"
    expected_exp024 = ROOT / f"reports/exp024_pl_same_volume/{target_date}_pre"
    if current_root.resolve() != expected_current.resolve():
        raise Stop("STOP_CURRENT_AUTHORITY_MISMATCH")
    if exp024_root.resolve() != expected_exp024.resolve():
        raise Stop("STOP_EXP024_FREEZE_AUTHORITY_INVALID")
    current_manifest = current_root / "prediction_manifest.json"
    current_sha = sha(current_manifest)
    selection_path = exp024_root / "selection.json"
    freeze_path = exp024_root / "selection_freeze.json"
    selection, freeze = load(selection_path), load(freeze_path)
    if (selection.get("date") != target_date or
            freeze.get("selection_sha256") != sha(selection_path) or
            freeze.get("result_access_before_freeze") is not False):
        raise Stop("STOP_EXP024_FREEZE_AUTHORITY_INVALID")
    check_current_authority(current_sha, selection.get("current_prediction_sha256"))
    if selection.get("current_pre_root") and Path(selection["current_pre_root"]).resolve() != current_root.resolve():
        raise Stop("STOP_CURRENT_AUTHORITY_MISMATCH")

    expected_schedule = ROOT / f"reports/exp024_pl_same_volume/authority/first_start_{target_date}.json"
    source = ROOT / str(freeze.get("schedule_source_path", "")).replace("\\", "/")
    if not source.is_file():
        raise Stop("STOP_FIRST_START_AUTHORITY_MISSING")
    if source.resolve() != expected_schedule.resolve() or sha(source) != freeze.get("schedule_source_sha256"):
        raise Stop("STOP_FIRST_START_AUTHORITY_INVALID")
    schedule = load(source)
    if (schedule.get("date") != target_date or
            timestamp(schedule["first_start_at"]) != timestamp(freeze["first_start_at"]) or
            timestamp(freeze["selection_freeze_timestamp"]) >= timestamp(freeze["first_start_at"])):
        raise Stop("STOP_FIRST_START_AUTHORITY_INVALID")

    input_manifest_path = current_root / "input_manifest.json"
    input_manifest = load(input_manifest_path)
    if input_manifest.get("date") != target_date:
        raise Stop("STOP_INPUT_AUTHORITY_MISMATCH")
    expected, observed = {}, {}
    for kind in ("DG", "DE", "DS"):
        item = input_manifest.get("sources", {}).get(kind)
        path = ROOT / f"data/raw/prediction_input/{kind}{target_date[2:]}.CSV"
        if not isinstance(item, dict) or not path.is_file() or not item.get("sha256"):
            raise Stop("STOP_INPUT_AUTHORITY_MISMATCH")
        if (ROOT / str(item.get("path", "")).replace("\\", "/")).resolve() != path.resolve():
            raise Stop("STOP_INPUT_AUTHORITY_MISMATCH")
        expected[kind] = item["sha256"]
        observed[kind] = sha(path)
    check_input_authority(expected, observed)
    return {
        "current_manifest_path": str(current_manifest.relative_to(ROOT)).replace("\\", "/"),
        "current_manifest_sha256": current_sha,
        "current_input_manifest_sha256": sha(input_manifest_path),
        "exp024_freeze_path": str(freeze_path.relative_to(ROOT)).replace("\\", "/"),
        "exp024_freeze_sha256": sha(freeze_path),
        "first_start_at": schedule["first_start_at"],
        "first_start_authority_path": str(source.relative_to(ROOT)).replace("\\", "/"),
        "first_start_authority_sha256": sha(source),
        "input_sha256": expected,
    }


def build_selection(current_root: Path, target_date: str) -> dict:
    """Exactly the reviewed v1 selection path; no new ranking or fallback."""
    return v1.build_pre(current_root, target_date)


def run(target_date: str, *, now: datetime | None = None) -> dict:
    if len(target_date) != 8 or not target_date.isdigit():
        raise Stop("STOP_TARGET_DATE_FORMAT")
    current_root = ROOT / f"reports/prospective_prediction_{target_date}_formal_trace_v1"
    exp024_root = ROOT / f"reports/exp024_pl_same_volume/{target_date}_pre"
    output_root = ROOT / f"reports/current_rank1_prospective_shadow_v2/{target_date}_pre"
    check_output_absent(output_root)
    bindings = verify_bindings(target_date, current_root, exp024_root)
    execution = now or datetime.now(timezone.utc)
    prior_day = check_window(target_date, bindings["first_start_at"], execution)
    selection = build_selection(current_root, target_date)
    if selection.get("input_pre_sha256") != bindings["current_manifest_sha256"]:
        raise Stop("STOP_CURRENT_AUTHORITY_MISMATCH")
    selection["generated_at_jst"] = execution.astimezone(JST).isoformat()
    selected = selection["selections"]
    race_ids = sorted({row["race_id"] for row in selected})
    if len(race_ids) != len(selected) or selection["eligible_races"] != len(selected):
        raise Stop("STOP_V2_SELECTION_SEMANTICS_CHANGED")
    if build_selection(current_root, target_date)["selections"] != selected:
        raise Stop("STOP_V2_SELECTION_SEMANTICS_CHANGED")
    check_output_absent(output_root)
    frozen = datetime.now(timezone.utc)
    if now is None:
        check_window(target_date, bindings["first_start_at"], frozen)
    elif frozen >= timestamp(bindings["first_start_at"]):
        raise Stop("STOP_PRE_WINDOW_CLOSED")
    freeze = {
        "protocol_version": PROTOCOL_VERSION,
        "runner_version": RUNNER_VERSION,
        "target_date": target_date,
        "execution_timestamp_jst": execution.astimezone(JST).isoformat(),
        "execution_local_date": execution.astimezone(JST).date().isoformat(),
        "prior_day_pre": prior_day,
        "first_start_at": bindings["first_start_at"],
        "first_start_authority_path": bindings["first_start_authority_path"],
        "first_start_authority_sha256": bindings["first_start_authority_sha256"],
        "current_manifest_path": bindings["current_manifest_path"],
        "current_manifest_sha256": bindings["current_manifest_sha256"],
        "current_input_manifest_sha256": bindings["current_input_manifest_sha256"],
        "exp024_freeze_path": bindings["exp024_freeze_path"],
        "exp024_freeze_sha256": bindings["exp024_freeze_sha256"],
        "input_dg_sha256": bindings["input_sha256"]["DG"],
        "input_de_sha256": bindings["input_sha256"]["DE"],
        "input_ds_sha256": bindings["input_sha256"]["DS"],
        "result_access": 0,
        "odds_used_as_input": False,
        "popularity_used": False,
        "selection_logic_version": V1_RUNNER_SHA,
        "selected_races": race_ids,
        "selected_horses": [{"race_id": row["race_id"], "horse_number": row["selected_horse_number"],
                             "horse_name": row["selected_horse_name"]} for row in selected],
        "freeze_timestamp_jst": frozen.astimezone(JST).isoformat(),
        "pre_window_status": "PASS",
        "human_approval": HUMAN_APPROVAL,
        "evidence_role": selection["role"],
    }
    output_root.mkdir(parents=True, exist_ok=False)
    selection_path = output_root / "pre_selection.json"
    with selection_path.open("xb") as handle:
        handle.write(canonical(selection))
    freeze["selection_sha256"] = sha(selection_path)
    with (output_root / "freeze_manifest.json").open("xb") as handle:
        handle.write(canonical(freeze))
    if datetime.now(timezone.utc) >= timestamp(bindings["first_start_at"]):
        raise Stop("STOP_PRE_WINDOW_CLOSED")
    return {"status": "FROZEN", "selection_path": str(selection_path), "selection_sha256": sha(selection_path),
            "freeze_path": str(output_root / "freeze_manifest.json"), "freeze_sha256": sha(output_root / "freeze_manifest.json"),
            "selected_races": len(race_ids), "selected_horses": len(selected), "prior_day_pre": prior_day}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-date", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.target_date), sort_keys=True))


if __name__ == "__main__":
    main()
