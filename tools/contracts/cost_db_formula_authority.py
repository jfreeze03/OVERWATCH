"""COST_DB formula authority contract for OVERWATCH launch readiness."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping


FORMULA_AUTHORITY_DIR = "artifacts/formula_authority"
COST_DB_MAPPING_REL = f"{FORMULA_AUTHORITY_DIR}/cost_db_formula_mapping.json"
OVERWATCH_MAPPING_REL = f"{FORMULA_AUTHORITY_DIR}/overwatch_formula_mapping.json"
FORMULA_GAP_REL = f"{FORMULA_AUTHORITY_DIR}/formula_gap_results.json"
REQUIRED_FORMULA_AUTHORITY_ARTIFACTS = {
    COST_DB_MAPPING_REL,
    OVERWATCH_MAPPING_REL,
    FORMULA_GAP_REL,
}


def _ensure_app_path(root: Path) -> None:
    app_root = root / ".overwatch_final"
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def write_cost_db_formula_authority_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root)
    _ensure_app_path(root_path)
    from utils.cost_formula_authority import (
        cost_db_formula_mapping,
        evaluate_formula_gaps,
        overwatch_formula_mapping,
    )

    cost_db_rows = cost_db_formula_mapping()
    overwatch_rows = overwatch_formula_mapping()
    gap_results = evaluate_formula_gaps(cost_db_rows, overwatch_rows)
    artifacts = {
        COST_DB_MAPPING_REL: cost_db_rows,
        OVERWATCH_MAPPING_REL: overwatch_rows,
        FORMULA_GAP_REL: gap_results,
    }
    for rel, payload in artifacts.items():
        _write_json(root_path / rel, payload)
    return artifacts


def evaluate_cost_db_formula_authority(
    cost_db_mapping: Any,
    overwatch_mapping: Any,
    formula_gap_results: Any,
) -> dict[str, Any]:
    cost_db_rows = list(cost_db_mapping or []) if isinstance(cost_db_mapping, list) else []
    overwatch_rows = list(overwatch_mapping or []) if isinstance(overwatch_mapping, list) else []
    gap = dict(_as_mapping(formula_gap_results))
    failures: list[dict[str, Any]] = []
    if not cost_db_rows:
        failures.append({"code": "COST_DB_MAPPING_MISSING", "artifact": COST_DB_MAPPING_REL})
    if not overwatch_rows:
        failures.append({"code": "OVERWATCH_MAPPING_MISSING", "artifact": OVERWATCH_MAPPING_REL})
    if not bool(gap.get("passed")):
        failures.append({"code": "FORMULA_GAP_RESULTS_FAILED", "failure_count": int(gap.get("failure_count") or 0)})

    authority_ids = {str(row.get("formula_id") or "") for row in cost_db_rows if isinstance(row, Mapping)}
    target_ids = {str(row.get("formula_id") or "") for row in overwatch_rows if isinstance(row, Mapping)}
    for required in ("numeric_normalization", "credit_price", "warehouse_bridge", "account_billed_total", "cortex_ai", "workbench_charts"):
        if required not in authority_ids:
            failures.append({"code": "REQUIRED_COST_DB_FORMULA_MISSING", "formula_id": required})
    for required in ("account_billed_total", "warehouse_bridge", "cortex_ai", "workbench_charts"):
        if required not in target_ids:
            failures.append({"code": "REQUIRED_OVERWATCH_FORMULA_MISSING", "formula_id": required})

    for row in cost_db_rows:
        mapping = _as_mapping(row)
        if mapping and mapping.get("status") not in {"matched", "intentionally_different"}:
            failures.append({"code": "COST_DB_ROW_NOT_ACCEPTED", "formula_id": mapping.get("formula_id"), "status": mapping.get("status")})
    for row in overwatch_rows:
        mapping = _as_mapping(row)
        if mapping and not bool(mapping.get("uses_cost_db_authority")):
            failures.append({"code": "OVERWATCH_ROW_NOT_USING_AUTHORITY", "metric_key": mapping.get("overwatch_metric_key")})

    return {
        "source": "cost_db_formula_authority_gate",
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "cost_db_formula_count": len(cost_db_rows),
        "overwatch_formula_count": len(overwatch_rows),
        "required_artifacts": sorted(REQUIRED_FORMULA_AUTHORITY_ARTIFACTS),
        "raw_sql_included": False,
    }


def main() -> None:
    artifacts = write_cost_db_formula_authority_artifacts(Path.cwd())
    results = artifacts[FORMULA_GAP_REL]
    if not bool(_as_mapping(results).get("passed")):
        raise SystemExit(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()


__all__ = [
    "COST_DB_MAPPING_REL",
    "FORMULA_AUTHORITY_DIR",
    "FORMULA_GAP_REL",
    "OVERWATCH_MAPPING_REL",
    "REQUIRED_FORMULA_AUTHORITY_ARTIFACTS",
    "evaluate_cost_db_formula_authority",
    "write_cost_db_formula_authority_artifacts",
]
