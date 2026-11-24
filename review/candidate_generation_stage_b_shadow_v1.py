"""Generator-independent, isolated Stage-B shadow orchestration.

This module is intentionally not connected to TargetTrialAdapter, main.py, or
any production entry point.  It accepts an explicit Exact5 packet only.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from engine.buy_v1_rc1_engine import BUYV1RC1Engine
from engine.decision_engine import DecisionEngine
from engine.race_decision_buy_synchronizer import RaceDecisionBuySynchronizer
from engine.race_decision_engine import RaceDecisionEngine


NON_CANDIDATE_DECISION_RANK_SENTINEL = 999
EXACT5_TIE_BREAK_ID = "probability_desc__shadow_ai_rank_asc__horse_number_asc"


class StageBStop(RuntimeError):
    """Fail-closed state; no Stage-B BUY artifact is returned."""


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _number(value):
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class CandidateGenerationStageBShadow:
    """External B2 seam implementing copy → validate → commit semantics."""

    def __init__(self, decision_engine=None, race_decision_engine=None, rc1_engine=None, synchronizer=None):
        self.decision_engine = decision_engine or DecisionEngine()
        self.race_decision_engine = race_decision_engine or RaceDecisionEngine()
        self.rc1_engine = rc1_engine or BUYV1RC1Engine()
        self.synchronizer = synchronizer or RaceDecisionBuySynchronizer()

    def race_context_snapshot(self, full_race_context, race_context=None):
        rows = self._assert_pre_bridge(full_race_context)
        context = race_context if isinstance(race_context, dict) else {}
        # Exact local reproduction of DecisionEngine._best_score.  Do not call
        # the private method: this shadow contract remains coupled by explicit
        # source semantics, not by a private runtime hook.
        scores = [self._current_decision_engine_best_score(row) for row in rows]
        scores = [score for score in scores if score is not None]
        identity = sorted((int(row["horse_number"]), str(row["horse_name"])) for row in rows)
        snapshot = {
            "source_marker": "FULL_RACE_CONTEXT_ONLY",
            "race_id": context.get("race_id", ""),
            "date": context.get("date", ""),
            "venue": context.get("venue", ""),
            "race_number": context.get("race_number", ""),
            "full_field_horse_identity_set": identity,
            "full_field_horse_count": len(rows),
            "full_field_identity_hash": _hash(identity),
            "top_score": max(scores) if scores else None,
            "bottom_score": min(scores) if scores else None,
            "race_structure": deepcopy(context.get("race_structure", {})),
            "structure_flags": deepcopy(context.get("structure_flags", {})),
            "baseline_race_decision_result": deepcopy(context.get("baseline_race_decision_result")),
        }
        snapshot["snapshot_hash"] = _hash(snapshot)
        return snapshot

    @staticmethod
    def _current_decision_engine_best_score(row):
        for key in ("adjusted_score", "integrated_score", "weighted_score", "final_score"):
            value = _number(row.get(key))
            if value is not None:
                return value
        return None

    def run(self, candidate_packet, full_race_context, race_context=None, *, decision_rank_override=None):
        """Run the current authority chain on an isolated working copy.

        On any failure this returns STOP metadata only.  It never returns a
        partially mutated horse list or a valid Stage-B BUY artifact.
        """
        original = deepcopy(full_race_context)
        try:
            snapshot = self.race_context_snapshot(full_race_context, race_context)
            packet = self._validate_packet(candidate_packet, snapshot)
            working = deepcopy(full_race_context)
            bridge = self._bridge(working)
            candidates = {item["horse_number"]: item for item in packet["exact5"]}
            override = self._validate_decision_rank_override(decision_rank_override, candidates)
            for horse in working:
                number = int(horse["horse_number"])
                item = candidates.get(number)
                horse["current_rank"] = horse.get("rank")
                horse["candidate_rank"] = item["candidate_rank"] if item else None
                horse["decision_rank"] = (
                    override[number] if item and override is not None
                    else item["candidate_rank"] if item
                    else NON_CANDIDATE_DECISION_RANK_SENTINEL
                )
                horse["rank"] = horse["decision_rank"]  # preserved by ShadowBUYDecisionEngine._with_ranks
                horse["stage_b_candidate_probability"] = item["candidate_probability"] if item else None
                rank_context = {
                    "rank": horse["decision_rank"],
                    "top_score": snapshot["top_score"],
                    "bottom_score": snapshot["bottom_score"],
                    "baseline_race_decision_result": deepcopy(snapshot["baseline_race_decision_result"]),
                }
                decision = self.decision_engine.decide(horse, rank_context)
                horse.update(decision)
                horse["stage_b_pre_rc1_decision"] = decision.get("decision")
            race_input = {
                "race_id": snapshot["race_id"], "race_structure": deepcopy(snapshot["race_structure"]),
                "structure_flags": deepcopy(snapshot["structure_flags"]),
                "baseline_race_decision_result": deepcopy(snapshot["baseline_race_decision_result"]),
            }
            race_before = self.race_decision_engine.decide(race_input, working)
            rc1 = self.rc1_engine.evaluate({"race_id": snapshot["race_id"], "race_decision": race_before.get("race_decision"), "race_confidence": race_before.get("race_confidence")}, working)
            self._assert_shadow_bridge(rc1, bridge, len(working))
            self._assert_rc1_bridge(rc1, bridge, len(working))
            self.rc1_engine.apply_to_horses(working, rc1)
            self._assert_final_bridge(working, bridge)
            if override is not None:
                for horse in working:
                    if horse.get("decision_rank") == NON_CANDIDATE_DECISION_RANK_SENTINEL and str(horse.get("decision", "")).upper() == "BUY":
                        raise StageBStop("STOP_OVERRIDE_SENTINEL_BUY_INVARIANT")
            for horse in working:
                if int(horse["horse_number"]) not in candidates and str(horse.get("decision", "")).upper() == "BUY":
                    raise StageBStop("STOP_NON_CANDIDATE_BUY_INVARIANT")
            synchronized = self.synchronizer.synchronize(race_before, working, rc1)
            trace = self._trace(snapshot, packet, working, rc1, synchronized, candidates)
            return {"status": "COMMITTED", "snapshot": snapshot, "race_decision": synchronized, "horses": working, "trace": trace}
        except StageBStop as error:
            if original != full_race_context:
                raise AssertionError("STAGE_B_INPUT_MUTATED")
            return {"status": "STOP", "failure_state": str(error), "valid_stage_b_buy_artifact": False}

    def _assert_pre_bridge(self, rows):
        if not isinstance(rows, list) or not rows:
            raise StageBStop("STOP_MISSING_NUMBER")
        numbers, names = set(), set()
        output = []
        for row in rows:
            if not isinstance(row, dict) or row.get("horse_number") is None:
                raise StageBStop("STOP_MISSING_NUMBER")
            if not str(row.get("horse_name") or ""):
                raise StageBStop("STOP_MISSING_NAME")
            number, name = int(row["horse_number"]), str(row["horse_name"])
            if number in numbers: raise StageBStop("STOP_DUPLICATE_NUMBER")
            if name in names: raise StageBStop("STOP_DUPLICATE_NAME")
            numbers.add(number); names.add(name); output.append(row)
        return output

    def _bridge(self, rows):
        self._assert_pre_bridge(rows)
        return {int(row["horse_number"]): str(row["horse_name"]) for row in rows}

    def _validate_packet(self, packet, snapshot):
        if not isinstance(packet, dict): raise StageBStop("STOP_CANDIDATE_PACKET_MISSING")
        required = ("race_id", "race_context_snapshot_hash", "generator_id", "generator_version_hash", "generator_recipe_freeze_hash", "tie_break_id", "exact5")
        if any(packet.get(key) in (None, "") for key in required[:-1]) or packet.get("tie_break_id") != EXACT5_TIE_BREAK_ID:
            raise StageBStop("STOP_CANDIDATE_PROVENANCE_MISSING")
        if packet["race_id"] != snapshot["race_id"] or packet["race_context_snapshot_hash"] != snapshot["snapshot_hash"]:
            raise StageBStop("STOP_RACE_CONTEXT_MISMATCH")
        exact5 = packet.get("exact5")
        if not isinstance(exact5, list) or len(exact5) != 5: raise StageBStop("STOP_CANDIDATE_COUNT_MISMATCH")
        allowed = dict(snapshot["full_field_horse_identity_set"]); seen = set()
        for item in exact5:
            if not isinstance(item, dict) or item.get("horse_number") is None or item.get("candidate_rank") is None or item.get("candidate_probability") is None:
                raise StageBStop("STOP_CANDIDATE_IDENTITY_MISSING")
            number = int(item["horse_number"]); name = str(item.get("horse_name") or "")
            if number in seen or number not in allowed or allowed[number] != name: raise StageBStop("STOP_NUMBER_NAME_MISMATCH")
            seen.add(number)
        if sorted(int(item["candidate_rank"]) for item in exact5) != [1,2,3,4,5]: raise StageBStop("STOP_CANDIDATE_RANK_INVALID")
        return packet

    @staticmethod
    def _validate_decision_rank_override(override, candidates):
        """Validate the generic Exact5 → decision-rank boundary fail-closed."""
        if override is None:
            return None
        if not isinstance(override, dict):
            raise StageBStop("STOP_OVERRIDE_INVALID_TYPE")
        candidate_numbers = set(candidates)
        for number in override:
            if isinstance(number, bool) or not isinstance(number, int):
                raise StageBStop("STOP_OVERRIDE_INVALID_HORSE_NUMBER")
        keys = set(override)
        if keys - candidate_numbers:
            raise StageBStop("STOP_OVERRIDE_OUTSIDE_CANDIDATE")
        if candidate_numbers - keys:
            raise StageBStop("STOP_OVERRIDE_INCOMPLETE")
        active = []
        for number, rank in override.items():
            if isinstance(rank, bool) or not isinstance(rank, int) or rank not in {1, 2, 3, 4, 5, NON_CANDIDATE_DECISION_RANK_SENTINEL}:
                raise StageBStop("STOP_OVERRIDE_INVALID_RANK")
            if rank != NON_CANDIDATE_DECISION_RANK_SENTINEL:
                active.append(rank)
        if len(active) != len(set(active)):
            raise StageBStop("STOP_OVERRIDE_DUPLICATE_ACTIVE_RANK")
        return dict(override)

    def _assert_shadow_bridge(self, rc1, bridge, expected):
        shadow = rc1.get("shadow_result", {}) if isinstance(rc1, dict) else {}
        records = shadow.get("horse_records", [])
        if len(records) != expected: raise StageBStop("STOP_COUNT_MISMATCH")
        for row in records:
            number = row.get("horse_number")
            if number is None or int(number) not in bridge or row.get("horse_name") != bridge[int(number)]:
                raise StageBStop("STOP_NUMBER_NAME_MISMATCH")

    def _assert_rc1_bridge(self, rc1, bridge, expected):
        records = rc1.get("horse_records", []) if isinstance(rc1, dict) else []
        if len(records) != expected: raise StageBStop("STOP_COUNT_MISMATCH")
        by_name = {name:number for number,name in bridge.items()}
        if len(by_name) != len(bridge): raise StageBStop("STOP_DUPLICATE_NAME")
        for row in records:
            if row.get("horse_name") not in by_name: raise StageBStop("STOP_RC1_NAME_NOT_FOUND")

    def _assert_final_bridge(self, rows, bridge):
        if len(rows) != len(bridge): raise StageBStop("STOP_COUNT_MISMATCH")
        for row in rows:
            number = row.get("horse_number")
            if number is None or int(number) not in bridge or row.get("horse_name") != bridge[int(number)]:
                raise StageBStop("STOP_FINAL_IDENTITY_MISMATCH")

    def _trace(self, snapshot, packet, rows, rc1, synchronized, candidates):
        rc1_by_name = {r.get("horse_name"):r for r in rc1.get("horse_records", [])}
        horses=[]
        for row in rows:
            number=int(row["horse_number"]); rec=rc1_by_name.get(row["horse_name"],{})
            horses.append({"race_id":snapshot["race_id"],"horse_number":number,"horse_name":row["horse_name"],"is_candidate_member":number in candidates,"current_rank":row.get("current_rank"),"candidate_rank":row.get("candidate_rank"),"decision_rank":row.get("decision_rank"),"shadow_ai_rank":row.get("shadow_ai_rank"),"generator_id":packet["generator_id"],"generator_version_hash":packet["generator_version_hash"],"generator_recipe_freeze_hash":packet["generator_recipe_freeze_hash"],"candidate_probability":row.get("stage_b_candidate_probability"),"stage_b_pre_rc1_decision":row.get("stage_b_pre_rc1_decision"),"rc1_decision":rec.get("rc1_decision"),"final_stage_b_decision":row.get("decision"),"identity_bridge_status":"PASS","failure_state":None})
        buys=[r["horse_number"] for r in horses if r["final_stage_b_decision"]=="BUY"]
        return {"race":{"race_id":snapshot["race_id"],"generator_id":packet["generator_id"],"race_context_snapshot_hash":snapshot["snapshot_hash"],"full_field_count":len(rows),"candidate_count":len(candidates),"stage_b_final_buy_count":len(buys),"stage_b_final_buy_horse_numbers":buys,"race_decision_before_synchronization":synchronized.get("race_decision_original"),"race_decision_final":synchronized.get("race_decision_final"),"stop_status":"PASS","stop_reason":""},"horses":horses}
