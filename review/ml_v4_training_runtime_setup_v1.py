"""Verify and record the dedicated, pinned V4 training runtime without fitting."""
from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import scipy
import sklearn
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "ml_v4_training_runtime_v1"
PROTOCOL = ROOT / "reports" / "ml_v4_buy_selection_training_protocol_v1"
DATASET = ROOT / "reports" / "ml_v4_buy_selection_dataset_v1"
EXPECTED = {
    "protocol": "97e783a8c63c7a8ff446b14bb7ec6f17001d43128eb215eda994b96be44d1ebd",
    "protocol_manifest": "847e9f94acc4e4d16c4efa4a8be774ba2e2a53fa82b2a0035ef2de5302fb5d2c",
    "dataset": "02d2471f11c1069ebb264946eacdc55fe3ea673c8812b6d17c8fd973af538b53",
}
PINS = ("numpy==2.3.5", "scikit-learn==1.9.0", "scipy==1.18.1", "joblib==1.5.3")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def run() -> Path:
    if OUT.exists():
        raise FileExistsError(f"OUTPUT_EXISTS:{OUT}")
    OUT.mkdir(parents=True)
    actual = {"protocol": sha(PROTOCOL / "training_protocol.md"), "protocol_manifest": sha(PROTOCOL / "protocol_manifest.json"), "dataset": sha(DATASET / "dataset.csv")}
    if actual != EXPECTED:
        raise RuntimeError(f"FROZEN_AUTHORITY_SHA_MISMATCH:{actual}")
    recipe = LogisticRegression(penalty="l2", C=1.0, solver="lbfgs", class_weight=None)
    validation = {
        "status": "PASS",
        "python_version_expected": "3.12.13",
        "python_version_actual": platform.python_version(),
        "python_version_match": platform.python_version() == "3.12.13",
        "numpy_version": np.__version__, "scikit_learn_version": sklearn.__version__, "scipy_version": scipy.__version__, "joblib_version": joblib.__version__,
        "package_versions_match": {"numpy": np.__version__ == "2.3.5", "scikit_learn": sklearn.__version__ == "1.9.0", "scipy": scipy.__version__ == "1.18.1", "joblib": joblib.__version__ == "1.5.3"},
        "standard_scaler_import": "PASS", "logistic_regression_import": "PASS",
        "lbfgs_recipe_constructor_check": "PASS" if recipe.solver == "lbfgs" and recipe.penalty == "l2" and recipe.C == 1.0 and recipe.class_weight is None else "FAIL",
        "model_fit_count": 0, "scaler_fit_count": 0, "may_access_count": 0, "march_or_earlier_access_count": 0,
    }
    if not validation["python_version_match"] or not all(validation["package_versions_match"].values()) or validation["lbfgs_recipe_constructor_check"] != "PASS":
        raise RuntimeError(f"RUNTIME_VERSION_OR_RECIPE_MISMATCH:{validation}")
    (OUT / "requirements_frozen.txt").write_text("\n".join(PINS) + "\n", encoding="utf-8")
    manifest = {
        "runtime_version": "KEIBAAI_ML_V4_TRAINING_RUNTIME_V1", "base_python_path": sys.executable, "training_python_path": sys.executable,
        "python_version": sys.version, "python_implementation": platform.python_implementation(), "platform": platform.platform(),
        "venv_path": str(Path(sys.prefix)), "packages": {"numpy": np.__version__, "scikit_learn": sklearn.__version__, "scipy": scipy.__version__, "joblib": joblib.__version__},
        "v2_historical_runtime_reference": {"python": "3.12.13", "numpy": "2.3.5", "scikit_learn": "1.9.0", "scipy": "1.18.1", "joblib": "1.5.3"},
        "v4_frozen_authority_sha256": actual, "creation_timestamp": datetime.now(timezone.utc).isoformat(),
        "bundled_runtime_modified": "NO", "model_fit_count": 0, "scaler_fit_count": 0, "may_access_count": 0, "march_or_earlier_access_count": 0,
    }
    write("runtime_manifest.json", manifest)
    (OUT / "python_environment.txt").write_text("\n".join([f"sys.executable={sys.executable}", f"sys.version={sys.version}", f"implementation={platform.python_implementation()}", f"platform={platform.platform()}", f"numpy={np.__version__}", f"scikit_learn={sklearn.__version__}", f"scipy={scipy.__version__}", f"joblib={joblib.__version__}", "model_fit_count=0", "scaler_fit_count=0", "may_access_count=0", "march_or_earlier_access_count=0"]) + "\n", encoding="utf-8")
    write("runtime_validation.json", validation)
    write("artifact_hashes.json", {"indexed_artifacts": {p.name: sha(p) for p in OUT.iterdir() if p.is_file() and p.name != "artifact_hashes.json"}, "self_hash_excluded": True})
    return OUT


if __name__ == "__main__":
    print(run())
