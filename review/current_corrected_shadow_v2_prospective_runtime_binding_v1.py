"""Canonical runtime binding inventory and import-closure audit for Formal v1."""
from __future__ import annotations

import ast
from pathlib import Path

from review.current_corrected_shadow_v2_prospective_protocol_v1 import ROOT, Stop


# This is the single shared binding authority.  Stage 2 must extend this tuple,
# never create a per-entrypoint binding list.
FORMAL_RUNTIME_MODULES = (
    ROOT / "docs" / "current_corrected_shadow_v2_prospective_protocol_v1.json",
    ROOT / "review" / "current_corrected_shadow_v2_prospective_runtime_binding_v1.py",
    ROOT / "review" / "current_corrected_shadow_v2_prospective_state_v1.py",
    ROOT / "review" / "current_corrected_shadow_v2_prospective_formal_pre_v1.py",
    ROOT / "review" / "current_corrected_shadow_v2_prospective_post_v1.py",
    ROOT / "review" / "current_corrected_shadow_v2_prospective_cumulative_v1.py",
    ROOT / "review" / "current_corrected_shadow_v2_prospective_cumulative_fold_v1.py",
    ROOT / "review" / "current_corrected_shadow_v2_prospective_governance_v1.py",
    ROOT / "review" / "current_corrected_shadow_v2_prospective_human_artifact_store_v1.py",
    ROOT / "review" / "current_corrected_shadow_v2_prospective_pre_v1.py",
    ROOT / "review" / "current_corrected_shadow_v2_prospective_protocol_v1.py",
    ROOT / "review" / "current_corrected_shadow_v2_prospective_validators_v1.py",
    ROOT / "review" / "target_bulk_prediction_input_adapter_v1.py",
    ROOT / "review" / "target_daily_result_list_schema_v2_validator.py",
    ROOT / "review" / "target_bulk_prediction_input_shadow_v1.py",
    ROOT / "review" / "track_condition_semantic_shadow_v1.py",
    ROOT / "review" / "current_corrected_shadow_v2.py",
    ROOT / "review" / "current_corrected_shadow_v2_runner.py",
    ROOT / "review" / "track_condition_semantic_shadow_prospective_pre.py",
)

# Dynamic imports cannot be extracted by Python's Import AST.  These explicit
# edges are part of the closure authority and are independently tested.
EXPLICIT_IMPORT_EDGES = {
    "review/current_corrected_shadow_v2_prospective_formal_pre_v1.py": {
        "review/current_corrected_shadow_v2_prospective_pre_v1.py",
    },
    "review/current_corrected_shadow_v2_prospective_post_v1.py": {
        "review/current_corrected_shadow_v2_prospective_formal_pre_v1.py",
    },
    "review/current_corrected_shadow_v2_prospective_cumulative_v1.py": {
        "review/current_corrected_shadow_v2_prospective_governance_v1.py",
    },
    "review/current_corrected_shadow_v2_prospective_protocol_v1.py": {
        "review/track_condition_semantic_shadow_prospective_pre.py",
    },
}
PINNED_OUTSIDE_CLOSURE_ALLOWLIST: dict[str, str] = {}


def _relative(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def _module_to_path(module: str) -> Path | None:
    if not module.startswith("review."):
        return None
    path = ROOT / (module.replace(".", "/") + ".py")
    return path if path.is_file() else None


def actual_formal_pre_module_closure() -> set[str]:
    """Compatibility name for the shared PRE/POST/CUMULATE formal closure."""
    queue = [
        "review/current_corrected_shadow_v2_prospective_formal_pre_v1.py",
        "review/current_corrected_shadow_v2_prospective_post_v1.py",
        "review/current_corrected_shadow_v2_prospective_cumulative_v1.py",
    ]
    seen: set[str] = set()
    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        path = ROOT / current
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        dependencies: set[str] = set(EXPLICIT_IMPORT_EDGES.get(current, set()))
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.ImportFrom):
                module = node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    candidate = _module_to_path(alias.name)
                    if candidate:
                        dependencies.add(_relative(candidate))
            if module:
                candidate = _module_to_path(module)
                if candidate:
                    dependencies.add(_relative(candidate))
        for dependency in dependencies:
            if dependency not in seen:
                queue.append(dependency)
    return seen


def validate_import_closure(*, bound_modules: tuple[Path, ...] = FORMAL_RUNTIME_MODULES) -> None:
    bound = {_relative(path) for path in bound_modules}
    missing = actual_formal_pre_module_closure() - bound - set(PINNED_OUTSIDE_CLOSURE_ALLOWLIST)
    if missing:
        raise Stop("STOP_RUNTIME_BINDING_IMPORT_CLOSURE:" + ",".join(sorted(missing)))
