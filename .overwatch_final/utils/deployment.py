# utils/deployment.py - release and mart migration status helpers
from __future__ import annotations

from pathlib import Path

import pandas as pd


OVERWATCH_SCHEMA_VERSION = "2026.06.13-executive-observability-mart"
MIGRATION_TABLE = "OVERWATCH_SCHEMA_MIGRATION"
STREAMLIT_DEPLOYMENT_DECISION_VERSION = "2026.06.13-streamlit-entrypoint-contract"
STREAMLIT_MANIFEST_CONTRACT_VERSION = "2026.06.13-sis-manifest-contract"
STREAMLIT_SNOWFLAKE_ARTIFACTS = (
    "app.py",
    "access_control.py",
    "config.py",
    "filters.py",
    "layout.py",
    "navigation.py",
    "perf_trace.py",
    "refresh.py",
    "runtime_state.py",
    "section_dispatch.py",
    "shell.py",
    "theme.py",
    "environment.yml",
    "utils/",
    "sections/",
)


def _repo_root(root: str | Path | None = None) -> Path:
    if root is not None:
        return Path(root)
    return Path(__file__).resolve().parents[2]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _contract_row(
    check: str,
    expected: str,
    actual: str,
    ready: bool,
    next_action: str = "No action.",
) -> dict[str, str]:
    return {
        "CHECK": check,
        "EXPECTED": expected,
        "ACTUAL": actual,
        "STATE": "Ready" if ready else "Blocked",
        "NEXT_ACTION": next_action if not ready else "No action.",
    }


def build_streamlit_manifest_contract(root: str | Path | None = None) -> pd.DataFrame:
    """Validate the pinned Streamlit deployment files without importing app code."""
    repo = _repo_root(root)
    app_root = repo / ".overwatch_final"
    manifest_path = app_root / "snowflake.yml"
    wrapper_path = repo / "streamlit_app.py"
    cloud_config_path = repo / ".streamlit" / "config.toml"
    deploy_doc_path = repo / "STREAMLIT_CLOUD_DEPLOY.md"
    ci_path = repo / ".github" / "workflows" / "validate.yml"
    cortex_path = app_root / "utils" / "cortex.py"

    manifest = _read_text(manifest_path)
    wrapper = _read_text(wrapper_path)
    cloud_config = _read_text(cloud_config_path)
    deploy_doc = _read_text(deploy_doc_path)
    ci_text = _read_text(ci_path)
    cortex_text = _read_text(cortex_path)

    artifact_states = []
    for artifact in STREAMLIT_SNOWFLAKE_ARTIFACTS:
        listed = f"- {artifact}" in manifest
        exists = (app_root / artifact.rstrip("/")).exists()
        artifact_states.append((artifact, listed, exists))
    missing_artifacts = [name for name, listed, exists in artifact_states if not (listed and exists)]

    rows = [
        _contract_row(
            "Snowflake manifest file",
            ".overwatch_final/snowflake.yml exists",
            "present" if manifest_path.exists() else "missing",
            manifest_path.exists(),
            "Restore .overwatch_final/snowflake.yml before deploying Streamlit in Snowflake.",
        ),
        _contract_row(
            "Snowflake entrypoint",
            "main_file: app.py",
            "app.py" if "main_file: app.py" in manifest else "unknown",
            "main_file: app.py" in manifest,
            "Keep Streamlit-in-Snowflake pointed at .overwatch_final/app.py.",
        ),
        _contract_row(
            "Snowflake runtime warehouse",
            "query_warehouse: COMPUTE_WH",
            "COMPUTE_WH" if "query_warehouse: COMPUTE_WH" in manifest else "unknown",
            "query_warehouse: COMPUTE_WH" in manifest,
            "Use COMPUTE_WH for app execution until a dedicated OVERWATCH warehouse is approved.",
        ),
        _contract_row(
            "Snowflake caller boundary",
            "CALLER-mode deployment, never execute_as OWNER",
            "OWNER" if "execute_as: OWNER" in manifest else "CALLER documented",
            "execute_as: OWNER" not in manifest and "CALLER MODE MEANS" in manifest,
            "Keep the app in caller-mode. Do not deploy OVERWATCH as an owner-rights action runner.",
        ),
        _contract_row(
            "Snowflake package artifacts",
            ", ".join(STREAMLIT_SNOWFLAKE_ARTIFACTS),
            "missing: " + ", ".join(missing_artifacts) if missing_artifacts else "all listed and present",
            not missing_artifacts,
            "Update snowflake.yml artifacts and repository paths together.",
        ),
        _contract_row(
            "Community Cloud wrapper",
            "streamlit_app.py delegates to .overwatch_final/app.py",
            "wrapper pinned" if ".overwatch_final" in wrapper and "runpy.run_path" in wrapper else "unknown",
            ".overwatch_final" in wrapper and "runpy.run_path" in wrapper and "app.py" in wrapper,
            "Keep Community Cloud on the root wrapper and root requirements.txt.",
        ),
        _contract_row(
            "Community Cloud config",
            "sidebar navigation hidden and usage stats disabled",
            "configured" if "showSidebarNavigation = false" in cloud_config else "unknown",
            "showSidebarNavigation = false" in cloud_config and "gatherUsageStats = false" in cloud_config,
            "Restore .streamlit/config.toml production shell settings.",
        ),
        _contract_row(
            "Deployment guide",
            "runtime split and release rule documented",
            "documented" if "Deployment Decision" in deploy_doc and "Only commit and push" in deploy_doc else "unknown",
            "Deployment Decision" in deploy_doc
            and ".overwatch_final/snowflake.yml" in deploy_doc
            and "streamlit_app.py" in deploy_doc
            and "Only commit and push" in deploy_doc,
            "Update STREAMLIT_CLOUD_DEPLOY.md with the current deployment split.",
        ),
        _contract_row(
            "CI deployment contract",
            "validate.yml runs tests.test_deployment_contract",
            "present" if "tests.test_deployment_contract" in ci_text else "missing",
            "tests.test_deployment_contract" in ci_text,
            "Add the dedicated deployment-contract test step to .github/workflows/validate.yml.",
        ),
        _contract_row(
            "CI production shell guards",
            "validate.yml fast-fails production shell and navigation regressions before full suite",
            "present" if "Run production shell guards" in ci_text else "missing",
            "Run production shell guards" in ci_text
            and "test_streamlit_deployment_entrypoints_are_pinned" in ci_text
            and "test_app_shell_header_renders_before_sidebar_hydration" in ci_text
            and "test_workflow_hubs_replace_scattered_operational_pages" in ci_text
            and "test_dead_ui_helpers_stay_removed" in ci_text,
            "Add the production shell guard step before the full test suite in .github/workflows/validate.yml.",
        ),
        _contract_row(
            "Cortex completion guardrails",
            "ad hoc Cortex completions are throttled, cached, and telemetry-safe",
            "present" if "Run Cortex guardrails" in ci_text else "missing",
            "Run Cortex guardrails" in ci_text
            and "tests.test_cortex_guard" in ci_text
            and "DEFAULT_CORTEX_COOLDOWN_SECONDS" in cortex_text
            and "DEFAULT_CORTEX_DAILY_CALL_LIMIT" in cortex_text
            and "DEFAULT_CORTEX_CACHE_TTL_SECONDS" in cortex_text
            and "_overwatch_cortex_cache" in cortex_text
            and "prompt_hash" in cortex_text,
            "Restore utils.cortex throttling, session cache, prompt-safe telemetry, and the CI guard step.",
        ),
    ]
    return pd.DataFrame(rows)


def build_streamlit_deployment_decision() -> pd.DataFrame:
    """Return the pinned OVERWATCH Streamlit deployment entrypoint contract."""
    rows = [
        {
            "RUNTIME": "Streamlit in Snowflake",
            "DECISION": "Use .overwatch_final/snowflake.yml",
            "ENTRYPOINT": ".overwatch_final/app.py",
            "MANIFEST": ".overwatch_final/snowflake.yml",
            "WAREHOUSE": "COMPUTE_WH",
            "EXECUTE_AS": "CALLER",
            "DEPLOY_CONTEXT": "Snowflake app package root is .overwatch_final.",
            "DO_NOT_USE": "streamlit_app.py, execute_as OWNER",
            "WHY_IT_MATTERS": "Keeps app execution on the approved current warehouse with caller-mode privileges.",
        },
        {
            "RUNTIME": "Streamlit Community Cloud",
            "DECISION": "Use root streamlit_app.py wrapper",
            "ENTRYPOINT": "streamlit_app.py",
            "MANIFEST": ".streamlit/config.toml",
            "WAREHOUSE": "User-provided Snowflake connection",
            "EXECUTE_AS": "Connected Snowflake role",
            "DEPLOY_CONTEXT": "Public wrapper inserts .overwatch_final into sys.path and runs .overwatch_final/app.py.",
            "DO_NOT_USE": ".overwatch_final/snowflake.yml",
            "WHY_IT_MATTERS": "Keeps Community Cloud on root requirements.txt instead of Snowflake-specific environment.yml.",
        },
        {
            "RUNTIME": "Snowflake status",
            "DECISION": "DBA-owned Snowflake objects provide summary facts",
            "ENTRYPOINT": "Approved DBA release process",
            "MANIFEST": "utils.deployment schema contract",
            "WAREHOUSE": "Dedicated summary refresh and app runtime warehouses",
            "EXECUTE_AS": "Reviewed DBA role",
            "DEPLOY_CONTEXT": "Data objects and migration status are owned outside the Streamlit UI.",
            "DO_NOT_USE": "ad hoc app-generated object changes as source of truth",
            "WHY_IT_MATTERS": "Separates UI deployment from reviewed Snowflake data-health ownership.",
        },
    ]
    return pd.DataFrame(rows)


def build_schema_migration_contract() -> pd.DataFrame:
    """Return the baseline mart/setup versions expected by this app release."""
    rows = [
        {
            "COMPONENT": "Core mart setup",
            "REQUIRED_VERSION": OVERWATCH_SCHEMA_VERSION,
            "REQUIRED_OBJECT": "OVERWATCH_SETTINGS",
            "WHY_IT_MATTERS": "Stores cost, alert, and runtime settings used by every DBA workflow.",
            "READY_CRITERIA": "Version row exists and OVERWATCH_SETTINGS is queryable.",
        },
        {
            "COMPONENT": "Action queue and telemetry status",
            "REQUIRED_VERSION": OVERWATCH_SCHEMA_VERSION,
            "REQUIRED_OBJECT": "OVERWATCH_ACTION_QUEUE",
            "WHY_IT_MATTERS": "Keeps recommendations, alert routes, cost actions, and closure status auditable.",
            "READY_CRITERIA": "Queue table exists with route, SLA, review, and telemetry columns.",
        },
        {
            "COMPONENT": "Alert delivery",
            "REQUIRED_VERSION": OVERWATCH_SCHEMA_VERSION,
            "REQUIRED_OBJECT": "OVERWATCH_ALERT_DELIVERY_LOG",
            "WHY_IT_MATTERS": "Stores digest delivery telemetry, escalation acknowledgement, and email health history.",
            "READY_CRITERIA": "Delivery log exists and Alert Center can write digest telemetry.",
        },
        {
            "COMPONENT": "Alert delivery",
            "REQUIRED_VERSION": OVERWATCH_SCHEMA_VERSION,
            "REQUIRED_OBJECT": "OVERWATCH_ANNOTATIONS",
            "WHY_IT_MATTERS": "Stores suppression windows used by the hourly anomaly task to avoid duplicate alert noise.",
            "READY_CRITERIA": "Annotation table exists before OVERWATCH_ANOMALY_CHECK is resumed.",
        },
        {
            "COMPONENT": "Cost telemetry mart",
            "REQUIRED_VERSION": OVERWATCH_SCHEMA_VERSION,
            "REQUIRED_OBJECT": "FACT_COST_DAILY",
            "WHY_IT_MATTERS": "Persists billed cost by Snowflake service type so the UI does not rescan daily metering views.",
            "READY_CRITERIA": "Daily service-cost mart and source-health mart exist.",
        },
        {
            "COMPONENT": "Executive observability mart",
            "REQUIRED_VERSION": OVERWATCH_SCHEMA_VERSION,
            "REQUIRED_OBJECT": "MART_EXECUTIVE_OBSERVABILITY",
            "WHY_IT_MATTERS": "Serves the boss-ready Executive Landing graphics from one tiny precomputed result set instead of live-assembling heavy telemetry.",
            "READY_CRITERIA": "Executive observability table, refresh procedure, and task are deployed.",
        },
        {
            "COMPONENT": "Procedure runtime context",
            "REQUIRED_VERSION": OVERWATCH_SCHEMA_VERSION,
            "REQUIRED_OBJECT": "FACT_PROCEDURE_RUN",
            "WHY_IT_MATTERS": "Keeps stored procedure failures, runtime spikes, and child-query telemetry scoped to database and schema.",
            "READY_CRITERIA": "Procedure run fact exists with DATABASE_NAME, SCHEMA_NAME, ENVIRONMENT, and PROCEDURE_NAME.",
        },
        {
            "COMPONENT": "Schema migration ledger",
            "REQUIRED_VERSION": OVERWATCH_SCHEMA_VERSION,
            "REQUIRED_OBJECT": MIGRATION_TABLE,
            "WHY_IT_MATTERS": "Shows whether the deployed Snowflake mart is aligned to the app release.",
            "READY_CRITERIA": "Ledger contains the current app/setup version row.",
        },
    ]
    return pd.DataFrame(rows)


def build_schema_migration_status_sql(
    *,
    database: str = "DBA_MAINT_DB",
    schema: str = "OVERWATCH",
    required_version: str = OVERWATCH_SCHEMA_VERSION,
) -> str:
    """Build a Snowflake status query for setup/migration status."""
    db = str(database).replace('"', '""')
    sch = str(schema).replace('"', '""')
    version = str(required_version).replace("'", "''")
    return f"""
WITH required_objects AS (
    SELECT * FROM VALUES
        ('Core mart setup', 'OVERWATCH_SETTINGS', 'TABLE', '{version}'),
        ('Action queue and telemetry status', 'OVERWATCH_ACTION_QUEUE', 'TABLE', '{version}'),
        ('Alert delivery', 'OVERWATCH_ALERT_DELIVERY_LOG', 'TABLE', '{version}'),
        ('Alert delivery', 'OVERWATCH_ANNOTATIONS', 'TABLE', '{version}'),
        ('Cost telemetry mart', 'FACT_COST_DAILY', 'TABLE', '{version}'),
        ('Cost telemetry mart', 'FACT_COST_SOURCE_HEALTH_DAILY', 'TABLE', '{version}'),
        ('Executive observability mart', 'MART_EXECUTIVE_OBSERVABILITY', 'TABLE', '{version}'),
        ('Procedure runtime context', 'FACT_PROCEDURE_RUN', 'TABLE', '{version}'),
        ('Schema migration ledger', 'OVERWATCH_SCHEMA_MIGRATION', 'TABLE', '{version}')
    AS t(component, object_name, object_type, required_version)
),
object_inventory AS (
    SELECT table_name AS object_name, table_type AS object_type
    FROM {db}.INFORMATION_SCHEMA.TABLES
    WHERE table_schema = '{sch}'
    UNION ALL
    SELECT stage_name AS object_name, 'STAGE' AS object_type
    FROM {db}.INFORMATION_SCHEMA.STAGES
    WHERE stage_schema = '{sch}'
    UNION ALL
    SELECT file_format_name AS object_name, 'FILE FORMAT' AS object_type
    FROM {db}.INFORMATION_SCHEMA.FILE_FORMATS
    WHERE file_format_schema = '{sch}'
),
ledger AS (
    SELECT
        MAX_BY(MIGRATION_VERSION, APPLIED_AT) AS latest_version,
        MAX(APPLIED_AT) AS latest_applied_at
    FROM {db}.{sch}.OVERWATCH_SCHEMA_MIGRATION
)
SELECT
    r.component,
    r.object_name,
    r.object_type,
    IFF(i.object_name IS NULL, 'Missing', 'Present') AS object_state,
    r.required_version,
    COALESCE(l.latest_version, 'Unknown') AS deployed_version,
    l.latest_applied_at,
    CASE
        WHEN i.object_name IS NULL THEN 'Blocked'
        WHEN COALESCE(l.latest_version, '') <> r.required_version THEN 'Version Drift'
        ELSE 'Ready'
    END AS migration_state,
    CASE
        WHEN i.object_name IS NULL THEN 'Ask the DBA team to refresh Snowflake status objects.'
        WHEN COALESCE(l.latest_version, '') <> r.required_version THEN 'Ask the DBA team to apply the matching status migration.'
        ELSE 'No action.'
    END AS next_action
FROM required_objects r
LEFT JOIN object_inventory i
    ON i.object_name = r.object_name
LEFT JOIN ledger l
    ON TRUE
ORDER BY
    CASE migration_state WHEN 'Blocked' THEN 0 WHEN 'Version Drift' THEN 1 ELSE 2 END,
    component,
    object_name
"""


def build_schema_migration_ddl(required_version: str = OVERWATCH_SCHEMA_VERSION) -> str:
    """Return the additive setup ledger DDL used by the Snowflake setup bundle."""
    version = str(required_version).replace("'", "''")
    return f"""
CREATE TABLE IF NOT EXISTS OVERWATCH_SCHEMA_MIGRATION (
  MIGRATION_VERSION   VARCHAR(100) NOT NULL,
  MIGRATION_NAME      VARCHAR(300) NOT NULL,
  APPLIED_AT          TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  APPLIED_BY          VARCHAR(200) DEFAULT CURRENT_USER(),
  SOURCE_FILE         VARCHAR(500),
  NOTES               VARCHAR(1000)
);

MERGE INTO OVERWATCH_SCHEMA_MIGRATION tgt
USING (
  SELECT
    '{version}' AS MIGRATION_VERSION,
    'Executive observability mart, cost telemetry, procedure context, alert delivery, and migration ledger' AS MIGRATION_NAME,
    'snowflake/OVERWATCH_MART_SETUP.sql' AS SOURCE_FILE,
    'Baseline setup ledger row for the app release, including the executive first-paint observability mart, cost telemetry marts, procedure database/schema context, alert delivery, and migration tracking.' AS NOTES
) src
ON tgt.MIGRATION_VERSION = src.MIGRATION_VERSION
WHEN MATCHED THEN UPDATE SET
  MIGRATION_NAME = src.MIGRATION_NAME,
  SOURCE_FILE = src.SOURCE_FILE,
  NOTES = src.NOTES
WHEN NOT MATCHED THEN INSERT (MIGRATION_VERSION, MIGRATION_NAME, SOURCE_FILE, NOTES)
VALUES (src.MIGRATION_VERSION, src.MIGRATION_NAME, src.SOURCE_FILE, src.NOTES);
"""
