"""Execute retry2 protocol tests and record the actual result, never a fixed PASS."""
from __future__ import annotations

import importlib
import json
import py_compile
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUT = ROOT / "reports" / "current_corrected_shadow_v2_prospective_test_report_retry2.json"
MODULES = (
    "tests.test_current_corrected_shadow_v2_prospective_protocol_v1",
    "tests.test_current_corrected_shadow_v2_prospective_retry2_v1",
)
SOURCES = (
    "review/current_corrected_shadow_v2_prospective_protocol_v1.py",
    "review/current_corrected_shadow_v2_prospective_validators_v1.py",
    "review/current_corrected_shadow_v2_prospective_pre_v1.py",
    "review/current_corrected_shadow_v2_prospective_post_v1.py",
    "review/current_corrected_shadow_v2_prospective_cumulative_v1.py",
    "review/current_corrected_shadow_v2_prospective_diagnostics_v1.py",
)


def main() -> dict:
    executed, failed = [], []
    for source in SOURCES:
        try:
            py_compile.compile(str(ROOT / source), doraise=True)
        except Exception as exc:  # captured in evidence; no claimed PASS
            failed.append({"id": "py_compile:" + source, "error": repr(exc)})
    for name in MODULES:
        module = importlib.import_module(name)
        for test_name in sorted(n for n in dir(module) if n.startswith("test_")):
            try:
                getattr(module, test_name)()
                executed.append(name + "." + test_name)
            except Exception as exc:
                failed.append({"id": name + "." + test_name, "error": repr(exc)})
    report = {
        "schema_version": "CURRENT_CORRECTED_SHADOW_V2_PROSPECTIVE_TEST_REPORT_RETRY2",
        "command": "bundled-python review/current_corrected_shadow_v2_prospective_test_runner_retry2.py",
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "total": len(executed) + len(failed), "passed": len(executed), "failed": len(failed),
        "status": "PASS" if not failed else "FAIL", "test_ids": executed, "failures": failed,
        "required_coverage": ["authorization", "PRE", "POST", "cumulative", "diagnostics", "artifact_integrity"],
        "result_data_access_count": 0, "formal_prospective_started": False,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if failed:
        raise RuntimeError("RETRY2_TEST_FAILURE")
    return report


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False))
