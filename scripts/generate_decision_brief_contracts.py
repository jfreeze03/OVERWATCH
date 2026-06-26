"""Generate Decision Brief contract artifacts from one JSON manifest.

The manifest is the source of truth for app-side section contracts and the
Snowflake source/metric validation snippets. Run with ``--check`` in CI to fail
when generated artifacts drift from ``config/decision_brief_contracts.json``.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "decision_brief_contracts.json"
PY_OUT = ROOT / ".overwatch_final" / "sections" / "section_command_contracts_generated.py"
SQL_DIR = ROOT / "snowflake" / "generated"
SEED_SQL = SQL_DIR / "decision_brief_contract_seed.sql"
METRIC_SQL = SQL_DIR / "decision_brief_metric_validation.sql"
ROUTES_PY = ROOT / ".overwatch_final" / "sections" / "command_brief_routes.py"


def _load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _allowlisted_route_keys() -> set[str]:
    if not ROUTES_PY.exists():
        return set()
    source = ROUTES_PY.read_text(encoding="utf-8")
    return set(re.findall(r'^\s*"([^"]+)":\s*CommandBriefRoute\(', source, flags=re.MULTILINE))


def validate_manifest(manifest: dict) -> list[str]:
    """Return contract errors that should block generated artifact output."""
    errors: list[str] = []
    allowed_routes = _allowlisted_route_keys()
    for section in manifest.get("sections", []):
        section_name = str(section.get("section", "")).strip()
        source_keys: list[str] = []
        source_required: dict[str, bool] = {}
        for source in section.get("sources", []):
            key = str(source.get("source_key", "")).strip()
            if not key:
                errors.append(f"{section_name}: source is missing source_key")
                continue
            if key in source_required:
                errors.append(f"{section_name}: duplicate source_key {key}")
            source_keys.append(key)
            source_required[key] = bool(source.get("required", True))
        declared_sources = set(source_keys)
        for metric in section.get("metrics", []):
            metric_key = str(metric.get("key", "")).strip()
            source_key = str(metric.get("source_key", "")).strip()
            if source_key not in declared_sources:
                errors.append(f"{section_name}.{metric_key}: source_key {source_key or '<empty>'} is not declared")
            is_primary = bool(metric.get("primary", False))
            is_required_metric = str(metric.get("availability_policy", "optional")).lower() == "required"
            explicitly_allowed = bool(metric.get("allow_required_optional_source", False))
            if is_primary and is_required_metric and source_key in source_required and not source_required[source_key] and not explicitly_allowed:
                errors.append(
                    f"{section_name}.{metric_key}: required primary metric uses optional source {source_key}"
                )
        for action in section.get("actions", []):
            route_key = str(action.get("route_key", "")).strip()
            if not route_key:
                errors.append(f"{section_name}: action {action.get('action_key', '<unknown>')} is missing route_key")
            elif route_key not in allowed_routes:
                errors.append(f"{section_name}: action route_key {route_key} is not allowlisted")
    return errors


def _quote(value: object) -> str:
    text = "" if value is None else str(value)
    return "'" + text.replace("'", "''") + "'"


def _py_string(value: object) -> str:
    return repr("" if value is None else str(value))


def _py_tuple(items: list[str], *, indent: str = "            ") -> str:
    if not items:
        return "()"
    lines = ["("]
    for item in items:
        lines.append(f"{indent}{item},")
    lines.append(indent[:-4] + ")")
    return "\n".join(lines)


def _generate_python(manifest: dict) -> str:
    lines: list[str] = [
        '"""Generated Decision Brief contracts. Do not edit by hand."""',
        "",
        "from __future__ import annotations",
        "",
        "from typing import Mapping",
        "",
        "from sections.section_command_contracts import SectionCommandContract, _contract, _metrics, _sources",
        "",
        "# Generated from config/decision_brief_contracts.json by scripts/generate_decision_brief_contracts.py.",
        "SECTION_COMMAND_CONTRACTS: Mapping[str, SectionCommandContract] = {",
    ]
    for section in manifest["sections"]:
        name = section["section"]
        sources = [
            "("
            + ", ".join(
                (
                    _py_string(source["source_key"]),
                    _py_string(source["source_object"]),
                    "True" if source.get("required", True) else "False",
                    _py_string(source.get("confidence", "allocated")),
                )
            )
            + ")"
            for source in section.get("sources", [])
        ]
        metrics = [
            "("
            + ", ".join(
                (
                    _py_string(metric["key"]),
                    _py_string(metric["label"]),
                    "True" if metric.get("primary", False) else "False",
                    _py_string(metric.get("format", "integer")),
                    _py_string(metric.get("unit", "")),
                    _py_string(metric.get("directionality", "higher_is_worse")),
                    _py_string(metric.get("source_key", "")),
                    _py_string(metric.get("availability_policy", "optional")),
                )
            )
            + ")"
            for metric in section.get("metrics", [])
        ]
        actions = [
            "("
            + ", ".join(
                (
                    _py_string(action["label"]),
                    _py_string(action.get("detail", "")),
                    _py_string(action.get("target_section", name)),
                    _py_string(action.get("target_workflow", "")),
                )
            )
            + ")"
            for action in section.get("actions", [])
        ]
        fallback_routes = [_py_string(action.get("route_key", "")) for action in section.get("actions", [])]
        metric_labels = [_py_string(metric["label"]) for metric in section.get("metrics", [])[:8]]
        lines.extend(
            [
                f"    {_py_string(name)}: _contract(",
                f"        {_py_string(name)},",
                f"        source_table={_py_string(section.get('source_table', 'MART_SECTION_COMMAND_BRIEF'))},",
                "        source_configs=_sources(",
                f"            {int(section['target_freshness_minutes'])},",
            ]
        )
        lines.extend(f"            {source}," for source in sources)
        lines.extend(
            [
                "        ),",
                f"        target_freshness_minutes={int(section['target_freshness_minutes'])},",
                f"        metric_contracts=_metrics{_py_tuple(metrics, indent='            ')},",
                f"        metric_labels={_py_tuple(metric_labels, indent='            ')},",
                f"        unavailable_headline={_py_string(section.get('unavailable_headline', 'Decision brief unavailable.'))},",
                f"        unavailable_summary={_py_string(section.get('unavailable_summary', 'The Decision Brief mart has no current packet for this scope.'))},",
                f"        top_signal_label={_py_string(section.get('top_signal_label', 'Top decision'))},",
                f"        top_signal_detail={_py_string(section.get('top_signal_detail', 'Review the top signal and load detail only when evidence is needed.'))},",
                f"        next_actions={_py_tuple(actions, indent='            ')},",
                f"        fallback_route_keys={_py_tuple(fallback_routes, indent='            ')},",
                "    ),",
            ]
        )
    lines.extend(
        [
            "}",
            "",
            "CANONICAL_COMMAND_BRIEF_SECTIONS = tuple(SECTION_COMMAND_CONTRACTS)",
            "",
        ]
    )
    return "\n".join(lines)


def _generate_seed_sql(manifest: dict) -> str:
    values: list[str] = []
    for section in manifest["sections"]:
        for source in section.get("sources", []):
            values.append(
                "    ("
                + ", ".join(
                    (
                        _quote(section["section"]),
                        _quote(source["source_key"]),
                        _quote(source["source_object"]),
                        "TRUE" if source.get("required", True) else "FALSE",
                        str(int(source.get("target_freshness_minutes", section["target_freshness_minutes"]))),
                        _quote(source.get("confidence", "allocated")),
                        "TRUE",
                    )
                )
                + ")"
            )
    return "\n".join(
        [
            "-- Generated from config/decision_brief_contracts.json. Do not edit by hand.",
            "INSERT INTO OVERWATCH_SECTION_COMMAND_SOURCE_CONFIG (",
            "  SECTION_NAME, SOURCE_KEY, SOURCE_OBJECT, REQUIRED,",
            "  TARGET_FRESHNESS_MINUTES, DEFAULT_CONFIDENCE, ENABLED",
            ")",
            "SELECT * FROM VALUES",
            ",\n".join(values),
            "  AS v(SECTION_NAME, SOURCE_KEY, SOURCE_OBJECT, REQUIRED, TARGET_FRESHNESS_MINUTES, DEFAULT_CONFIDENCE, ENABLED)",
            "WHERE NOT EXISTS (",
            "  SELECT 1",
            "  FROM OVERWATCH_SECTION_COMMAND_SOURCE_CONFIG cfg",
            "  WHERE cfg.SECTION_NAME = v.SECTION_NAME",
            "    AND cfg.SOURCE_KEY = v.SOURCE_KEY",
            ");",
            "",
        ]
    )


def _generate_metric_validation_sql(manifest: dict) -> str:
    values: list[str] = []
    for section in manifest["sections"]:
        for metric in section.get("metrics", []):
            values.append(
                "    ("
                + ", ".join(
                    (
                        _quote(section["section"]),
                        _quote(metric["key"]),
                        "TRUE" if metric.get("primary", False) else "FALSE",
                        _quote(metric.get("source_key", "")),
                        _quote(metric.get("availability_policy", "optional")),
                    )
                )
                + ")"
            )
    return "\n".join(
        [
            "-- Generated from config/decision_brief_contracts.json. Do not edit by hand.",
            "WITH expected_metrics AS (",
            "  SELECT * FROM VALUES",
            ",\n".join(values),
            "  AS v(SECTION_NAME, METRIC_KEY, IS_PRIMARY, SOURCE_KEY, AVAILABILITY_POLICY)",
            ")",
            "SELECT 'SECTION_DECISION_CONTRACT_METRICS' AS CHECK_NAME, COUNT(*) AS OBSERVED_VALUE, 'PASS' AS STATUS",
            "FROM expected_metrics",
            "UNION ALL",
            "SELECT",
            "  'SECTION_DECISION_CONTRACT_METRIC_SOURCE_KEYS' AS CHECK_NAME,",
            "  COUNT(*) AS OBSERVED_VALUE,",
            "  IFF(COUNT(*) = 0, 'PASS', 'FAIL') AS STATUS",
            "FROM expected_metrics e",
            "LEFT JOIN OVERWATCH_SECTION_COMMAND_SOURCE_CONFIG cfg",
            "  ON cfg.SECTION_NAME = e.SECTION_NAME",
            " AND cfg.SOURCE_KEY = e.SOURCE_KEY",
            "WHERE COALESCE(e.SOURCE_KEY, '') <> ''",
            "  AND cfg.SOURCE_KEY IS NULL",
            "UNION ALL",
            "SELECT",
            "  'SECTION_COMMAND_SOURCE_CONFIG_UNIQUE_SOURCE_KEYS' AS CHECK_NAME,",
            "  COUNT(*) AS OBSERVED_VALUE,",
            "  IFF(COUNT(*) = 0, 'PASS', 'FAIL') AS STATUS",
            "FROM (",
            "  SELECT SECTION_NAME, SOURCE_KEY",
            "  FROM OVERWATCH_SECTION_COMMAND_SOURCE_CONFIG",
            "  GROUP BY SECTION_NAME, SOURCE_KEY",
            "  HAVING COUNT(*) > 1",
            ");",
            "",
        ]
    )


def _write_or_check(path: Path, content: str, *, check: bool) -> bool:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if existing == content:
        return True
    if check:
        print(f"Generated artifact is out of date: {path.relative_to(ROOT)}")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"Wrote {path.relative_to(ROOT)}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Fail if generated artifacts differ.")
    args = parser.parse_args()
    manifest = _load_manifest()
    errors = validate_manifest(manifest)
    if errors:
        for error in errors:
            print(f"Manifest validation error: {error}")
        return 1
    outputs = {
        PY_OUT: _generate_python(manifest),
        SEED_SQL: _generate_seed_sql(manifest),
        METRIC_SQL: _generate_metric_validation_sql(manifest),
    }
    ok = True
    for path, content in outputs.items():
        ok = _write_or_check(path, content, check=args.check) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
