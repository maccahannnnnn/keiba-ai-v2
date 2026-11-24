"""Date-scoped Formal PRE authority operations; prediction remains in frozen runners.

V1 is loaded into a private module instance for each date. Its approved recording
operations are reused without changing the V1 file or process-global V1 state.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "review/formal_pre_authority_helper_v1.py"
V1_SHA = "62d049d3963c5646150673dfeaaf7902dd9bbaa530d900e835eae0ebc73195fa"
CALENDAR_SHA = "33cfa46d92a7ed3e6a5e96054503fcea69c487786eb37e369419d23917a5ee19"
CALENDAR = Path("C:/Users/hikar/.codex/worktrees/rolling-learning-v1/keiba AI/docs/JRA_OFFICIAL_SEASON_CALENDAR_2026.json")
VENUE_IDS = {"東京": "tokyo", "京都": "kyoto", "福島": "fukushima",
             "中山": "nakayama", "阪神": "hanshin", "中京": "chukyo",
             "新潟": "niigata", "小倉": "kokura", "札幌": "sapporo", "函館": "hakodate"}
CONSERVATIVE_AUTHORITY_START = "20261109"
CONSERVATIVE_AUTHORITY_KIND = "KEIBAAI_0900_JST_OPERATIONAL_CUTOFF_V1"
JST = timezone(timedelta(hours=9))


class Stop(RuntimeError):
    pass


def digest(path: Path) -> str:
    if not path.is_file():
        raise Stop("STOP_REQUIRED_ARTIFACT_MISSING:" + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_date(value: str) -> str:
    if re.fullmatch(r"\d{8}", value) is None:
        raise Stop("STOP_DATE_FORMAT")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise Stop("STOP_DATE_FORMAT") from error
    return value


def calendar_venues(date: str, calendar: Path = CALENDAR) -> frozenset[str]:
    checked_date(date)
    if date[:4] != "2026":
        raise Stop("STOP_NEW_CALENDAR_AUTHORITY_REQUIRED")
    if digest(calendar) != CALENDAR_SHA:
        raise Stop("STOP_CALENDAR_SHA")
    value = json.loads(calendar.read_text(encoding="utf-8"))
    venues = value.get("scheduled_venues", {}).get(date)
    if date not in value.get("scheduled_dates", []) or not isinstance(venues, list) or not venues:
        raise Stop("STOP_CALENDAR_DATE_OR_VENUES")
    if len(venues) != len(set(venues)) or any(venue not in VENUE_IDS for venue in venues):
        raise Stop("STOP_CALENDAR_VENUE_MAPPING")
    return frozenset(venues)


def conservative_cutoff(date: str) -> datetime:
    checked_date(date)
    return datetime.combine(datetime.strptime(date, "%Y%m%d").date(), time(9), JST)


def create_conservative_authority(date: str, *, root: Path = ROOT,
                                  calendar: Path = CALENDAR,
                                  known_first_start_at: str | None = None,
                                  special_condition: bool = False,
                                  now_utc: datetime | None = None) -> str:
    """Record a conservative operational deadline, never an official JRA time."""
    if date < CONSERVATIVE_AUTHORITY_START:
        raise Stop("STOP_CONSERVATIVE_AUTHORITY_NOT_EFFECTIVE")
    venues = calendar_venues(date, calendar)
    cutoff = conservative_cutoff(date)
    observed = now_utc or datetime.now(timezone.utc)
    if observed.tzinfo is None or observed >= cutoff:
        raise Stop("STOP_CONSERVATIVE_CUTOFF_PASSED")
    if special_condition:
        raise Stop("STOP_SPECIAL_SCHEDULE_CONDITION")
    if known_first_start_at is not None:
        known = datetime.fromisoformat(known_first_start_at.replace("Z", "+00:00"))
        if known.tzinfo is None or known.astimezone(JST).date() != cutoff.date() or known <= cutoff:
            raise Stop("STOP_KNOWN_EARLY_OR_INVALID_FIRST_START")
    path = Paths(date, root).first_start
    if path.exists():
        raise Stop("STOP_OUTPUT_EXISTS:" + str(path))
    value = {"date": date, "authority_kind": CONSERVATIVE_AUTHORITY_KIND,
             "first_start_at": cutoff.isoformat(),
             "first_start_at_semantics": "CONSERVATIVE_OPERATIONAL_FREEZE_CUTOFF_NOT_OFFICIAL_START",
             "operational_cutoff_at": cutoff.isoformat(), "official_time_verified": False,
             "operator_verified": False, "first_race": "NOT_VERIFIED",
             "source_snapshots": [], "calendar_sha256": digest(calendar),
             "calendar_venues": sorted(venues), "known_first_start_at": known_first_start_at,
             "special_condition": False, "observed_at_utc": observed.isoformat(),
             "result_access": 0, "odds_used_as_input": False, "popularity_used_as_input": False,
             "prospective_only_effective_from": CONSERVATIVE_AUTHORITY_START}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write((json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
    return digest(path)


@dataclass(frozen=True)
class Paths:
    date: str
    root: Path = ROOT

    @property
    def first_start(self) -> Path:
        return self.root / f"reports/exp024_pl_same_volume/authority/first_start_{self.date}.json"

    @property
    def official_snapshots(self) -> Path:
        return self.root / f"reports/exp024_pl_same_volume/authority/{self.date}_official_snapshots"

    @property
    def current(self) -> Path:
        return self.root / f"reports/prospective_prediction_{self.date}_formal_trace_v1"

    @property
    def exp024(self) -> Path:
        return self.root / f"reports/exp024_pl_same_volume/{self.date}_pre"

    @property
    def rank1(self) -> Path:
        return self.root / f"reports/current_rank1_prospective_shadow_v2/{self.date}_pre"

    @property
    def plj(self) -> Path:
        return self.root / f"reports/frozen_pl_v1_jockey_offset_provisional_v1/{self.date}_pre"

    @property
    def independent(self) -> Path:
        return self.root / f"reports/independent_race_selection_prospective/{self.date}_pre"

    @property
    def pl_forward(self) -> Path:
        return self.root / f"reports/pl_forward_shadow_v1/{self.date}_pre/prediction.json"

    @property
    def step1(self) -> Path:
        return self.root / f"reports/pl_jockey_step1_completion_v1/{self.date}_pre/derivation_freeze.json"

    @property
    def daily_summary(self) -> Path:
        return self.root / f"reports/formal_pre_daily/{self.date}/summary.json"

    @property
    def snapshot_manifest(self) -> Path:
        return self.root / "docs/KeibaAI_JOCKEY_FORMAL_PRE_SNAPSHOT_MANIFEST_V1.json"


def previous_exp024_fingerprint(date: str, root: Path = ROOT, manifest_path: Path | None = None) -> str:
    """Resolve the latest earlier formal date, then verify its frozen EXP-024 SHA chain."""
    path = manifest_path or Paths(date, root).snapshot_manifest
    value = json.loads(path.read_text(encoding="utf-8"))
    dates = value.get("expected_formal_pre_dates")
    entries = value.get("entries")
    if not isinstance(dates, list) or not isinstance(entries, list):
        raise Stop("STOP_FORMAL_MANIFEST_SCHEMA")
    prior = [d for d in dates if isinstance(d, str) and d < date]
    if not prior or len(prior) != len(set(prior)):
        raise Stop("STOP_PREVIOUS_FORMAL_DATE_MISSING")
    prior_date = max(prior)
    matched = [entry for entry in entries if entry.get("date") == prior_date]
    if len(matched) != 1 or matched[0].get("status") != "FROZEN_PRE_SOURCE":
        raise Stop("STOP_PREVIOUS_FORMAL_ENTRY")
    prior_root = root / f"reports/exp024_pl_same_volume/{prior_date}_pre"
    selection_path = prior_root / "selection.json"
    freeze_path = prior_root / "selection_freeze.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    if freeze.get("selection_sha256") != digest(selection_path):
        raise Stop("STOP_EXP024_PREVIOUS_SELECTION_SHA")
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    fingerprint = selection.get("current_environment_fingerprint")
    if (selection.get("date") != prior_date or not isinstance(fingerprint, str) or
            re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None or
            selection.get("current_environment", {}).get("block_fingerprint_sha256") != fingerprint):
        raise Stop("STOP_EXP024_PREVIOUS_FINGERPRINT")
    return fingerprint


def helper(date: str, *, root: Path = ROOT, calendar: Path = CALENDAR):
    """Private date binding of approved V1 operations, with only date-lock repairs."""
    venues = calendar_venues(date, calendar)
    if digest(V1) != V1_SHA:
        raise Stop("STOP_V1_SHA_CHANGED")
    spec = importlib.util.spec_from_file_location("_formal_pre_authority_v1_private_" + date, V1)
    if spec is None or spec.loader is None:
        raise Stop("STOP_V1_LOAD")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    paths = Paths(date, root)
    module.DATE = date
    module.ROOT = root
    module.VENUES = set(venues)
    module.CALENDAR = calendar
    module.FIRST_START = paths.first_start
    module.CURRENT = paths.current
    module.EXP024 = paths.exp024
    module.RANK1 = paths.rank1
    module.PLJ = paths.plj
    module.INDEPENDENT = paths.independent
    module.SNAPSHOT_MANIFEST = paths.snapshot_manifest
    module.EXP024_DEADLINE = datetime.combine(datetime.strptime(date, "%Y%m%d").date(),
                                               time(9), tzinfo=module.JST)
    module.previous_exp024_fingerprint = lambda active_root: previous_exp024_fingerprint(
        date, active_root, paths.snapshot_manifest)

    legacy_first_start_evidence = module.first_start_evidence

    def first_start_evidence(path: Path, *, root: Path = root) -> dict:
        value = module.load(path)
        if value.get("authority_kind") != CONSERVATIVE_AUTHORITY_KIND:
            return legacy_first_start_evidence(path, root=root)
        if date < CONSERVATIVE_AUTHORITY_START or path.resolve() != Paths(date, root).first_start.resolve():
            raise Stop("STOP_CONSERVATIVE_AUTHORITY_SCOPE")
        cutoff = conservative_cutoff(date)
        try:
            observed = module.moment(value["observed_at_utc"])
            known = module.moment(value["known_first_start_at"]) if value.get("known_first_start_at") else None
        except (KeyError, ValueError) as error:
            raise Stop("STOP_CONSERVATIVE_AUTHORITY_TIME") from error
        if (value.get("date") != date or value.get("first_start_at") != cutoff.isoformat() or
                value.get("operational_cutoff_at") != cutoff.isoformat() or
                value.get("first_start_at_semantics") != "CONSERVATIVE_OPERATIONAL_FREEZE_CUTOFF_NOT_OFFICIAL_START" or
                value.get("official_time_verified") is not False or value.get("operator_verified") is not False or
                value.get("first_race") != "NOT_VERIFIED" or value.get("source_snapshots") != [] or
                value.get("special_condition") is not False or value.get("result_access") != 0 or
                value.get("prospective_only_effective_from") != CONSERVATIVE_AUTHORITY_START or
                value.get("calendar_sha256") != digest(calendar) or
                value.get("calendar_venues") != sorted(calendar_venues(date, calendar)) or
                observed >= cutoff or (known is not None and known <= cutoff)):
            raise Stop("STOP_CONSERVATIVE_AUTHORITY_INVALID")
        return value

    module.first_start_evidence = first_start_evidence

    original_current_authority = module.current_authority

    def current_authority(active_root: Path, current: Path):
        # V1's fixed three-venue check is the only non-date-specific check here.
        try:
            if current.resolve() != (active_root / f"reports/prospective_prediction_{date}_formal_trace_v1").resolve():
                raise Stop("STOP_CURRENT_ROOT")
            # Keep all V1 SHA, input, race-index and adapter checks, replacing
            # only its venue comparison via a scoped check on the same index.
            if {VENUE_IDS[v] for v in venues} == {"kyoto", "tokyo", "fukushima"}:
                return original_current_authority(active_root, current)
            manifest = module.load(current / "prediction_manifest.json")
            listed = manifest.get("files")
            if not isinstance(listed, list) or not listed:
                raise Stop("STOP_PREDICTION_MANIFEST_SCHEMA")
            names = [x.get("relative_path") for x in listed]
            if (any(not isinstance(n, str) or len(Path(n).parts) != 1 or ":" in n or n in {".", ".."}
                    for n in names) or len(names) != len(set(names))):
                raise Stop("STOP_PREDICTION_MANIFEST_PATH_SCOPE")
            for item in listed:
                if module.sha(current / item["relative_path"]) != item["sha256"]:
                    raise Stop("STOP_PREDICTION_MANIFEST_SHA")
            inputs = module.load(current / "input_manifest.json")
            provenance = module.load(current / "provenance.json")
            if inputs.get("date") != date or provenance.get("target_date") != date or provenance.get("result_data_access_count") != 0:
                raise Stop("STOP_CURRENT_DATE_OR_RESULT_ACCESS")
            for kind in ("DG", "DE", "DS"):
                source = active_root / f"data/raw/prediction_input/{kind}{date[2:]}.CSV"
                item = inputs.get("sources", {}).get(kind, {})
                if module.relative(active_root, source) != module.normalized_input_path(item.get("path")) or module.sha(source) != item.get("sha256"):
                    raise Stop("STOP_CURRENT_INPUT_SHA:" + kind)
            index = module.load(current / "race_index.json").get("race_index")
            if not isinstance(index, list) or not index or len({r["race_id"] for r in index}) != len(index):
                raise Stop("STOP_RACE_INDEX_SCHEMA")
            if next((x["sha256"] for x in listed if x["relative_path"] == "race_index.json"), None) != module.sha(current / "race_index.json"):
                raise Stop("STOP_RACE_INDEX_SHA")
            if {n for n in names if n.endswith("_prediction.json")} != {r["artifact"] for r in index}:
                raise Stop("STOP_PREDICTION_MANIFEST_RACE_SET")
            if {r["race_id"].split("_")[2] for r in index} != {VENUE_IDS[v] for v in venues}:
                raise Stop("STOP_CALENDAR_VENUE_SCOPE")
            if any(not r["race_id"].startswith("race_" + date + "_") or not r["artifact"].endswith("_prediction.json") for r in index):
                raise Stop("STOP_RACE_ID_SCOPE")
            module.check_source_scope(active_root, index)
            return manifest, inputs, index
        finally:
            module.current_authority = current_authority

    module.current_authority = current_authority

    original_freeze_exp024 = module.freeze_exp024

    def freeze_exp024(*, current: Path, evidence: Path, approval: Path, output: Path,
                      root: Path = root) -> str:
        first = module.moment(module.first_start_evidence(evidence, root=root)["first_start_at"])
        if module.now_utc() >= min(first, module.EXP024_DEADLINE):
            raise Stop("STOP_EXP024_FORMAL_FREEZE_DEADLINE")
        result = original_freeze_exp024(current=current, evidence=evidence, approval=approval,
                                        output=output, root=root)
        frozen = module.moment(module.load(output / "selection_freeze.json")["selection_freeze_timestamp"])
        if frozen >= min(first, module.EXP024_DEADLINE):
            raise Stop("STOP_EXP024_FORMAL_FREEZE_DEADLINE")
        return result

    module.freeze_exp024 = freeze_exp024

    def verify_v3_pre(active_root: Path, manifest_path: Path) -> None:
        if not (module.V3 / "review/rolling_learning_v3.py").is_file():
            raise Stop("STOP_V3_VERIFIER_MISSING")
        code = ("from pathlib import Path; from review.rolling_learning_v3 import verify_pre; "
                "verify_pre(Path(__import__('sys').argv[1]), __import__('sys').argv[2], "
                "Path(__import__('sys').argv[3]))")
        import os
        result = subprocess.run([sys.executable, "-c", code, str(active_root), date,
                                 module.relative(active_root, manifest_path)], cwd=module.V3,
                                env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
                                capture_output=True, text=True)
        if result.returncode:
            raise Stop("STOP_V3_VERIFY_PRE:" + result.stderr.strip()[-500:])

    module.verify_v3_pre = verify_v3_pre
    original_audit = module.audit

    def audit(*, root: Path, current: Path, evidence: Path, manifest_path: Path,
              lane_artifacts: dict[str, Path] | None = None,
              step1_path: Path | None = None) -> dict:
        result = original_audit(root=root, current=current, evidence=evidence,
                                manifest_path=manifest_path, lane_artifacts=lane_artifacts,
                                step1_path=step1_path)
        return {**result, "venue_count": len(venues)}

    module.audit = audit
    return module


def _verified_selection(path: Path, freeze_path: Path, *, date: str,
                        date_key: str = "date", sha_key: str = "selection_sha256") -> dict:
    """Resume only a complete, SHA-bound selection pair; never repair partial output."""
    if not path.is_file() or not freeze_path.is_file():
        raise Stop("STOP_PARTIAL_LANE_ARTIFACT:" + str(path.parent))
    selection = json.loads(path.read_text(encoding="utf-8"))
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    if selection.get(date_key) != date or freeze.get(sha_key) != digest(path) or freeze.get("date", date) != date:
        raise Stop("STOP_RESUME_SELECTION_SHA_OR_DATE:" + str(path))
    return selection


def _assert_before_cutoff(date: str) -> None:
    if datetime.now(timezone.utc) >= conservative_cutoff(date):
        raise Stop("STOP_CONSERVATIVE_CUTOFF_PASSED")


def _run_b1_boundary(operation) -> dict:
    """Capture ordinary B1-only errors after the seven-lane audit passes."""
    try:
        return operation()
    except Exception as error:
        return {"status": "STOPPED", "reason": str(error),
                "exception_type": type(error).__name__, "exception_message": str(error),
                "result_access_count": 0, "formal_lanes_affected": False}


def run_all(date: str, *, root: Path = ROOT, calendar: Path = CALENDAR,
            known_first_start_at: str | None = None,
            special_condition: bool = False) -> dict:
    """Single date-scoped orchestration of existing frozen PRE runners."""
    if date < CONSERVATIVE_AUTHORITY_START:
        raise Stop("STOP_RUN_ALL_NOT_EFFECTIVE")
    paths = Paths(date, root)
    venues = calendar_venues(date, calendar)
    if special_condition:
        raise Stop("STOP_SPECIAL_SCHEDULE_CONDITION")
    if known_first_start_at is not None:
        try:
            known = datetime.fromisoformat(known_first_start_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise Stop("STOP_KNOWN_EARLY_OR_INVALID_FIRST_START") from error
        if (known.tzinfo is None or known.astimezone(JST).date() != conservative_cutoff(date).date()
                or known <= conservative_cutoff(date)):
            raise Stop("STOP_KNOWN_EARLY_OR_INVALID_FIRST_START")
    _assert_before_cutoff(date)
    result_dir = root / "data/raw/target/daily_result_list"
    if any((result_dir / f"{prefix}_{date}.csv").exists() for prefix in ("馬番順着順", "着順馬番")):
        raise Stop("STOP_TARGET_RESULT_ALREADY_PRESENT")
    from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
    raw = root / "data/raw/prediction_input"
    sources = {kind: raw / f"{kind}{date[2:]}.CSV" for kind in ("DG", "DE", "DS")}
    input_sha = {kind: digest(path) for kind, path in sources.items()}
    bundle = TargetBulkPredictionInputAdapterV1().load(sources["DG"], sources["DE"], sources["DS"])
    if bundle.date != date or {rid.split("_")[2] for rid in bundle.races} != {VENUE_IDS[v] for v in venues}:
        raise Stop("STOP_INPUT_DATE_OR_CALENDAR_VENUES")
    race_count = len(bundle.races)
    horse_count = sum(len(r.today_entries) for r in bundle.races.values())
    h = helper(date, root=root, calendar=calendar)
    if paths.first_start.exists():
        evidence = h.first_start_evidence(paths.first_start, root=root)
        if evidence.get("authority_kind") != CONSERVATIVE_AUTHORITY_KIND:
            raise Stop("STOP_RUN_ALL_UNEXPECTED_FIRST_START_AUTHORITY")
    else:
        create_conservative_authority(date, root=root, calendar=calendar,
                                      known_first_start_at=known_first_start_at)
        evidence = h.first_start_evidence(paths.first_start, root=root)
    _assert_before_cutoff(date)

    from review import prospective_prediction_runner_v1 as current_runner
    if paths.current.exists():
        h.current_authority(root, paths.current)
    else:
        current_runner.run(date, trace=True, output_root=paths.current)
        h.current_authority(root, paths.current)
    index = h.load(paths.current / "race_index.json")["race_index"]
    if len(index) != race_count or sum(int(x["horse_count"]) for x in index) != horse_count:
        raise Stop("STOP_CURRENT_INPUT_POPULATION")
    if paths.current.joinpath("formal_freeze_attestation.json").exists():
        attest = h.load(paths.current / "formal_freeze_attestation.json")
        if (attest.get("date") != date or attest.get("result_access_count") != 0 or
                attest.get("prediction_manifest_sha256") != digest(paths.current / "prediction_manifest.json") or
                attest.get("first_start_evidence_sha256") != digest(paths.first_start) or
                attest.get("first_start_at") != conservative_cutoff(date).isoformat() or
                (root / attest.get("first_start_evidence_path", "")).resolve() != paths.first_start.resolve() or
                h.moment(attest["freeze_timestamp_utc"]) >= conservative_cutoff(date)):
            raise Stop("STOP_RESUME_CURRENT_ATTESTATION")
    else:
        _assert_before_cutoff(date)
        h.freeze_current(root=root, current=paths.current, evidence_path=paths.first_start)

    if paths.snapshot_manifest.exists():
        registry = h.load(paths.snapshot_manifest)
        entries = [e for e in registry.get("entries", []) if e.get("date") == date]
    else:
        raise Stop("STOP_SNAPSHOT_MANIFEST_MISSING")
    if entries:
        from review import frozen_pl_v1_jockey_offset_provisional_v1 as plj
        if (len(entries) != 1 or entries[0].get("current_pre_sha256") != digest(paths.current / "prediction_manifest.json") or
                entries[0].get("ds_snapshot_sha256") != input_sha["DS"]):
            raise Stop("STOP_RESUME_SNAPSHOT_ENTRY")
        plj.validate_formal_manifest(date)
    else:
        _assert_before_cutoff(date)
        h.append_snapshot(root=root, current=paths.current, manifest_path=paths.snapshot_manifest)

    if paths.exp024.exists():
        selection = _verified_selection(paths.exp024 / "selection.json", paths.exp024 / "selection_freeze.json", date=date)
        seal = h.load(paths.exp024 / "selection_freeze.json")
        if (selection.get("current_prediction_sha256") != digest(paths.current / "prediction_manifest.json") or
                selection.get("pl_model_sha256") != "418fc9b4cefe1757f79dfc22a7d49b7c1592b91084cca97f88f55bb1389b0585" or
                seal.get("schedule_source_sha256") != digest(paths.first_start) or
                seal.get("result_access_before_freeze") is not False or
                h.moment(seal["selection_freeze_timestamp"]) >= conservative_cutoff(date)):
            raise Stop("STOP_RESUME_EXP024_AUTHORITY")
    else:
        _assert_before_cutoff(date)
        h.freeze_exp024(current=paths.current, evidence=paths.first_start,
                        approval=root / "docs/KeibaAI_EXP024_HUMAN_FINAL_APPROVAL_V1.json",
                        output=paths.exp024, root=root)

    from review import current_unconverged_rank1_prospective_shadow_v2 as rank1
    if paths.rank1.exists():
        selection = _verified_selection(paths.rank1 / "pre_selection.json", paths.rank1 / "freeze_manifest.json",
                                        date=date, date_key="target_date")
        rank_freeze = h.load(paths.rank1 / "freeze_manifest.json")
        if (selection.get("input_pre_sha256") != digest(paths.current / "prediction_manifest.json") or
                rank_freeze.get("exp024_freeze_sha256") != digest(paths.exp024 / "selection_freeze.json") or
                rank_freeze.get("first_start_authority_sha256") != digest(paths.first_start) or
                rank_freeze.get("result_access") != 0 or
                h.moment(rank_freeze["freeze_timestamp_jst"]) >= conservative_cutoff(date)):
            raise Stop("STOP_RESUME_RANK1_AUTHORITY")
    else:
        _assert_before_cutoff(date)
        rank1.run(date)

    from review import pl_forward_shadow_v1 as forward
    if paths.pl_forward.exists():
        pl = h.load(paths.pl_forward)
        if (pl.get("input_pre_artifact_sha256") != digest(paths.current / "prediction_manifest.json") or
                pl.get("model_sha256") != "418fc9b4cefe1757f79dfc22a7d49b7c1592b91084cca97f88f55bb1389b0585" or
                pl.get("result_fields_used") is not False or len(pl.get("races", [])) != race_count):
            raise Stop("STOP_RESUME_PL_FORWARD_AUTHORITY")
    else:
        _assert_before_cutoff(date)
        forward.run_inference(paths.current, paths.pl_forward)

    if paths.plj.exists():
        selection = h.load(paths.plj / "selection.json")
        audit = h.load(paths.plj / "provisional_audit.json")
        if (selection.get("date") != date or selection.get("current_pre_sha256") != digest(paths.current / "prediction_manifest.json") or
                selection.get("pl_prediction_sha256") != digest(paths.pl_forward) or
                selection.get("result_access_count") != 0 or audit.get("selection_sha256") != digest(paths.plj / "selection.json") or
                audit.get("first_race_timestamp_authority_sha256") != digest(paths.first_start) or
                h.moment(audit["freeze_timestamp"]) >= conservative_cutoff(date)):
            raise Stop("STOP_RESUME_PL_JOCKEY_AUTHORITY")
    else:
        _assert_before_cutoff(date)
        h.freeze_pl_jockey(current=paths.current, pl_prediction=paths.pl_forward, evidence=paths.first_start,
                           de=sources["DE"], ds=sources["DS"], output=paths.plj, root=root)

    a_root = h.ANEW / "reports/a_new_prospective_shadow_v1"
    completion = a_root / f"formal_completion_{date}.json"
    if completion.exists():
        value = h.load(completion)
        if value.get("date") != date or value.get("result_access_count") != 0 or any(
                digest(Path(item["path"])) != item["sha256"] for item in value.get("artifacts", [])):
            raise Stop("STOP_RESUME_A_NEW_COMPLETION")
    else:
        _assert_before_cutoff(date)
        h.create_a_new_completion(root=root, current=paths.current, exp024=paths.exp024,
                                  rank1=paths.rank1, plj=paths.plj, output=completion)
    a_pre = a_root / "daily_pre" / date
    if a_pre.exists():
        a_selection = _verified_selection(a_pre / "selection.json", a_pre / "freeze_manifest.json", date=date)
        a_freeze = h.load(a_pre / "freeze_manifest.json")
        if (a_selection.get("current_pre_sha256") != digest(paths.current / "prediction_manifest.json") or
                a_selection.get("formal_completion_sha256") != digest(completion) or
                a_freeze.get("result_access_count_at_freeze") != 0 or
                h.moment(a_freeze["freeze_timestamp_utc"]) >= conservative_cutoff(date)):
            raise Stop("STOP_RESUME_A_NEW_AUTHORITY")
    else:
        _assert_before_cutoff(date)
        h.run_a_new_existing(completion=completion, current=paths.current, formal=paths.plj,
                             approval=a_root / "human_operational_approval_v1.json")
        _verified_selection(a_pre / "selection.json", a_pre / "freeze_manifest.json", date=date)

    e_root = h.E1 / "reports/e1_full_field_allocation_prospective_shadow_v1"
    priority = e_root / "authority" / f"priority_completion_{date}.json"
    if priority.exists():
        value = h.load(priority)
        if value.get("date") != date or value.get("result_access_count") != 0 or any(
                digest(Path(item["path"])) != item["sha256"] for item in value.get("artifacts", [])):
            raise Stop("STOP_RESUME_E1_COMPLETION")
    else:
        _assert_before_cutoff(date)
        h.create_e1_completion(current=paths.current, exp024=paths.exp024, rank1=paths.rank1, plj=paths.plj,
                               a_new_status=None, a_new_freeze=a_pre / "freeze_manifest.json",
                               authority_root=e_root / "authority")
    e_pre = e_root / "daily_pre" / date
    if e_pre.exists():
        e_selection = _verified_selection(e_pre / "selection.json", e_pre / "freeze_manifest.json", date=date)
        e_freeze = h.load(e_pre / "freeze_manifest.json")
        if (e_selection.get("current_formal_pre_sha256") != digest(paths.current / "prediction_manifest.json") or
                e_selection.get("priority_completion_sha256") != digest(priority) or
                e_selection.get("exp024_sealed_selection_sha256") != digest(paths.exp024 / "selection.json") or
                e_freeze.get("result_access_count") != 0 or
                h.moment(e_freeze["e1_freeze_timestamp"]) >= conservative_cutoff(date)):
            raise Stop("STOP_RESUME_E1_AUTHORITY")
    else:
        _assert_before_cutoff(date)
        h.run_e1_existing(priority=priority, exp024=paths.exp024, current=paths.current,
                          approval=e_root / "authority/human_operational_approval_v1.json")
        _verified_selection(e_pre / "selection.json", e_pre / "freeze_manifest.json", date=date)

    if paths.step1.exists():
        step1 = h.load(paths.step1)
        if (step1.get("result_access") != 0 or step1.get("input_pre_sha256", {}).get("pl_jockey") != digest(paths.plj / "selection.json") or
                step1.get("input_pre_sha256", {}).get("e1") != digest(e_pre / "selection.json") or
                h.moment(step1["created_at_jst"]) >= conservative_cutoff(date)):
            raise Stop("STOP_RESUME_STEP1_AUTHORITY")
    else:
        _assert_before_cutoff(date)
        h.freeze_step1(plj_path=paths.plj / "selection.json", e1_path=e_pre / "selection.json",
                       current=paths.current, evidence=paths.first_start, output=paths.step1, root=root)

    from review import independent_race_selection_prospective_pre as independent
    if paths.independent.exists():
        index_hash = h.load(paths.independent / "artifact_hashes.json")["indexed_artifacts"]
        if any(digest(paths.independent / name) != expected for name, expected in index_hash.items()):
            raise Stop("STOP_RESUME_INDEPENDENT_SHA")
        ind = h.load(paths.independent / "selection_manifest.json")
        if (ind.get("date") != date or ind.get("result_data_access_count") != 0 or
                ind.get("source_prediction_manifest_sha256") != digest(paths.current / "prediction_manifest.json") or
                ind.get("protocol_sha256") != digest(root / "docs/independent_race_selection_prospective_protocol_v1.json")):
            raise Stop("STOP_RESUME_INDEPENDENT_DATE_OR_CURRENT")
    else:
        _assert_before_cutoff(date)
        independent.run(date, paths.current, paths.independent)

    _assert_before_cutoff(date)
    audit = h.audit(root=root, current=paths.current, evidence=paths.first_start,
                    manifest_path=paths.snapshot_manifest,
                    lane_artifacts={"EXP024": paths.exp024 / "selection_freeze.json",
                                    "CURRENT_RANK1": paths.rank1 / "freeze_manifest.json",
                                    "PL_JOCKEY": paths.plj / "provisional_audit.json",
                                    "A_NEW": a_pre / "freeze_manifest.json", "E1": e_pre / "freeze_manifest.json",
                                    "INDEPENDENT_V5": paths.independent / "artifact_hashes.json"},
                    step1_path=paths.step1)
    if audit.get("status") != "PASS":
        raise Stop("STOP_SEVEN_LANE_AUDIT")
    # B1 is an additive diagnostic. Its failure is reported independently and
    # must not change the seven-lane Formal PRE completion status.
    from review import b1_prospective_diagnostic_v1 as b1
    e1_pre = h.E1 / "reports/e1_full_field_allocation_prospective_shadow_v1" / "daily_pre" / date
    b1_record = _run_b1_boundary(lambda: b1.freeze_pre(
            date, current_root=paths.current, plj_path=paths.plj / "selection.json",
            plj_freeze=paths.plj / "provisional_audit.json",
            e1_path=e1_pre / "selection.json", e1_freeze=e1_pre / "freeze_manifest.json",
            first_start_path=paths.first_start,
            output_root=root / f"reports/formal_pre_daily/{date}/b1_diagnostic"))
    summary = _daily_summary(date, root=root, paths=paths, input_sha=input_sha,
                             race_count=race_count, horse_count=horse_count, h=h,
                             a_pre=a_pre, e_pre=e_pre)
    if paths.daily_summary.exists():
        if h.load(paths.daily_summary) != summary:
            # Time of summary creation is not recomputed during a resume.
            prior = h.load(paths.daily_summary)
            if {k:v for k,v in prior.items() if k != "generated_at_jst"} != {
                    k:v for k,v in summary.items() if k != "generated_at_jst"}:
                raise Stop("STOP_RESUME_DAILY_SUMMARY_MISMATCH")
        return {"date": date, "status": "COMPLETE", "summary_path": str(paths.daily_summary),
                "summary_sha256": digest(paths.daily_summary), "resumed": True,
                "b1_diagnostic": b1_record}
    paths.daily_summary.parent.mkdir(parents=True, exist_ok=True)
    with paths.daily_summary.open("xb") as stream:
        stream.write((json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
    return {"date": date, "status": "COMPLETE", "summary_path": str(paths.daily_summary),
            "summary_sha256": digest(paths.daily_summary), "resumed": False,
            "b1_diagnostic": b1_record}


def _daily_summary(date: str, *, root: Path, paths: Paths, input_sha: dict,
                   race_count: int, horse_count: int, h, a_pre: Path, e_pre: Path) -> dict:
    index = h.load(paths.current / "race_index.json")["race_index"]
    races = [h.load(paths.current / item["artifact"]) for item in index]
    names = {(p["race_id"], int(horse["horse_number"])): horse["horse_name"]
             for p in races for horse in p["ranked_results"]}
    exp = h.load(paths.exp024 / "selection.json")
    rank = h.load(paths.rank1 / "pre_selection.json")
    plj = h.load(paths.plj / "selection.json")
    a_new = h.load(a_pre / "selection.json")
    e1 = h.load(e_pre / "selection.json")
    ind = h.load(paths.independent / "selection_manifest.json")
    members = {
        "CURRENT": [(p["race_id"], int(horse["horse_number"])) for p in races for horse in p["buys"]],
        "EXP024": [(p["race_id"], int(n)) for p in exp["races"] for n in p["treatment_selected_horses"]],
        "CURRENT_RANK1": [(p["race_id"], int(p["selected_horse_number"])) for p in rank["selections"]],
        "PL_JOCKEY": [(p["race_id"], int(n)) for p in plj["races"] for n in p["candidate_selected_horses"]],
        "A_NEW": [(p["race_id"], int(n)) for p in a_new["races"] for n in p["a_new_selected_horses"]],
        "E1": [(p["race_id"], int(p["horse_number"])) for p in e1["selected_horses"]],
        "INDEPENDENT_V5": [(p["race_id"], int(horse["horse_number"])) for p in ind["races"] for horse in p["selected_horses"]],
    }
    reverse_venues = {value: key for key, value in VENUE_IDS.items()}
    selected = {}
    for lane, rows in members.items():
        if len(rows) != len(set(rows)) or not set(rows) <= set(names):
            raise Stop("STOP_SUMMARY_HORSE_IDENTITY:" + lane)
        selected[lane] = [{"venue": reverse_venues[rid.split("_")[2]],
                           "race_number": int(rid.rsplit("_", 1)[1][:-1]),
                           "race_id": rid, "horse_number": number,
                           "horse_name": names[rid, number]}
                          for rid, number in sorted(rows)]
    artifacts = {
        "CURRENT": (paths.current / "prediction_manifest.json", paths.current / "formal_freeze_attestation.json"),
        "EXP024": (paths.exp024 / "selection.json", paths.exp024 / "selection_freeze.json"),
        "CURRENT_RANK1": (paths.rank1 / "pre_selection.json", paths.rank1 / "freeze_manifest.json"),
        "PL_JOCKEY": (paths.plj / "selection.json", paths.plj / "provisional_audit.json"),
        "A_NEW": (a_pre / "selection.json", a_pre / "freeze_manifest.json"),
        "E1": (e_pre / "selection.json", e_pre / "freeze_manifest.json"),
        "INDEPENDENT_V5": (paths.independent / "selection_manifest.json", paths.independent / "artifact_hashes.json"),
    }
    freeze_fields = {"CURRENT": "freeze_timestamp_utc", "EXP024": "selection_freeze_timestamp",
                     "CURRENT_RANK1": "freeze_timestamp_jst", "PL_JOCKEY": "freeze_timestamp",
                     "A_NEW": "freeze_timestamp_utc", "E1": "e1_freeze_timestamp",
                     "INDEPENDENT_V5": "generated_at"}
    lane_records = {}
    for lane, (selection_path, authority_path) in artifacts.items():
        authority = h.load(authority_path)
        frozen = authority.get(freeze_fields[lane])
        if lane == "INDEPENDENT_V5":
            frozen = h.load(paths.independent / "provenance.json")["generated_at"]
        if frozen is None or h.moment(frozen) >= conservative_cutoff(date):
            raise Stop("STOP_SUMMARY_FREEZE_TIME:" + lane)
        lane_records[lane] = {"selection_path": str(selection_path.relative_to(root)) if selection_path.is_relative_to(root) else str(selection_path),
                              "selection_sha256": digest(selection_path),
                              "authority_path": str(authority_path.relative_to(root)) if authority_path.is_relative_to(root) else str(authority_path),
                              "authority_sha256": digest(authority_path),
                              "freeze_or_execution_time": frozen,
                              "selected_count": len(selected[lane]), "selected_horses": selected[lane],
                              "status": "COMPLETE"}
    return {"date": date, "status": "COMPLETE", "role": "FORMAL_PRE_FUTURE_ONLY",
            "authority_kind": CONSERVATIVE_AUTHORITY_KIND,
            "official_time_verified": False, "first_start_at_semantics": "CONSERVATIVE_OPERATIONAL_FREEZE_CUTOFF_NOT_OFFICIAL_START",
            "conservative_cutoff_at": conservative_cutoff(date).isoformat(),
            "first_start_authority_sha256": digest(paths.first_start),
            "race_count": race_count, "horse_count": horse_count, "input_sha256": input_sha,
            "generated_at_jst": datetime.now(JST).isoformat(), "result_access_count": 0,
            "lanes": lane_records}


def main() -> None:
    parser = argparse.ArgumentParser(description="Date-scoped, Result-blind Formal PRE authority helper")
    parser.add_argument("step", choices=("first-start", "first-start-auto", "attest", "register", "a-new-completion", "e1-completion", "audit", "run-all"))
    parser.add_argument("--date", required=True, type=checked_date)
    parser.add_argument("--snapshot", type=Path, action="append", default=[])
    parser.add_argument("--first-start-at")
    parser.add_argument("--first-race")
    parser.add_argument("--schedule-url")
    parser.add_argument("--entry-page-url")
    parser.add_argument("--operator-verified", action="store_true")
    parser.add_argument("--known-first-start-at")
    parser.add_argument("--special-condition", action="store_true")
    parser.add_argument("--step1-artifact", type=Path)
    args = parser.parse_args()
    if args.step == "run-all":
        print(json.dumps(run_all(args.date, known_first_start_at=args.known_first_start_at,
                                 special_condition=args.special_condition), ensure_ascii=False, sort_keys=True))
        return
    if args.step == "first-start-auto":
        result = create_conservative_authority(args.date, known_first_start_at=args.known_first_start_at,
                                               special_condition=args.special_condition)
        print(json.dumps({"date": args.date, "authority_sha256": result,
                          "official_time_verified": False}, ensure_ascii=False, sort_keys=True))
        return
    h = helper(args.date)
    p = Paths(args.date)
    if args.step == "first-start":
        if not all((args.first_start_at, args.first_race, args.schedule_url, args.entry_page_url)):
            raise Stop("STOP_FIRST_START_ARGUMENTS")
        if len(args.snapshot) < 2 or any(not path.resolve().is_relative_to(p.official_snapshots.resolve()) for path in args.snapshot):
            raise Stop("STOP_OFFICIAL_SNAPSHOT_SCOPE")
        result = h.create_first_start(root=ROOT, snapshot_paths=args.snapshot, first_start_at=args.first_start_at,
                                      first_race=args.first_race, schedule_url=args.schedule_url,
                                      entry_page_url=args.entry_page_url, operator_verified=args.operator_verified)
    elif args.step == "attest":
        result = h.freeze_current(root=ROOT, current=p.current, evidence_path=p.first_start)
    elif args.step == "register":
        result = h.append_snapshot(root=ROOT, current=p.current, manifest_path=p.snapshot_manifest)
    elif args.step == "a-new-completion":
        result = h.create_a_new_completion(root=ROOT, current=p.current, exp024=p.exp024, rank1=p.rank1,
                                           plj=p.plj, output=h.ANEW / f"reports/a_new_prospective_shadow_v1/formal_completion_{args.date}.json")
    elif args.step == "e1-completion":
        a = h.ANEW / "reports/a_new_prospective_shadow_v1"
        result = h.create_e1_completion(current=p.current, exp024=p.exp024, rank1=p.rank1, plj=p.plj,
                                        a_new_status=(a / f"date_status/{args.date}/status.json") if (a / f"date_status/{args.date}/status.json").is_file() else None,
                                        a_new_freeze=(a / f"daily_pre/{args.date}/freeze_manifest.json") if (a / f"daily_pre/{args.date}/freeze_manifest.json").is_file() else None,
                                        authority_root=h.E1 / "reports/e1_full_field_allocation_prospective_shadow_v1/authority")
    else:
        a = h.ANEW / "reports/a_new_prospective_shadow_v1"
        e = h.E1 / "reports/e1_full_field_allocation_prospective_shadow_v1"
        result = h.audit(root=ROOT, current=p.current, evidence=p.first_start, manifest_path=p.snapshot_manifest,
                         lane_artifacts={"EXP024": p.exp024 / "selection_freeze.json",
                                         "CURRENT_RANK1": p.rank1 / "freeze_manifest.json",
                                         "PL_JOCKEY": p.plj / "provisional_audit.json",
                                         "A_NEW": a / f"daily_pre/{args.date}/freeze_manifest.json",
                                         "E1": e / f"daily_pre/{args.date}/freeze_manifest.json",
                                         "INDEPENDENT_V5": p.independent / "artifact_hashes.json"},
                         step1_path=args.step1_artifact)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
