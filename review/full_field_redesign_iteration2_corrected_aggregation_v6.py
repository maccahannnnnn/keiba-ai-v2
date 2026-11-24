"""Iteration 2 v6: canonical frozen-budget schema compatibility only."""
from __future__ import annotations
import csv
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from review import full_field_redesign_iteration2_corrected_aggregation_v5 as v5
from review import full_field_redesign_iteration2_corrected_aggregation_v4 as core

ROOT=v5.ROOT; INPUT=v5.INPUT; OUT=v5.OUT; TEMP_OUT=v5.TEMP_OUT; MANIFEST=v5.MANIFEST
Paths=v5.Paths; Stop=v5.Stop; ensure=v5.ensure; sha=v5.sha
CANONICAL_BUDGET_COLUMN="current_pre_buy_count"
REQUIRED_COLUMNS={"date","month","current_pre_buy_count","eligible_horse_count","eligible_race_count"}

def read_budget(path:Path, expected_dates:set[str]|None=None)->dict[str,int]:
    with path.open(encoding="utf-8-sig",newline="") as h:
        reader=csv.DictReader(h); header=set(reader.fieldnames or [])
        ensure(CANONICAL_BUDGET_COLUMN in header,"STOP_BUDGET_COLUMN_CURRENT_PRE_BUY_COUNT_MISSING")
        ensure(REQUIRED_COLUMNS<=header,"STOP_BUDGET_COLUMN_CURRENT_PRE_BUY_COUNT_MISSING")
        values:dict[str,int]={}
        for row in reader:
            date=str(row.get("date","")).strip(); ensure(bool(date),"STOP_DAILY_BUDGET_DATE_MISSING"); ensure(date not in values,"STOP_BUDGET_DUPLICATE_DATE")
            try:value=int(str(row[CANONICAL_BUDGET_COLUMN]).strip())
            except (TypeError,ValueError) as exc:raise Stop("STOP_BUDGET_CURRENT_PRE_BUY_COUNT_INVALID") from exc
            ensure(value>=0,"STOP_BUDGET_CURRENT_PRE_BUY_COUNT_INVALID"); values[date]=value
    if expected_dates is not None:ensure(expected_dates<=set(values),"STOP_DAILY_BUDGET_DATE_MISSING")
    return values

def budgets(paths:Paths, expected_dates:set[str]|None=None)->dict[str,int]:
    path=paths.iter1/"daily_current_buy_budget.csv";ensure(path.is_file() and sha(path)==core.EXPECTED_ITER1_BUDGET_SHA,"STOP_DAILY_BUDGET_MISMATCH")
    values=read_budget(path,expected_dates);ensure(len(values)==62,"STOP_DAILY_BUDGET_MISMATCH");return values

def assert_budget_conformance(frozen:dict[str,int], recomputed:dict[str,int])->None:
    ensure(frozen==recomputed,"STOP_DAILY_BUDGET_MISMATCH")

@contextmanager
def _v6_budget_path():
    old_core,old_v5=core.budgets,v5.budgets
    def reader(paths:Paths)->dict[str,int]:return budgets(paths)
    core.budgets=reader;v5.budgets=reader
    try:yield
    finally:core.budgets=old_core;v5.budgets=old_v5

def prepare(paths:Paths=Paths())->dict[str,Any]:
    """PRE-only identity freeze with the canonical budget schema."""
    core.frozen_gate(paths);rows=core.load_rows(paths);budget=budgets(paths,{str(row["date"]) for row in rows});core.direct_budget_conformance(paths,budget);core.baseline(rows,budget,paths);core.assert_pl_mass(rows)
    return core.prepare_result_manifest(rows,paths)

def execute_after_authorization(approved_manifest_sha:str|None,paths:Paths=Paths())->dict[str,Any]:
    """Future authorized v6 path; v5 semantics are otherwise unchanged."""
    rows=core.load_rows(paths);budgets(paths,{str(row["date"]) for row in rows})
    with _v6_budget_path():return v5.execute_after_authorization(approved_manifest_sha,paths)

def main()->None:
    import argparse
    p=argparse.ArgumentParser();p.add_argument("--prepare",action="store_true");p.add_argument("--execute",action="store_true");p.add_argument("--approved-result-manifest-sha");a=p.parse_args();ensure(a.prepare^a.execute,"STOP_EXACTLY_ONE_MODE_REQUIRED")
    if a.prepare:
        m=prepare();print(f"RESULT_SOURCE_IDENTITY_MANIFEST_PATH = {INPUT/MANIFEST}\nRESULT_SOURCE_IDENTITY_MANIFEST_SHA256 = {m['manifest_sha256']}\nPREPARE_STATUS = COMPLETE\nREAL_RESULT_ROWS_PARSED = FALSE")
    else:execute_after_authorization(a.approved_result_manifest_sha)
if __name__=="__main__":main()
