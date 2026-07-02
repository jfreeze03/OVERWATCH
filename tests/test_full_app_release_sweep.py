from pathlib import Path
import hashlib
import json
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


PRIMARY_ALIASES = {
    "Executive Landing": "Executive Overview",
    "DBA Control Room": "Morning Cockpit",
    "Alert Center": "Active Alerts",
    "Cost & Contract": "Cost Overview",
    "Workload Operations": "Workload Overview",
    "Security Monitoring": "Security Overview",
}
TEST_COMMIT = "test-commit"


def _producer_fields(section: str, workflow: str, *, source: str = "rendered_app") -> dict:
    return {
        "producer": "full_app_runtime_validation",
        "producer_signature": f"sig::{section}::{workflow}",
        "provenance_origin": "producer",
        "commit_sha": TEST_COMMIT,
        "generated_at": "2026-07-01T00:00:00Z",
        "source": source,
        "runtime_source": "actual_section_render",
        "section": section,
        "workflow": workflow,
        "raw_sql_included": False,
    }


def _command_brief_html(section: str) -> str:
    return (
        f"<section class='ow-decision-workspace-marker'>"
        f"<div class='ow-kit-command-brief'><h1>{section}</h1>"
        "<p>Packet-backed first paint. Evidence loads on request.</p></div></section>"
    )


def _write_payload(root: Path, rel: str, content: str) -> dict:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="")
    return {
        "payload_file": rel,
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "size_bytes": len(content.encode("utf-8")),
    }


def _passing_payload(root: Path) -> dict:
    view_rows = []
    first_paint_rows = []
    for section, workflow in PRIMARY_ALIASES.items():
        view_rows.append(
            {
                **_producer_fields(section, workflow),
                "section": section,
                "workflow": workflow,
                "rendered": True,
                "html_fragment": _command_brief_html(section),
                "old_board_marker_count": 0,
                "diagnostic_card_count": 0,
                "passed": True,
            }
        )
        first_paint_rows.append(
            {
                **_producer_fields(section, workflow),
                "section": section,
                "workflow": workflow,
                "product_boundary": "first_paint_packet",
                "execution_boundary": "decision_packet",
                "cold_first_paint_packet_query_count": 1,
                "warm_first_paint_query_count": 0,
                "non_packet_first_paint_event_count": 0,
                "evidence_query_count": 0,
                "account_usage_count": 0,
                "detail_query_count": 0,
                "cost_workbench_query_count": 0,
                "query_search_query_count": 0,
                "direct_sql_count": 0,
                "session_open_count": 0,
                "elapsed_ms": 100,
                "passed": True,
            }
        )

    fragment_rows = [
        {**_producer_fields("Query Search", "No click"), "rendered": True, "text": "Query Search"},
        {**_producer_fields("Query Search", "Explicit search"), "rendered": True, "text": "Exact query result"},
        {**_producer_fields("Advanced Scope", "Active filters"), "rendered": True, "text": "Advanced Scope"},
        {**_producer_fields("Settings", "Default"), "rendered": True, "text": "Cost estimates use configured credit rates."},
        {
            **_producer_fields("Settings/Admin Setup Health", "Setup Health"),
            "section": "Settings/Admin Setup Health",
            "workflow": "Setup Health",
            "admin_only": True,
            "rendered": True,
            "text": "Setup Health",
        },
        {**_producer_fields("Packet Missing", "Fallback"), "rendered": True, "text": "Summary pending"},
        {**_producer_fields("Packet Closest Fallback", "Fallback"), "rendered": True, "text": "Latest available"},
        {**_producer_fields("Snowflake Unavailable", "Fallback"), "rendered": True, "text": "Snowflake unavailable"},
        {**_producer_fields("Permission Denied", "Fallback"), "rendered": True, "text": "Permission needed"},
        {**_producer_fields("Targeted Evidence", "Route action"), "rendered": True, "text": "Targeted route"},
        {**_producer_fields("Targeted Evidence", "Evidence action"), "rendered": True, "text": "Evidence action"},
        {**_producer_fields("Cost Workbench", "Explicit action"), "rendered": True, "text": "Cost workbench"},
        {**_producer_fields("Alert Center", "Loaded"), "rendered": True, "text": "Alert evidence loaded"},
        {**_producer_fields("Cost & Contract", "Loaded"), "rendered": True, "text": "Cost evidence loaded"},
        {**_producer_fields("Workload Operations", "Loaded"), "rendered": True, "text": "Workload evidence loaded"},
        {**_producer_fields("Security Monitoring", "Loaded"), "rendered": True, "text": "Security evidence loaded"},
        {
            **_producer_fields("Cortex Efficiency", "Explicit action"),
            "id": "cortex_efficiency::explicit_action",
            "rendered": True,
            "text": "Cortex token efficiency loaded",
            "visible_row_count": 1,
            "source_rows_present": True,
        },
        {
            **_producer_fields("Security Credential Evidence", "Explicit action"),
            "id": "security_credential_evidence::explicit_action",
            "rendered": True,
            "text": "Credential expiration evidence loaded",
            "visible_row_count": 1,
            "source_rows_present": True,
        },
    ]
    action_rows = [
        {
            **_producer_fields(section, workflow, source="clicked_action"),
            "id": f"{section.lower().replace(' ', '_')}::{workflow.lower().replace(' ', '_')}",
            "stable_key": f"{section.lower().replace(' ', '_')}_{workflow.lower().replace(' ', '_')}",
            "label": f"{section} {workflow}",
            "clicked": True,
            "action_area": "query_search"
            if section == "Query Search"
            else ("evidence_action" if section not in {"Cortex Efficiency", "Cost Workbench"} else "cost_workbench"),
            "passed": True,
        }
        for section, workflow in (
            ("Alert Center", "Loaded"),
            ("Cost & Contract", "Loaded"),
            ("Workload Operations", "Loaded"),
            ("Security Monitoring", "Loaded"),
            ("Query Search", "Explicit search"),
            ("Targeted Evidence", "Route action"),
            ("Targeted Evidence", "Evidence action"),
            ("Cost Workbench", "Explicit action"),
            ("Cortex Efficiency", "Explicit action"),
            ("Security Credential Evidence", "Explicit action"),
        )
    ]
    cortex_csv = (
        "USER_DISPLAY_NAME,TOTAL_TOKENS,TOTAL_REQUESTS,COST_USD,TOTAL_CREDITS,"
        "TOKENS_PER_REQUEST,TOKENS_PER_DOLLAR,COST_PER_1K_TOKENS_USD,AI_CREDITS_PER_1K_TOKENS\n"
        "Jane Doe,1000,10,2.2,1.0,100,454.55,2.2,1.0\n"
    )
    credential_csv = (
        "User,Credential,Type,Domain,Status,Expires,Days left,Last used,Recommended action\n"
        "Jane Doe,Jane PAT,PAT,USER,ACTIVE,2026-07-05,5,2026-06-29,Rotate credential\n"
    )
    cortex_case_json = json.dumps(
        {
            "section": "Cortex Efficiency",
            "workflow": "Explicit action",
            "scope": "ALFA / ALL / 7",
            "target": "Cortex token efficiency",
            "freshness": "Current",
            "source_family": "cortex_token_efficiency",
            "summary": "Token efficiency case",
            "row_count": 1,
            "visible_row_count": 1,
            "recommended_action": "Review token efficiency.",
            "total_tokens": 1000,
            "tokens_per_dollar": 454.55,
            "cost_per_1k_tokens_usd": 2.2,
        },
        sort_keys=True,
    )
    credential_case_json = json.dumps(
        {
            "section": "Security Credential Evidence",
            "workflow": "Explicit action",
            "scope": "ALFA / ALL / 7",
            "target": "Credential expirations",
            "freshness": "Current",
            "source_family": "credential_expiration",
            "summary": "Credential case",
            "row_count": 1,
            "visible_row_count": 1,
            "recommended_action": "Rotate credential.",
            "expired_count": 0,
            "expiring_30d_count": 1,
            "next_expiration": "2026-07-05",
            "owner_labels": ["Jane Doe"],
        },
        sort_keys=True,
    )
    export_rows = [
        {
            **_producer_fields("Cortex Efficiency", "Explicit action", source="file_backed_export"),
            "id": "cortex_efficiency::export",
            "filename": "cortex_token_efficiency.csv",
            **_write_payload(root, "artifacts/full_app_validation/generated_exports/cortex_token_efficiency.csv", cortex_csv),
            "content_type": "text/csv",
            "parsed_row_count": 1,
            "visible_row_count": 1,
            "row_count": 1,
            "sanitized_default_export": True,
            "admin_only": False,
            "passed": True,
        },
        {
            **_producer_fields("Security Credential Evidence", "Explicit action", source="file_backed_export"),
            "id": "security_credential_evidence::export",
            "filename": "security_credential_evidence.csv",
            **_write_payload(root, "artifacts/full_app_validation/generated_exports/security_credential_evidence.csv", credential_csv),
            "content_type": "text/csv",
            "parsed_row_count": 1,
            "visible_row_count": 1,
            "row_count": 1,
            "sanitized_default_export": True,
            "admin_only": False,
            "passed": True,
        },
    ]
    case_rows = [
        {
            **_producer_fields("Cortex Efficiency", "Explicit action", source="case_payload"),
            "id": "cortex_efficiency::case",
            "filename": "cortex_token_efficiency_case.json",
            **_write_payload(root, "artifacts/full_app_validation/generated_exports/cortex_token_efficiency_case.json", cortex_case_json),
            "content_type": "application/json",
            "parsed_row_count": 1,
            "visible_row_count": 1,
            "row_count": 1,
            "source_family": "cortex_token_efficiency",
            "passed": True,
        },
        {
            **_producer_fields("Security Credential Evidence", "Explicit action", source="case_payload"),
            "id": "security_credential_evidence::case",
            "filename": "security_credential_case.json",
            **_write_payload(root, "artifacts/full_app_validation/generated_exports/security_credential_case.json", credential_case_json),
            "content_type": "application/json",
            "parsed_row_count": 1,
            "visible_row_count": 1,
            "row_count": 1,
            "source_family": "credential_expiration",
            "passed": True,
        },
    ]

    def _feature_gate(section: str) -> dict:
        render = next(row for row in fragment_rows if row["section"] == section)
        action = next(row for row in action_rows if row["section"] == section)
        export = next(row for row in export_rows if row["section"] == section)
        case = next(row for row in case_rows if row["section"] == section)
        return {
            "passed": True,
            "failure_count": 0,
            "rendered_artifact_path": "artifacts/full_app_validation/rendered_fragments.json",
            "rendered_row_id": render["id"],
            "action_artifact_path": "artifacts/full_app_validation/action_click_results.json",
            "action_row_id": action["id"],
            "export_artifact_path": "artifacts/full_app_validation/export_results.json",
            "export_row_id": export["id"],
            "export_row_index": export_rows.index(export),
            "case_payload_artifact_path": "artifacts/full_app_validation/case_payload_results.json",
            "case_payload_row_id": case["id"],
            "case_payload_row_index": case_rows.index(case),
            "expected_section": section,
            "expected_workflow": "Explicit action",
            "source_rows_present": True,
            "visible_row_count": 1,
            "exported_row_count": 1,
            "case_row_count": 1,
            "producer_signature": render["producer_signature"],
            "commit_sha": TEST_COMMIT,
            "raw_sql_included": False,
        }

    passed_gate = {"passed": True, "failure_count": 0, "raw_sql_included": False}
    snowflake_cli_gate = {
        **passed_gate,
        "snowflake_cli_token_auth_used": True,
        "snowflake_cli_token_file_supplied": True,
        "snowflake_cli_token_path_leak_count": 0,
        "snowflake_cli_temp_sql_path_leak_count": 0,
        "temp_file_hygiene_passed": True,
        "temp_sql_file_leftover_count": 0,
    }
    temp_hygiene_gate = {
        **passed_gate,
        "snowflake_cli_temp_file_hygiene_passed": True,
        "temp_sql_file_used_count": 4,
        "temp_sql_file_leftover_count": 0,
        "temp_sql_file_path_stored": False,
    }
    setup_migration_gate = {
        **passed_gate,
        "setup_migration_live_passed": True,
        "object_probe_passed": True,
        "ledger_probe_passed": True,
    }
    return {
        "artifacts/full_app_validation/view_results.json": view_rows,
        "artifacts/full_app_validation/rendered_fragments.json": fragment_rows,
        "artifacts/full_app_validation/first_paint_performance_results.json": {
            "passed": True,
            "rows": first_paint_rows,
            "failure_count": 0,
        },
        "artifacts/full_app_validation/cost_overview_no_autoload_results.json": {
            "passed": True,
            "failure_count": 0,
            "cost_overview_autoload_violation_count": 0,
            "rows": [
                {
                    **_producer_fields("Cost & Contract", "Cost Overview"),
                    "id": "cost_overview_no_autoload::cost_contract::cost_overview",
                    "rendered": True,
                    "first_paint_row_exists": True,
                    "autoload_violation_count": 0,
                    "old_splash_wording_count": 0,
                    "passed": True,
                }
            ],
            "raw_sql_included": False,
        },
        "artifacts/full_app_validation/action_click_results.json": {"passed": True, "rows": action_rows, "failure_count": 0},
        "artifacts/full_app_validation/button_click_results.json": action_rows,
        "artifacts/full_app_validation/export_results.json": export_rows,
        "artifacts/full_app_validation/case_payload_results.json": case_rows,
        "artifacts/launch_readiness/action_click_gate_results.json": passed_gate,
        "artifacts/launch_readiness/runtime_artifact_provenance_gate_results.json": passed_gate,
        "artifacts/launch_readiness/export_download_gate_results.json": passed_gate,
        "artifacts/launch_readiness/settings_live_feature_gate_results.json": {
            **passed_gate,
            "settings_failure_count": 0,
            "live_feature_failure_count": 0,
        },
        "artifacts/launch_readiness/connection_policy_gate_results.json": {
            **passed_gate,
            "connection_policy_passed": True,
            "fallback_render_passed": True,
            "fallback_render_failure_count": 0,
            "unknown_route_fail_closed": True,
        },
        "artifacts/launch_readiness/import_laziness_gate_results.json": {
            **passed_gate,
            "import_laziness_failure_count": 0,
            "runtime_import_graph_failure_count": 0,
        },
        "artifacts/full_app_validation/runtime_import_graph_results.json": {
            **passed_gate,
            "runtime_import_graph_failure_count": 0,
            "rows": [],
        },
        "artifacts/launch_readiness/performance_budget_gate_results.json": {
            **passed_gate,
            "cost_overview_autoload_violation_count": 0,
        },
        "artifacts/launch_readiness/user_stress_gate_results.json": passed_gate,
        "artifacts/launch_readiness/sql_cleanup_gate_results.json": passed_gate,
        "artifacts/launch_readiness/delete_first_cleanup_gate_results.json": passed_gate,
        "artifacts/launch_readiness/rendered_ui_leak_gate_results.json": passed_gate,
        "artifacts/launch_readiness/security_credential_render_gate_results.json": passed_gate,
        "artifacts/launch_readiness/security_credential_evidence_gate_results.json": _feature_gate("Security Credential Evidence"),
        "artifacts/launch_readiness/security_credential_expiration_live_gate_results.json": {
            **passed_gate,
            "live_validation_status": "passed",
        },
        "artifacts/launch_readiness/security_credential_snapshot_gate_results.json": passed_gate,
        "artifacts/launch_readiness/security_credential_export_gate_results.json": passed_gate,
        "artifacts/launch_readiness/user_display_surface_gate_results.json": passed_gate,
        "artifacts/launch_readiness/cortex_token_efficiency_gate_results.json": {
            **_feature_gate("Cortex Efficiency"),
            "cortex_token_metric_count": 7,
        },
        "artifacts/launch_readiness/cortex_token_efficiency_live_gate_results.json": {
            **passed_gate,
            "live_validation_status": "passed",
        },
        "artifacts/launch_readiness/snowflake_cli_live_gate_results.json": snowflake_cli_gate,
        "artifacts/launch_readiness/snowflake_cli_temp_file_hygiene_gate_results.json": temp_hygiene_gate,
        "artifacts/launch_readiness/setup_migration_live_gate_results.json": setup_migration_gate,
    }


class FullAppReleaseSweepTests(unittest.TestCase):
    def test_passing_payload_covers_all_required_surfaces(self):
        from tools.contracts.full_app_release_sweep import (
            REQUIRED_RELEASE_SURFACES,
            build_full_app_release_sweep,
            evaluate_full_app_release_sweep_gate,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results, failures = build_full_app_release_sweep(
                _passing_payload(root),
                current_commit=TEST_COMMIT,
                root=root,
            )
            gate = evaluate_full_app_release_sweep_gate(results)

            self.assertTrue(results["passed"], failures)
            self.assertTrue(gate["passed"], gate)
        self.assertGreaterEqual(results["surface_count"], len(REQUIRED_RELEASE_SURFACES))
        for row in results["rows"]:
            for field in (
                "area",
                "section",
                "workflow",
                "source_artifact",
                "rendered",
                "clicked",
                "exported",
                "passed",
                "failure_reason",
            ):
                self.assertIn(field, row)

    def test_missing_required_surface_fails(self):
        from tools.contracts.full_app_release_sweep import build_full_app_release_sweep

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _passing_payload(root)
            payload["artifacts/full_app_validation/rendered_fragments.json"] = [
                row
                for row in payload["artifacts/full_app_validation/rendered_fragments.json"]
                if row["section"] != "Query Search" or row["workflow"] != "Explicit search"
            ]
            results, _failures = build_full_app_release_sweep(payload, current_commit=TEST_COMMIT, root=root)

        self.assertFalse(results["passed"])
        self.assertTrue(any(row["section"] == "Query Search" for row in results["failures"]))

    def test_missing_import_laziness_gate_fails(self):
        from tools.contracts.full_app_release_sweep import build_full_app_release_sweep

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _passing_payload(root)
            payload.pop("artifacts/launch_readiness/import_laziness_gate_results.json")
            results, _failures = build_full_app_release_sweep(payload, current_commit=TEST_COMMIT, root=root)

        self.assertFalse(results["passed"])
        self.assertGreater(results["import_laziness_failure_count"], 0)

    def test_connection_policy_gate_failure_blocks_release_sweep(self):
        from tools.contracts.full_app_release_sweep import build_full_app_release_sweep

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _passing_payload(root)
            payload["artifacts/launch_readiness/connection_policy_gate_results.json"] = {
                "passed": False,
                "failure_count": 1,
                "fallback_render_failure_count": 1,
                "raw_sql_included": False,
            }
            results, _failures = build_full_app_release_sweep(payload, current_commit=TEST_COMMIT, root=root)

        self.assertFalse(results["passed"])
        self.assertEqual(results["fallback_render_failure_count"], 1)

    def test_cost_overview_autoload_gate_blocks_release_sweep(self):
        from tools.contracts.full_app_release_sweep import build_full_app_release_sweep

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _passing_payload(root)
            payload["artifacts/launch_readiness/performance_budget_gate_results.json"] = {
                "passed": False,
                "failure_count": 1,
                "cost_overview_autoload_violation_count": 1,
                "raw_sql_included": False,
            }
            results, _failures = build_full_app_release_sweep(payload, current_commit=TEST_COMMIT, root=root)

        self.assertFalse(results["passed"])
        self.assertEqual(results["cost_overview_autoload_violation_count"], 1)

    def test_raw_source_token_in_daily_surface_fails(self):
        from tools.contracts.full_app_release_sweep import build_full_app_release_sweep

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _passing_payload(root)
            payload["artifacts/full_app_validation/view_results.json"][0]["html_fragment"] += " ACCOUNT_USAGE"
            results, _failures = build_full_app_release_sweep(payload, current_commit=TEST_COMMIT, root=root)

        self.assertFalse(results["passed"])
        self.assertGreater(results["raw_source_leak_count"], 0)

    def test_first_paint_over_budget_fails(self):
        from tools.contracts.full_app_release_sweep import build_full_app_release_sweep

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _passing_payload(root)
            payload["artifacts/full_app_validation/first_paint_performance_results.json"]["rows"][0][
                "cold_first_paint_packet_query_count"
            ] = 2
            results, _failures = build_full_app_release_sweep(payload, current_commit=TEST_COMMIT, root=root)

        self.assertFalse(results["passed"])
        self.assertGreater(results["first_paint_failure_count"], 0)

    def test_missing_first_paint_row_fails(self):
        from tools.contracts.full_app_release_sweep import build_full_app_release_sweep

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _passing_payload(root)
            payload["artifacts/full_app_validation/first_paint_performance_results.json"]["rows"] = [
                row
                for row in payload["artifacts/full_app_validation/first_paint_performance_results.json"]["rows"]
                if row["section"] != "Security Monitoring"
            ]
            results, _failures = build_full_app_release_sweep(payload, current_commit=TEST_COMMIT, root=root)

        self.assertFalse(results["passed"])
        self.assertGreater(results["missing_first_paint_row_count"], 0)

    def test_manual_render_source_fails(self):
        from tools.contracts.full_app_release_sweep import build_full_app_release_sweep

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _passing_payload(root)
            payload["artifacts/full_app_validation/view_results.json"][0]["source"] = "test_constructed_payload"
            results, _failures = build_full_app_release_sweep(payload, current_commit=TEST_COMMIT, root=root)

        self.assertFalse(results["passed"])
        self.assertGreater(results["producer_provenance_failure_count"], 0)

    def test_missing_producer_signature_fails(self):
        from tools.contracts.full_app_release_sweep import build_full_app_release_sweep

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _passing_payload(root)
            payload["artifacts/full_app_validation/view_results.json"][0].pop("producer_signature")
            results, _failures = build_full_app_release_sweep(payload, current_commit=TEST_COMMIT, root=root)

        self.assertFalse(results["passed"])
        self.assertGreater(results["producer_provenance_failure_count"], 0)

    def test_commit_mismatch_fails(self):
        from tools.contracts.full_app_release_sweep import build_full_app_release_sweep

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _passing_payload(root)
            payload["artifacts/full_app_validation/rendered_fragments.json"][0]["commit_sha"] = "old-commit"
            results, _failures = build_full_app_release_sweep(payload, current_commit=TEST_COMMIT, root=root)

        self.assertFalse(results["passed"])
        self.assertGreater(results["producer_provenance_failure_count"], 0)

    def test_feature_gate_without_runtime_references_fails(self):
        from tools.contracts.full_app_release_sweep import build_full_app_release_sweep

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _passing_payload(root)
            payload["artifacts/launch_readiness/cortex_token_efficiency_gate_results.json"].pop("rendered_artifact_path")
            results, _failures = build_full_app_release_sweep(payload, current_commit=TEST_COMMIT, root=root)

        self.assertFalse(results["passed"])
        self.assertTrue(any(row["section"] == "Cortex Efficiency" for row in results["failures"]))

    def test_linked_gate_missing_export_row_id_fails(self):
        from tools.contracts.full_app_release_sweep import build_full_app_release_sweep

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _passing_payload(root)
            payload["artifacts/launch_readiness/security_credential_evidence_gate_results.json"].pop(
                "export_row_id"
            )
            results, _failures = build_full_app_release_sweep(payload, current_commit=TEST_COMMIT, root=root)

        self.assertFalse(results["passed"])
        self.assertTrue(any(row["section"] == "Security Credential Evidence" for row in results["failures"]))

    def test_linked_gate_wrong_export_row_fails(self):
        from tools.contracts.full_app_release_sweep import build_full_app_release_sweep

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _passing_payload(root)
            payload["artifacts/launch_readiness/security_credential_evidence_gate_results.json"][
                "export_row_id"
            ] = "cortex_efficiency::export"
            results, _failures = build_full_app_release_sweep(payload, current_commit=TEST_COMMIT, root=root)

        self.assertFalse(results["passed"])
        self.assertTrue(any("section mismatch" in row["failure_reason"] for row in results["failures"]))

    def test_loaded_surface_wrong_section_click_cannot_satisfy_action(self):
        from tools.contracts.full_app_release_sweep import build_full_app_release_sweep

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _passing_payload(root)
            for row in payload["artifacts/full_app_validation/action_click_results.json"]["rows"]:
                if row["section"] == "Alert Center" and row["workflow"] == "Loaded":
                    row["section"] = "Security Monitoring"
            for row in payload["artifacts/full_app_validation/button_click_results.json"]:
                if row["section"] == "Alert Center" and row["workflow"] == "Loaded":
                    row["section"] = "Security Monitoring"
            results, _failures = build_full_app_release_sweep(payload, current_commit=TEST_COMMIT, root=root)

        self.assertFalse(results["passed"])
        self.assertTrue(any(row["section"] == "Alert Center" and "action" in row["failure_reason"] for row in results["failures"]))

    def test_cortex_export_metadata_count_mismatch_fails_release_sweep(self):
        from tools.contracts.full_app_release_sweep import build_full_app_release_sweep

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _passing_payload(root)
            export = next(
                row
                for row in payload["artifacts/full_app_validation/export_results.json"]
                if row["section"] == "Cortex Efficiency"
            )
            export["parsed_row_count"] = 2
            export["visible_row_count"] = 2
            payload["artifacts/launch_readiness/cortex_token_efficiency_gate_results.json"]["visible_row_count"] = 2
            payload["artifacts/launch_readiness/cortex_token_efficiency_gate_results.json"]["exported_row_count"] = 2
            results, _failures = build_full_app_release_sweep(payload, current_commit=TEST_COMMIT, root=root)

        self.assertFalse(results["passed"])
        self.assertTrue(any("parsed row count differs from metadata" in row["failure_reason"] for row in results["failures"]))

    def test_default_credential_export_with_user_id_fails(self):
        from tools.contracts.full_app_release_sweep import build_full_app_release_sweep

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _passing_payload(root)
            export = next(
                row
                for row in payload["artifacts/full_app_validation/export_results.json"]
                if row["section"] == "Security Credential Evidence"
            )
            leaked_csv = "User,USER_ID,Credential,Type,Status,Recommended action\nJane Doe,123,Jane PAT,PAT,ACTIVE,Rotate\n"
            export.update(_write_payload(root, export["payload_file"], leaked_csv))
            export["parsed_row_count"] = 1
            export["visible_row_count"] = 1
            results, _failures = build_full_app_release_sweep(payload, current_commit=TEST_COMMIT, root=root)

        self.assertFalse(results["passed"])
        self.assertTrue(any("USER_ID" in row["failure_reason"] for row in results["failures"]))

    def test_credential_case_missing_source_family_fails(self):
        from tools.contracts.full_app_release_sweep import build_full_app_release_sweep

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _passing_payload(root)
            case = next(
                row
                for row in payload["artifacts/full_app_validation/case_payload_results.json"]
                if row["section"] == "Security Credential Evidence"
            )
            payload_json = json.loads((root / case["payload_file"]).read_text(encoding="utf-8"))
            payload_json.pop("source_family")
            payload_json.pop("source", None)
            case.update(_write_payload(root, case["payload_file"], json.dumps(payload_json, sort_keys=True)))
            results, _failures = build_full_app_release_sweep(payload, current_commit=TEST_COMMIT, root=root)

        self.assertFalse(results["passed"])
        self.assertTrue(any("source_family" in row["failure_reason"] for row in results["failures"]))

    def test_missing_export_payload_file_fails(self):
        from tools.contracts.full_app_release_sweep import build_full_app_release_sweep

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _passing_payload(root)
            payload["artifacts/full_app_validation/export_results.json"][0]["payload_file"] = (
                "artifacts/full_app_validation/generated_exports/missing.csv"
            )
            results, _failures = build_full_app_release_sweep(payload, current_commit=TEST_COMMIT, root=root)

        self.assertFalse(results["passed"])
        self.assertTrue(any("payload file missing" in row["failure_reason"] for row in results["failures"]))


if __name__ == "__main__":
    unittest.main()
