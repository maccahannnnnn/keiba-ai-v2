"""Runs Stage 1 technical-only tests and records no Formal evidence."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.current_corrected_shadow_v2_prospective_protocol_v1 import sha


def main() -> int:
    module = importlib.import_module("tests.test_current_corrected_shadow_v2_prospective_stage1_v1")
    passed = failed = 0
    failures = []
    for name in sorted(value for value in vars(module) if value.startswith("test_")):
        try:
            getattr(module, name)()
            passed += 1
        except Exception as exc:  # report each table/matrix failure
            failed += 1
            failures.append({"test": name, "type": type(exc).__name__, "message": str(exc)})
    report = {
        "status": "PASS" if not failed else "FAIL",
        "role": "TECHNICAL_TEST_ONLY",
        "total": passed + failed,
        "passed": passed,
        "failed": failed,
        "failures": failures,
        "formal_execution_authorized": False,
        "formal_prospective_started": False,
        "freeze_created": 0,
        "result_data_access_count": 0,
    }
    path = ROOT / "reports" / "current_corrected_shadow_v2_prospective_stage1_test_report_v1.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**report, "sha256": sha(path)}, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
