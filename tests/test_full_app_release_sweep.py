from pathlib import Path
import sys
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


def _passing_payload() -> dict:
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
    ]

    passed_gate = {"passed": True, "failure_count": 0, "raw_sql_included": False}
    return {
        "artifacts/full_app_validation/view_results.json": view_rows,
        "artifacts/full_app_validation/rendered_fragments.json": fragment_rows,
        "artifacts/full_app_validation/first_paint_performance_results.json": {
            "passed": True,
            "rows": first_paint_rows,
            "failure_count": 0,
        },
        "artifacts/launch_readiness/action_click_gate_results.json": passed_gate,
        "artifacts/launch_readiness/runtime_artifact_provenance_gate_results.json": passed_gate,
        "artifacts/launch_readiness/export_download_gate_results.json": passed_gate,
        "artifacts/launch_readiness/settings_live_feature_gate_results.json": {
            **passed_gate,
            "settings_failure_count": 0,
            "live_feature_failure_count": 0,
        },
        "artifacts/launch_readiness/performance_budget_gate_results.json": passed_gate,
        "artifacts/launch_readiness/user_stress_gate_results.json": passed_gate,
        "artifacts/launch_readiness/sql_cleanup_gate_results.json": passed_gate,
        "artifacts/launch_readiness/delete_first_cleanup_gate_results.json": passed_gate,
        "artifacts/launch_readiness/rendered_ui_leak_gate_results.json": passed_gate,
        "artifacts/launch_readiness/security_credential_render_gate_results.json": passed_gate,
        "artifacts/launch_readiness/security_credential_evidence_gate_results.json": passed_gate,
        "artifacts/launch_readiness/security_credential_export_gate_results.json": passed_gate,
        "artifacts/launch_readiness/user_display_surface_gate_results.json": passed_gate,
        "artifacts/launch_readiness/cortex_token_efficiency_gate_results.json": {
            **passed_gate,
            "cortex_token_metric_count": 7,
        },
    }


class FullAppReleaseSweepTests(unittest.TestCase):
    def test_passing_payload_covers_all_required_surfaces(self):
        from tools.contracts.full_app_release_sweep import (
            REQUIRED_RELEASE_SURFACES,
            build_full_app_release_sweep,
            evaluate_full_app_release_sweep_gate,
        )

        results, failures = build_full_app_release_sweep(_passing_payload(), current_commit=TEST_COMMIT)
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

        payload = _passing_payload()
        payload["artifacts/full_app_validation/rendered_fragments.json"] = [
            row
            for row in payload["artifacts/full_app_validation/rendered_fragments.json"]
            if row["section"] != "Query Search" or row["workflow"] != "Explicit search"
        ]

        results, _failures = build_full_app_release_sweep(payload, current_commit=TEST_COMMIT)

        self.assertFalse(results["passed"])
        self.assertTrue(any(row["section"] == "Query Search" for row in results["failures"]))

    def test_raw_source_token_in_daily_surface_fails(self):
        from tools.contracts.full_app_release_sweep import build_full_app_release_sweep

        payload = _passing_payload()
        payload["artifacts/full_app_validation/view_results.json"][0]["html_fragment"] += " ACCOUNT_USAGE"

        results, _failures = build_full_app_release_sweep(payload, current_commit=TEST_COMMIT)

        self.assertFalse(results["passed"])
        self.assertGreater(results["raw_source_leak_count"], 0)

    def test_first_paint_over_budget_fails(self):
        from tools.contracts.full_app_release_sweep import build_full_app_release_sweep

        payload = _passing_payload()
        payload["artifacts/full_app_validation/first_paint_performance_results.json"]["rows"][0][
            "cold_first_paint_packet_query_count"
        ] = 2

        results, _failures = build_full_app_release_sweep(payload, current_commit=TEST_COMMIT)

        self.assertFalse(results["passed"])
        self.assertGreater(results["first_paint_failure_count"], 0)

    def test_missing_first_paint_row_fails(self):
        from tools.contracts.full_app_release_sweep import build_full_app_release_sweep

        payload = _passing_payload()
        payload["artifacts/full_app_validation/first_paint_performance_results.json"]["rows"] = [
            row
            for row in payload["artifacts/full_app_validation/first_paint_performance_results.json"]["rows"]
            if row["section"] != "Security Monitoring"
        ]

        results, _failures = build_full_app_release_sweep(payload, current_commit=TEST_COMMIT)

        self.assertFalse(results["passed"])
        self.assertGreater(results["missing_first_paint_row_count"], 0)

    def test_manual_render_source_fails(self):
        from tools.contracts.full_app_release_sweep import build_full_app_release_sweep

        payload = _passing_payload()
        payload["artifacts/full_app_validation/view_results.json"][0]["source"] = "test_constructed_payload"

        results, _failures = build_full_app_release_sweep(payload, current_commit=TEST_COMMIT)

        self.assertFalse(results["passed"])
        self.assertGreater(results["producer_provenance_failure_count"], 0)

    def test_missing_producer_signature_fails(self):
        from tools.contracts.full_app_release_sweep import build_full_app_release_sweep

        payload = _passing_payload()
        payload["artifacts/full_app_validation/view_results.json"][0].pop("producer_signature")

        results, _failures = build_full_app_release_sweep(payload, current_commit=TEST_COMMIT)

        self.assertFalse(results["passed"])
        self.assertGreater(results["producer_provenance_failure_count"], 0)

    def test_commit_mismatch_fails(self):
        from tools.contracts.full_app_release_sweep import build_full_app_release_sweep

        payload = _passing_payload()
        payload["artifacts/full_app_validation/rendered_fragments.json"][0]["commit_sha"] = "old-commit"

        results, _failures = build_full_app_release_sweep(payload, current_commit=TEST_COMMIT)

        self.assertFalse(results["passed"])
        self.assertGreater(results["producer_provenance_failure_count"], 0)


if __name__ == "__main__":
    unittest.main()
