import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from tools.contracts.formula_end_to_end_validation import REQUIRED_PACKET_FIELDS
from tools.contracts.snowflake_cli_live_validation import (
    CLI_CAPABILITY_REL,
    CLI_CONNECTION_REL,
    CLI_FORMULA_VALUE_REL,
    CLI_FORMULA_VALUE_GATE_REL,
    CLI_LAUNCH_GATE_REL,
    CLI_MANIFEST_RECONCILIATION_REL,
    CLI_PACKET_VALUE_REL,
    CLI_COST_RECONCILIATION_REL,
    CLI_QUERY_BUDGET_REL,
    CLI_SETUP_MIGRATION_GATE_REL,
    CLI_SETUP_MIGRATION_REL,
    CLI_SETUP_REL,
    CLI_TEMP_FILE_HYGIENE_GATE_REL,
    CLI_TEMP_FILE_HYGIENE_REL,
    REQUIRED_QUERY_BUDGET_BOUNDARIES,
    SnowflakeCliValidationOptions,
    TEMP_SQL_PREFIX,
    evaluate_snowflake_cli_live_gate,
    evaluate_temp_file_hygiene_gate,
    run_snowflake_cli_live_validation,
    sanitize_text,
    write_snowflake_cli_live_validation_artifacts,
    _rendered_formula_static_contract_only,
)
from tools.contracts.packet_availability_live_validation import (
    PACKET_AVAILABILITY_GATE_REL,
    SNOWFLAKE_CLI_PACKET_AVAILABILITY_REL,
)


NUMERIC_DEFAULTS = {
    "ACCOUNT_BILLED_CREDITS": 100.0,
    "ACCOUNT_BILLED_COST_USD": 368.0,
    "ACCOUNT_USED_CREDITS": 98.0,
    "COMPUTE_CREDITS": 80.0,
    "CLOUD_SERVICES_CREDITS": 10.0,
    "CLOUD_SERVICES_ADJUSTMENT": -2.0,
    "ACCOUNT_CLOUD_SERVICES_ADJUSTMENT": -2.0,
    "WAREHOUSE_CREDITS": 90.0,
    "WAREHOUSE_COST_ESTIMATE_USD": 331.2,
    "WAREHOUSE_COST_USD": 331.2,
    "SERVICE_OTHER_CREDITS": 10.0,
    "SERVICE_OTHER_COST_USD": 36.8,
    "BILLING_BRIDGE_DELTA_CREDITS": 10.0,
    "BILLING_BRIDGE_DELTA_USD": 36.8,
    "CORTEX_AI_CREDITS": 3.0,
    "CORTEX_AI_COST_USD": 6.6,
    "SPEND_MOVEMENT_PCT": 2.5,
    "FORECAST_RUN_RATE_USD": 1200.0,
}


def _packet_values() -> dict[str, object]:
    values: dict[str, object] = {}
    for field in REQUIRED_PACKET_FIELDS:
        if field in NUMERIC_DEFAULTS:
            values[field] = NUMERIC_DEFAULTS[field]
        elif field.endswith("_STATUS"):
            values[field] = "matched"
        elif field.endswith("_COMPLETE"):
            values[field] = True
        elif "WINDOW" in field:
            values[field] = "2026-06-21"
        elif "FRESHNESS" in field or field.endswith("_TS"):
            values[field] = "2026-06-28T00:00:00Z"
        elif field == "BILLING_LATENCY_NOTE":
            values[field] = "completed billing window"
        else:
            values[field] = "available"
    values["BILLING_BRIDGE_STATUS"] = "warehouse_lower_than_billed"
    return values


def _packet_stdout(*, mismatch: bool = False) -> str:
    rows = []
    for section in (
        "Executive Landing",
        "Cost & Contract",
        "Workload Operations",
        "DBA Control Room",
        "Alert Center",
        "Security Monitoring",
    ):
        packet = _packet_values()
        flat = dict(packet)
        if mismatch and section == "Cost & Contract":
            flat["CORTEX_AI_COST_USD"] = 999.0
        rows.append(
            {
                "ROW_JSON": {
                    "section_name": section,
                    "packet_present": True,
                    "flat_present": True,
                    "packet": packet,
                    "flat": flat,
                }
            }
        )
    return json.dumps(rows)


def _formula_stdout() -> str:
    expected = dict(_packet_values())
    expected.update(
        {
            "SOURCE_ROWS_PRESENT": True,
            "ACCOUNT_SOURCE_ROWS_PRESENT": True,
            "WAREHOUSE_SOURCE_ROWS_PRESENT": True,
            "CORTEX_SOURCE_ROWS_PRESENT": True,
        }
    )
    return json.dumps([{"ROW_JSON": expected}])


def _query_budget_stdout() -> str:
    rows = []
    for section, workflow, boundary in REQUIRED_QUERY_BUDGET_BOUNDARIES:
        query_count = 1 if boundary == "first_paint_packet" else 0
        rows.append(
            {
                "ROW_JSON": {
                    "section": section,
                    "workflow": workflow,
                    "boundary": boundary,
                    "query_count": query_count,
                    "bytes_scanned": 0,
                    "rows_produced": 0,
                    "max_elapsed_ms": 0,
                    "warehouse": "COMPUTE_WH",
                    "query_tag_prefix": "OVERWATCH_VALIDATION",
                }
            }
        )
    return json.dumps(rows)


def _availability_stdout() -> str:
    rows = []
    for section in (
        "Executive Landing",
        "Cost & Contract",
        "Workload Operations",
        "DBA Control Room",
        "Alert Center",
        "Security Monitoring",
    ):
        rows.append(
            {
                "ROW_JSON": {
                    "section_name": section,
                    "company": "ALL",
                    "environment": "ALL",
                    "window_days": 7,
                    "active_current_count": 1,
                    "flat_current_count": 1,
                    "last_good_count": 1,
                    "latest_snapshot_ts": "2026-06-28T17:43:00Z",
                    "latest_load_ts": "2026-06-28T17:44:00Z",
                }
            }
        )
    return json.dumps(rows)


def _root_with_validation_sql() -> tempfile.TemporaryDirectory[str]:
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    (root / "snowflake").mkdir(parents=True)
    (root / "snowflake" / "OVERWATCH_MART_SETUP.sql").write_text(
        """
CREATE TABLE IF NOT EXISTS OVERWATCH_SCHEMA_MIGRATION (MIGRATION_VERSION VARCHAR);
MERGE INTO OVERWATCH_SCHEMA_MIGRATION tgt USING (
  SELECT '2026.06.13-executive-observability-mart' AS MIGRATION_VERSION
) src ON tgt.MIGRATION_VERSION = src.MIGRATION_VERSION;
MERGE INTO OVERWATCH_SCHEMA_MIGRATION tgt USING (
  SELECT '2026.06.17-enterprise-operating-model' AS MIGRATION_VERSION
) src ON tgt.MIGRATION_VERSION = src.MIGRATION_VERSION;
""",
        encoding="utf-8",
    )
    (root / "snowflake" / "OVERWATCH_MART_VALIDATION.sql").write_text("-- validation placeholder\n", encoding="utf-8")
    rendered = {
        "source": "rendered_formula_results",
        "value_checks": [
            {"packet_field": field, "rendered_value": _packet_values().get(field)}
            for field in REQUIRED_PACKET_FIELDS
        ],
    }
    rendered_path = root / "artifacts" / "full_app_validation" / "rendered_formula_results.json"
    rendered_path.parent.mkdir(parents=True, exist_ok=True)
    rendered_path.write_text(json.dumps(rendered), encoding="utf-8")
    return temp


def _runner(
    *,
    packet_mismatch: bool = False,
    connection_failure: bool = False,
    secret: str = "",
    json_help: bool = True,
    table_packet_output: bool = False,
    null_packet_field: str = "",
):
    def fake_runner(args, capture_output=True, text=True, timeout=None, check=False):
        joined = " ".join(str(arg) for arg in args)
        if "-f" in args:
            try:
                file_arg = str(args[args.index("-f") + 1])
                joined += " " + Path(file_arg).read_text(encoding="utf-8")
            except (OSError, ValueError, IndexError):
                pass
        if "--version" in args:
            return subprocess.CompletedProcess(args, 0, "Snowflake CLI version: 3.21.0\n", "")
        if "sql" in args and "--help" in args:
            help_text = "Usage: snow sql [OPTIONS]\n"
            if json_help:
                help_text += "--format [TABLE|JSON|JSON_EXT|CSV] Specifies output format\n"
            return subprocess.CompletedProcess(args, 0, help_text, "")
        if "connection" in args and "test" in args:
            if connection_failure:
                return subprocess.CompletedProcess(
                    args,
                    1,
                    "",
                    f"password={secret} failed while running SELECT * FROM hidden_table",
                )
            return subprocess.CompletedProcess(args, 0, "Connection test passed\n", "")
        if "INFORMATION_SCHEMA.PROCEDURES" in joined:
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    [
                        {
                            "ROW_JSON": {
                                "procedure_name": "SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FAST",
                                "signature_count": 1,
                                "supports_zero_arg_signature": 1,
                            }
                        }
                    ]
                ),
                "",
            )
        if "QUERY_HISTORY" in joined:
            return subprocess.CompletedProcess(args, 0, _query_budget_stdout(), "")
        if "INFORMATION_SCHEMA.TABLES" in joined and "OVERWATCH_SCHEMA_MIGRATION" in joined:
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    [
                        {
                            "ROW_JSON": {
                                "migration_table_exists": True,
                                "required_object_count": 3,
                                "present_required_object_count": 3,
                                "missing_required_object_count": 0,
                            }
                        }
                    ]
                ),
                "",
            )
        if "FROM OVERWATCH_SCHEMA_MIGRATION" in joined or ".OVERWATCH_SCHEMA_MIGRATION" in joined:
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    [
                        {
                            "ROW_JSON": {
                                "expected_migration_count": 2,
                                "present_migration_count": 2,
                                "missing_migration_count": 0,
                                "latest_migration_version": "2026.06.17-enterprise-operating-model",
                                "repo_source_file_count": 2,
                            }
                        }
                    ]
                ),
                "",
            )
        if "PACKET_AVAILABILITY_PROBE" in joined:
            return subprocess.CompletedProcess(args, 0, _availability_stdout(), "")
        if "MART_SECTION_COMMAND_BRIEF" in joined:
            if table_packet_output:
                return subprocess.CompletedProcess(args, 0, "+---+\n| ROW_JSON |\n+---+\n", "")
            if null_packet_field:
                rows = json.loads(_packet_stdout(mismatch=packet_mismatch))
                rows[1]["ROW_JSON"]["packet"][null_packet_field] = None
                return subprocess.CompletedProcess(args, 0, json.dumps(rows), "")
            return subprocess.CompletedProcess(args, 0, _packet_stdout(mismatch=packet_mismatch), "")
        if "FACT_COST_DAILY" in joined and "FACT_WAREHOUSE_HOURLY" in joined:
            return subprocess.CompletedProcess(args, 0, _formula_stdout(), "")
        if "-f" in args:
            return subprocess.CompletedProcess(args, 0, "validation passed\n", "")
        return subprocess.CompletedProcess(args, 0, "[]", "")

    return fake_runner


class SnowflakeCliLiveValidationTests(unittest.TestCase):
    def test_rendered_formula_static_detector_ignores_flat_fixture_context(self):
        runtime_backed = {
            "source": "rendered_formula_results",
            "value_checks": [
                {
                    "packet_field": "ACCOUNT_BILLED_COST_USD",
                    "flat_value_source": "artifacts/formula_authority/flat_packet_formula_results.json:fixture_expected_value",
                    "rendered_value_source": "artifacts/full_app_validation/rendered_fragments.json:producer_runtime_render",
                }
            ],
        }
        static_rendered = {
            "source": "rendered_formula_results",
            "value_checks": [
                {
                    "packet_field": "ACCOUNT_BILLED_COST_USD",
                    "rendered_value_source": "artifacts/full_app_validation/rendered_formula_results.json:fixture_expected_value",
                }
            ],
        }

        self.assertFalse(_rendered_formula_static_contract_only(runtime_backed))
        self.assertTrue(_rendered_formula_static_contract_only(static_rendered))

    def test_internal_fixture_without_connection_writes_profile_aware_skipped_artifacts(self):
        with _root_with_validation_sql() as temp:
            root = Path(temp)
            artifacts = write_snowflake_cli_live_validation_artifacts(
                root,
                options=SnowflakeCliValidationOptions(profile="internal_fixture"),
                runner=_runner(),
            )

            self.assertTrue(artifacts[CLI_LAUNCH_GATE_REL]["passed"], artifacts[CLI_LAUNCH_GATE_REL])
            self.assertTrue(artifacts[CLI_LAUNCH_GATE_REL]["snowflake_cli_gate_passed"])
            self.assertTrue(artifacts[CLI_LAUNCH_GATE_REL]["snowflake_cli_live_skipped"])
            self.assertFalse(artifacts[CLI_LAUNCH_GATE_REL]["snowflake_cli_live_executed"])
            self.assertFalse(artifacts[CLI_LAUNCH_GATE_REL]["snowflake_cli_live_passed"])
            self.assertTrue((root / CLI_CONNECTION_REL).exists())
            self.assertTrue((root / CLI_SETUP_MIGRATION_REL).exists())
            self.assertTrue((root / CLI_SETUP_MIGRATION_GATE_REL).exists())
            self.assertTrue((root / CLI_QUERY_BUDGET_REL).exists())
            self.assertTrue((root / CLI_MANIFEST_RECONCILIATION_REL).exists())

    def test_internal_live_without_connection_fails_without_waiver_and_passes_with_valid_waiver(self):
        with _root_with_validation_sql() as temp:
            artifacts = run_snowflake_cli_live_validation(
                temp,
                options=SnowflakeCliValidationOptions(profile="internal_live"),
                runner=_runner(),
            )

            failed_gate = evaluate_snowflake_cli_live_gate(artifacts, "internal_live", [])
            self.assertFalse(failed_gate["passed"], failed_gate)
            self.assertIn("SNOWFLAKE_CLI_LIVE_PROOF_MISSING", {row["code"] for row in failed_gate["failures"]})

            waived_gate = evaluate_snowflake_cli_live_gate(
                artifacts,
                "internal_live",
                [
                    {
                        "gate": "snowflake_cli_live_validation",
                        "owner": "release-owner",
                        "reason": "temporary self-hosted runner migration",
                        "expiration_or_review_note": "review by 2026-07-15",
                        "approving_surface": "release review",
                        "valid": True,
                    }
                ],
            )
            self.assertTrue(waived_gate["passed"], waived_gate)
            self.assertTrue(waived_gate["waived"], waived_gate)

    def test_connection_failure_sanitizes_secret_and_sql_body(self):
        secret = "super-secret-token-value"
        with _root_with_validation_sql() as temp, patch.dict(os.environ, {"SNOWFLAKE_TOKEN": secret}, clear=False):
            artifacts = write_snowflake_cli_live_validation_artifacts(
                temp,
                options=SnowflakeCliValidationOptions(connection="dev", profile="internal_fixture"),
                runner=_runner(connection_failure=True, secret=secret),
            )
            serialized = json.dumps(artifacts)

        self.assertNotIn(secret, serialized)
        self.assertNotIn("hidden_table", serialized)
        self.assertNotIn("SELECT *", serialized)
        self.assertFalse(artifacts[CLI_CONNECTION_REL]["passed"])

    def test_authenticator_token_file_flags_are_used_but_not_stored(self):
        seen_args: list[list[str]] = []
        base_runner = _runner()

        def recording_runner(args, capture_output=True, text=True, timeout=None, check=False):
            seen_args.append([str(arg) for arg in args])
            return base_runner(args, capture_output=capture_output, text=text, timeout=timeout, check=check)

        token_path = r"C:\secrets\TOK_CJ-token-secret.txt"
        with _root_with_validation_sql() as temp:
            artifacts = write_snowflake_cli_live_validation_artifacts(
                temp,
                options=SnowflakeCliValidationOptions(
                    connection="dev",
                    profile="internal_live",
                    authenticator="PROGRAMMATIC_ACCESS_TOKEN",
                    token_file_path=token_path,
                    skip_refresh=True,
                ),
                runner=recording_runner,
            )

        serialized = json.dumps(artifacts)
        self.assertNotIn(token_path, serialized)
        self.assertIn('"token_file_supplied": true', serialized)
        self.assertTrue(
            any(
                "connection" in args
                and "test" in args
                and "--authenticator" in args
                and "--token-file-path" in args
                for args in seen_args
            ),
            seen_args,
        )
        self.assertTrue(
            any(
                len(args) >= 2
                and args[1] == "sql"
                and "-f" in args
                and "--authenticator" in args
                and "--token-file-path" in args
                for args in seen_args
            ),
            seen_args,
        )

    def test_temp_sql_file_hygiene_is_proven_without_paths_or_sql_body(self):
        seen_files: list[str] = []
        base_runner = _runner()

        def recording_runner(args, capture_output=True, text=True, timeout=None, check=False):
            if "-f" in args:
                file_arg = str(args[args.index("-f") + 1])
                if TEMP_SQL_PREFIX in Path(file_arg).name:
                    seen_files.append(file_arg)
            return base_runner(args, capture_output=capture_output, text=text, timeout=timeout, check=check)

        with _root_with_validation_sql() as temp:
            artifacts = write_snowflake_cli_live_validation_artifacts(
                temp,
                options=SnowflakeCliValidationOptions(
                    connection="dev",
                    profile="internal_live",
                    skip_refresh=True,
                    query_history_enabled=True,
                ),
                runner=recording_runner,
            )

        serialized = json.dumps(artifacts)
        self.assertTrue(seen_files)
        self.assertTrue(all(not Path(path).exists() for path in seen_files))
        self.assertTrue(artifacts[CLI_TEMP_FILE_HYGIENE_REL]["passed"], artifacts[CLI_TEMP_FILE_HYGIENE_REL])
        self.assertTrue(artifacts[CLI_TEMP_FILE_HYGIENE_GATE_REL]["passed"], artifacts[CLI_TEMP_FILE_HYGIENE_GATE_REL])
        self.assertGreater(artifacts[CLI_TEMP_FILE_HYGIENE_REL]["temp_sql_file_used_count"], 0)
        self.assertEqual(artifacts[CLI_TEMP_FILE_HYGIENE_REL]["temp_sql_file_leftover_count"], 0)
        self.assertNotIn("MART_SECTION_COMMAND_BRIEF", serialized)
        for path in seen_files:
            self.assertNotIn(path, serialized)

    def test_temp_sql_leftover_fails_hygiene_gate_without_storing_full_path(self):
        leftover = Path(tempfile.gettempdir()) / f"{TEMP_SQL_PREFIX}unit_leftover.sql"
        leftover.write_text("select 1", encoding="utf-8")
        try:
            payload = {
                "source": "snowflake_cli_temp_file_hygiene_results",
                "passed": True,
                "failure_count": 0,
                "rows": [],
                "temp_sql_file_used_count": 1,
                "temp_sql_file_deleted_count": 1,
                "temp_sql_file_leftover_count": 1,
                "raw_sql_included": False,
            }
            gate = evaluate_temp_file_hygiene_gate(payload)
        finally:
            leftover.unlink(missing_ok=True)

        self.assertFalse(gate["passed"], gate)
        serialized = json.dumps(gate)
        self.assertIn("SNOWFLAKE_CLI_TEMP_SQL_FILE_LEFTOVER", serialized)
        self.assertNotIn(str(leftover), serialized)

    def test_cli_help_without_json_option_fails_capability_check(self):
        with _root_with_validation_sql() as temp:
            artifacts = write_snowflake_cli_live_validation_artifacts(
                temp,
                options=SnowflakeCliValidationOptions(connection="dev", profile="internal_fixture"),
                runner=_runner(json_help=False),
            )

        self.assertFalse(artifacts[CLI_CAPABILITY_REL]["passed"], artifacts[CLI_CAPABILITY_REL])
        self.assertIn("SNOWFLAKE_CLI_JSON_OUTPUT_UNAVAILABLE", {row["code"] for row in artifacts[CLI_CAPABILITY_REL]["failures"]})

    def test_table_stdout_does_not_silently_pass_json_contract(self):
        with _root_with_validation_sql() as temp:
            artifacts = write_snowflake_cli_live_validation_artifacts(
                temp,
                options=SnowflakeCliValidationOptions(connection="dev", profile="internal_fixture"),
                runner=_runner(table_packet_output=True),
            )

        self.assertFalse(artifacts[CLI_PACKET_VALUE_REL]["passed"], artifacts[CLI_PACKET_VALUE_REL])
        self.assertIn("SNOWFLAKE_CLI_PACKET_ROWS_MISSING", {row["code"] for row in artifacts[CLI_PACKET_VALUE_REL]["failures"]})

    def test_packet_flat_mismatch_fails_packet_and_launch_gate(self):
        with _root_with_validation_sql() as temp:
            artifacts = write_snowflake_cli_live_validation_artifacts(
                temp,
                options=SnowflakeCliValidationOptions(connection="dev", profile="internal_fixture"),
                runner=_runner(packet_mismatch=True),
            )

        self.assertFalse(artifacts[CLI_PACKET_VALUE_REL]["passed"], artifacts[CLI_PACKET_VALUE_REL])
        self.assertFalse(artifacts[CLI_LAUNCH_GATE_REL]["passed"], artifacts[CLI_LAUNCH_GATE_REL])
        self.assertIn("SNOWFLAKE_CLI_ARTIFACT_FAILED", {row["code"] for row in artifacts[CLI_LAUNCH_GATE_REL]["failures"]})

    def test_failed_live_value_check_still_reports_live_executed(self):
        with _root_with_validation_sql() as temp:
            artifacts = write_snowflake_cli_live_validation_artifacts(
                temp,
                options=SnowflakeCliValidationOptions(
                    connection="dev",
                    profile="internal_live",
                    skip_refresh=True,
                    query_history_enabled=True,
                ),
                runner=_runner(packet_mismatch=True),
            )

        self.assertFalse(artifacts[CLI_LAUNCH_GATE_REL]["passed"], artifacts[CLI_LAUNCH_GATE_REL])
        self.assertTrue(artifacts[CLI_LAUNCH_GATE_REL]["snowflake_cli_live_executed"], artifacts[CLI_LAUNCH_GATE_REL])
        self.assertFalse(artifacts[CLI_LAUNCH_GATE_REL]["snowflake_cli_live_passed"], artifacts[CLI_LAUNCH_GATE_REL])

    def test_successful_live_run_reconciles_packet_formula_and_query_budget(self):
        with _root_with_validation_sql() as temp:
            artifacts = write_snowflake_cli_live_validation_artifacts(
                temp,
                options=SnowflakeCliValidationOptions(
                    connection="dev",
                    profile="internal_live",
                    skip_refresh=True,
                    query_history_enabled=True,
                ),
                runner=_runner(),
            )

        self.assertTrue(artifacts[CLI_SETUP_REL]["passed"], artifacts[CLI_SETUP_REL])
        self.assertTrue(artifacts[CLI_SETUP_MIGRATION_REL]["passed"], artifacts[CLI_SETUP_MIGRATION_REL])
        self.assertTrue(artifacts[CLI_SETUP_MIGRATION_GATE_REL]["passed"], artifacts[CLI_SETUP_MIGRATION_GATE_REL])
        self.assertTrue(artifacts[SNOWFLAKE_CLI_PACKET_AVAILABILITY_REL]["passed"], artifacts[SNOWFLAKE_CLI_PACKET_AVAILABILITY_REL])
        self.assertTrue(artifacts[CLI_PACKET_VALUE_REL]["passed"], artifacts[CLI_PACKET_VALUE_REL])
        self.assertTrue(artifacts[CLI_FORMULA_VALUE_REL]["passed"], artifacts[CLI_FORMULA_VALUE_REL])
        self.assertTrue(artifacts[CLI_COST_RECONCILIATION_REL]["passed"], artifacts[CLI_COST_RECONCILIATION_REL])
        self.assertTrue(artifacts[CLI_QUERY_BUDGET_REL]["passed"], artifacts[CLI_QUERY_BUDGET_REL])
        self.assertTrue(artifacts[CLI_FORMULA_VALUE_GATE_REL]["passed"], artifacts[CLI_FORMULA_VALUE_GATE_REL])
        self.assertEqual(
            set(REQUIRED_PACKET_FIELDS),
            {row["formula_field"] for row in artifacts[CLI_FORMULA_VALUE_REL]["rows"]},
        )
        formula_by_field = {row["formula_field"]: row for row in artifacts[CLI_FORMULA_VALUE_REL]["rows"]}
        self.assertEqual(formula_by_field["CORTEX_AI_COST_USD"]["live_expected_value"], 6.6)
        self.assertEqual(formula_by_field["CORTEX_AI_COST_USD"]["selected_credit_price"], 2.2)
        self.assertEqual(formula_by_field["ACCOUNT_BILLED_COST_USD"]["selected_credit_price"], 3.68)
        self.assertTrue(artifacts[CLI_MANIFEST_RECONCILIATION_REL]["passed"], artifacts[CLI_MANIFEST_RECONCILIATION_REL])
        self.assertTrue(artifacts[CLI_LAUNCH_GATE_REL]["passed"], artifacts[CLI_LAUNCH_GATE_REL])
        self.assertTrue(artifacts[CLI_LAUNCH_GATE_REL]["snowflake_cli_live_executed"], artifacts[CLI_LAUNCH_GATE_REL])
        self.assertTrue(artifacts[CLI_LAUNCH_GATE_REL]["snowflake_cli_live_passed"], artifacts[CLI_LAUNCH_GATE_REL])
        self.assertFalse(artifacts[CLI_LAUNCH_GATE_REL]["snowflake_cli_live_skipped"], artifacts[CLI_LAUNCH_GATE_REL])
        self.assertTrue(artifacts[PACKET_AVAILABILITY_GATE_REL]["passed"], artifacts[PACKET_AVAILABILITY_GATE_REL])
        self.assertTrue(artifacts[CLI_LAUNCH_GATE_REL]["packet_availability_passed"], artifacts[CLI_LAUNCH_GATE_REL])
        self.assertTrue(artifacts[CLI_LAUNCH_GATE_REL]["setup_migration_live_passed"], artifacts[CLI_LAUNCH_GATE_REL])
        self.assertTrue(artifacts[CLI_LAUNCH_GATE_REL]["cost_reconciliation_passed"], artifacts[CLI_LAUNCH_GATE_REL])
        self.assertFalse(json.dumps(artifacts).count("SELECT *"))

    def test_formula_sql_uses_cloud_services_adjustment(self):
        from tools.contracts import snowflake_cli_live_validation as module

        sql = module._formula_expected_sql(SnowflakeCliValidationOptions(connection="dev", profile="internal_live"))

        self.assertIn("CREDITS_ADJUSTMENT_CLOUD_SERVICES", sql)
        self.assertIn("FROM FACT_COST_DAILY", sql)
        self.assertIn("FROM FACT_WAREHOUSE_HOURLY", sql)
        self.assertIn("FROM FACT_CORTEX_DAILY", sql)
        self.assertIn("'CORTEX_AI_COST_USD', c.cortex_ai_credits * 2.2", sql)
        self.assertNotIn("'CORTEX_AI_COST_USD', c.cortex_ai_credits * 3.68", sql)
        self.assertNotIn("'CLOUD_SERVICES_ADJUSTMENT', 0", sql)

    def test_packet_availability_sql_does_not_require_is_active_on_command_brief(self):
        from tools.contracts import snowflake_cli_live_validation as module

        sql = module._packet_availability_sql(SnowflakeCliValidationOptions(connection="dev", profile="internal_live"))
        command_branch = sql.split("FROM MART_SECTION_COMMAND_BRIEF", 1)[0]

        self.assertIn("TRUE AS is_active", command_branch)
        self.assertNotIn("COALESCE(IS_ACTIVE, TRUE) AS is_active", command_branch)

    def test_packet_flat_sql_prefers_exact_but_keeps_fallback_rows(self):
        from tools.contracts import snowflake_cli_live_validation as module

        sql = module._packet_flat_sql(SnowflakeCliValidationOptions(connection="dev", profile="internal_live"))

        self.assertIn("COALESCE(IS_EXACT_SCOPE, FALSE) DESC", sql)
        self.assertNotIn("AND COALESCE(IS_EXACT_SCOPE, TRUE)", sql)

    def test_nested_json_output_from_multistatement_temp_file_is_flattened(self):
        from tools.contracts import snowflake_cli_live_validation as module

        rows = module._parse_json_rows(
            json.dumps(
                [
                    [{"status": "Statement executed successfully."}],
                    [{"ROW_JSON": {"section": "Executive Landing", "boundary": "first_paint_packet"}}],
                ]
            )
        )

        self.assertEqual(rows[-1]["ROW_JSON"]["section"], "Executive Landing")
        self.assertTrue(any(row.get("status") == "Statement executed successfully." for row in rows))

    def test_null_packet_value_with_source_rows_fails_formula_validation(self):
        with _root_with_validation_sql() as temp:
            artifacts = write_snowflake_cli_live_validation_artifacts(
                temp,
                options=SnowflakeCliValidationOptions(connection="dev", profile="internal_fixture"),
                runner=_runner(null_packet_field="ACCOUNT_BILLED_COST_USD"),
            )

        self.assertFalse(artifacts[CLI_FORMULA_VALUE_REL]["passed"], artifacts[CLI_FORMULA_VALUE_REL])
        failures = {
            row["formula_field"]: row["failure_reason"]
            for row in artifacts[CLI_FORMULA_VALUE_REL]["rows"]
            if row["status"] == "failed"
        }
        self.assertIn("ACCOUNT_BILLED_COST_USD", failures)
        self.assertIn("source rows exist", failures["ACCOUNT_BILLED_COST_USD"])

    def test_sanitizer_preserves_object_names_but_strips_sql_and_secrets(self):
        with patch.dict(os.environ, {"SNOWFLAKE_PASSWORD": "p4ssword-secret"}, clear=False):
            sanitized = sanitize_text(
                'Procedure SP_OVERWATCH_REFRESH failed password=p4ssword-secret SELECT * FROM account_usage.table'
            )
        self.assertIn("SP_OVERWATCH_REFRESH", sanitized)
        self.assertNotIn("p4ssword-secret", sanitized)
        self.assertNotIn("account_usage.table", sanitized)
        self.assertNotIn("SELECT *", sanitized)

    def test_sanitizer_removes_cli_traceback_guidance_and_credwrite_details(self):
        sanitized = sanitize_text(
            "An unexpected exception occurred. Use --debug option to see the traceback. "
            "Exception message:\n\n(1783, 'CredWrite', 'The stub received bad data')"
        )

        self.assertIn("Snowflake CLI failed before query execution", sanitized)
        self.assertIn("local credential store write failed", sanitized)
        self.assertNotIn("traceback", sanitized.lower())
        self.assertNotIn("CredWrite", sanitized)
        self.assertNotIn("The stub received bad data", sanitized)

    def test_runbook_mentions_connection_test_artifacts_and_live_profile_policy(self):
        text = (ROOT / "docs" / "snowflake_cli_live_validation.md").read_text(encoding="utf-8")
        self.assertIn("snow connection test -c <connection>", text)
        self.assertIn("artifacts/snowflake_validation/snowflake_cli_capability_results.json", text)
        self.assertIn("internal_live", text)
        self.assertIn("prod_candidate", text)
        self.assertIn("must not record passwords", text.lower())


if __name__ == "__main__":
    unittest.main()
