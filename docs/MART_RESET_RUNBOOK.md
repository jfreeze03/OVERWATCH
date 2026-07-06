# OVERWATCH Mart Reset Runbook

Use this when the mart logic, object names, or retired tables changed enough that a clean
Snowflake rebuild is safer than incremental migrations.

## Scope

This reset affects only the OVERWATCH mart runtime in `DBA_MAINT_DB.OVERWATCH` by
default. The drop script includes commented optional lines for the database,
warehouse, resource monitor, and roles. Leave those optional lines commented unless
you intend to remove the full runtime container.

## Before You Start

1. Confirm you are connected with the DBA role that owns the OVERWATCH objects.
2. Confirm no app user is actively relying on the current mart refresh.
3. Save any manual notes you need from `OVERWATCH_ACTION_QUEUE`, alert history, or
   recovery tables if you are intentionally preserving operational history elsewhere.
4. Keep a copy of the current `snowflake/mart_setup/` ordered files (the
   canonical human deployment path), `snowflake/ACTIVE_MART_DDL_MANIFEST.yml`,
   and `snowflake/OVERWATCH_MART_DROP.sql` from the same Git revision.
   `snowflake/OVERWATCH_MART_SETUP.sql` is the byte-equivalent generated
   single-file artifact of the active split if you prefer one file.

## Reset Sequence

Run the scripts in this order from a Snowflake worksheet or SnowSQL session.

Step 1 - remove current OVERWATCH mart objects:

```sql
!source snowflake/OVERWATCH_MART_DROP.sql
```

Step 2 - recreate current OVERWATCH mart objects and seed configuration. Deploy
the ordered split under `snowflake/mart_setup/` (the canonical human deployment
path). Either use the bundled runner:

```bash
cd snowflake/mart_setup
./run_mart_setup.sh <snowsql-connection-name>
```

or run the numbered files in order in a single session (so the `USE
DATABASE/SCHEMA` context carries across files):

```sql
!source snowflake/mart_setup/01_runtime_objects.sql
!source snowflake/mart_setup/02_roles_and_grants.sql
!source snowflake/mart_setup/03_config_and_audit_tables.sql
!source snowflake/mart_setup/04_mart_tables.sql
!source snowflake/mart_setup/05_load_procedures.sql
!source snowflake/mart_setup/06_alert_framework.sql
!source snowflake/mart_setup/07_tasks.sql
!source snowflake/validation/validate_overwatch_mart_setup.sql
```

The single-file artifact `snowflake/OVERWATCH_MART_SETUP.sql` is byte-for-byte
equivalent to the ordered concatenation of the seven active setup files
(enforced by `tests/test_mart_setup_split.py`), so
`!source snowflake/OVERWATCH_MART_SETUP.sql` produces the same setup result if
you prefer one file. Run `snowflake/validation/validate_overwatch_mart_setup.sql`
afterward for smoke checks.

If your SQL client does not support `!source`, open each file and run it as a script.

The drop script suspends tasks before dropping them, drops dependent tasks/views/
procedures before tables, and keeps extra `DROP IF EXISTS` statements for retired
objects from older deployments.

The rebuild target is task/procedure-loaded physical tables. Do not convert
retired or rebuilt facts to Dynamic Tables when a source dependency can include
secure views; use the scheduled refresh chain in `OVERWATCH_MART_SETUP.sql`
instead.

Snowflake allows ordinary table drops to remove dynamic table objects with the
same name, so the table drop section is also the cleanup path for older same-name
mart objects that were deployed before the physical-table refresh model. After
the rebuild, run the validation script and confirm both dynamic-table and secure
view collision checks return `PASS`.

After validation, run `snowflake/OVERWATCH_ALERT_OPERATIONS_REVIEW.sql` before
promoting native alerts or changing thresholds. It reviews alert object
readiness, threshold/baseline candidates, ALFA/Trexis company scope, and the
dynamic-table compatibility follow-up in one read-only worksheet pass.

## Dry-Run Readiness

Before running a destructive lower-environment reset, do a local static rehearsal
from this Git revision:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_formula_regressions.FormulaRegressionTests.test_overwatch_mart_drop_script_covers_setup_objects
.\.venv\Scripts\python.exe -m unittest tests.test_formula_regressions.FormulaRegressionTests.test_mart_refresh_procedures_do_not_write_retired_objects
```

Then review the generated object inventory in `docs/MART_OBJECT_REVIEW.md`.
Do not run the drop script if either guard fails. A failure means the setup/drop
pair is out of sync or a retired object has leaked back into refresh logic.

For a worksheet rehearsal, keep the first run in a non-production account or
schema. Use the same role, database, schema, warehouse, and Git revision for
drop, setup, validation, and task resume so the object count and procedure output
map stay comparable.

## Required Refresh Calls

The setup script already runs the bootstrap calls near the end. If you need to rerun
them manually after setup, use:

```sql
CALL SP_OVERWATCH_LOAD_HOURLY_UNIT('WAREHOUSE_HOURLY', NULL, NULL);
CALL SP_OVERWATCH_LOAD_HOURLY_UNIT('QUERY_HOURLY', NULL, NULL);
CALL SP_OVERWATCH_LOAD_HOURLY_UNIT('QUERY_DETAIL', NULL, NULL);
CALL SP_OVERWATCH_LOAD_HOURLY_UNIT('OBJECT_CHANGE', NULL, NULL);
CALL SP_OVERWATCH_LOAD_HOURLY_UNIT('TASK_RUN', NULL, NULL);
CALL SP_OVERWATCH_LOAD_HOURLY_UNIT('PROCEDURE_RUN', NULL, NULL);
CALL SP_OVERWATCH_LOAD_HOURLY_UNIT('SNAPSHOTS', NULL, NULL);
CALL SP_OVERWATCH_LOAD_HOURLY_UNIT('TASK_CRITICAL_PATH', NULL, NULL);
CALL SP_OVERWATCH_LOAD_CORTEX();
CALL SP_OVERWATCH_REFRESH_CONTROL_ROOM();
CALL SP_OVERWATCH_REFRESH_COST_MONITORING();
CALL SP_OVERWATCH_LOAD_DAILY();
CALL SP_OVERWATCH_REFRESH_EXECUTIVE_OBSERVABILITY();
```

`SP_OVERWATCH_LOAD_HOURLY()` remains only as a guarded compatibility wrapper.
By default it records a `SKIPPED` audit row and returns guidance instead of
running the full chain, because the parent call can still exceed a 1000-second
statement timeout. Use the unit calls above, or manually trigger the root task
with `EXECUTE TASK OVERWATCH_LOAD_HOURLY;` after child tasks are resumed. For
historical backfill, run the same unit procedure with explicit day windows, for
example `CALL SP_OVERWATCH_LOAD_HOURLY_UNIT('QUERY_HOURLY', 35, 28);`.

## Validation

Run the validation script after setup:

```sql
!source snowflake/OVERWATCH_MART_VALIDATION.sql
```

At this revision the expected deployable object inventory is:

| Object type | Expected count |
| --- | ---: |
| Tables | 56 |
| Views | 2 |
| Procedures | 8 |
| Functions | 1 |
| Tasks | 7 |

`OVERWATCH_MART_VALIDATION.sql` reports the table/view/procedure/function count
contract directly. It also runs `SHOW TASKS IN SCHEMA` and reports each expected
task as `PRESENT`, `SUSPENDED`, or `MISSING`. A clean post-setup run should show
all seven expected tasks as `PRESENT`; if a task is `SUSPENDED`, resume the root
tasks listed below after confirming setup completed.

The latest static scan also confirmed that every deployable object has matching
drop coverage in `snowflake/OVERWATCH_MART_DROP.sql`. The remaining objects with
no direct app/test references are refresh procedures or `OVERWATCH_LOAD_AUDIT`
bookkeeping, so the reset path should keep them unless their downstream facts are
retired in a future setup revision.

The drop script also has a retired compatibility cleanup block for old deployed
objects that are intentionally absent from setup. Keep those drops even when the
current setup count is clean; they make lower-environment rebuilds recover from
older OVERWATCH DDL without a manual archaeology pass.

The validation script also reports:

| Check | Expected status |
| --- | --- |
| `DYNAMIC_TABLE_COLLISIONS` | `PASS` |
| `SECURE_VIEW_COLLISIONS` | `PASS` |

Latest consolidation note: repeated-query, duplicate-query, warehouse
right-sizing, clustering, storage-retention, and procedure summary reads moved
behind shared app loaders. A reset does not need new objects for that pass, but a
fresh setup should still recreate `FACT_QUERY_DETAIL_RECENT`,
`FACT_PROCEDURE_RUN`, and the procedure/task snapshots because those are now used
more broadly as fast advisor inputs.

Latest mart/SP audit note: the refresh procedures only write current mart facts
and summary marts. Retired automation, packet, monitoring-cost, external-control,
owner-directory, and cost-savings verification objects are not recreated by setup;
they remain in `snowflake/OVERWATCH_MART_DROP.sql` only so a mass drop removes
old deployed copies before a fresh setup.

Also confirm:

```sql
WITH deployed_objects AS (
    SELECT 'TABLE' AS OBJECT_TYPE, TABLE_NAME AS OBJECT_NAME
    FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_SCHEMA = CURRENT_SCHEMA()
    UNION ALL
    SELECT 'VIEW', TABLE_NAME
    FROM INFORMATION_SCHEMA.VIEWS
    WHERE TABLE_SCHEMA = CURRENT_SCHEMA()
    UNION ALL
    SELECT 'PROCEDURE', PROCEDURE_NAME
    FROM INFORMATION_SCHEMA.PROCEDURES
    WHERE PROCEDURE_SCHEMA = CURRENT_SCHEMA()
    UNION ALL
    SELECT 'FUNCTION', FUNCTION_NAME
    FROM INFORMATION_SCHEMA.FUNCTIONS
    WHERE FUNCTION_SCHEMA = CURRENT_SCHEMA()
)
SELECT OBJECT_TYPE, COUNT(*) AS OBJECT_COUNT
FROM deployed_objects
WHERE OBJECT_NAME ILIKE 'OVERWATCH%'
   OR OBJECT_NAME ILIKE 'FACT_%'
   OR OBJECT_NAME ILIKE 'DIM_%'
   OR OBJECT_NAME ILIKE 'MART_%'
   OR OBJECT_NAME ILIKE 'SP_OVERWATCH%'
GROUP BY OBJECT_TYPE
ORDER BY OBJECT_TYPE;

SHOW TASKS IN SCHEMA;

SELECT *
FROM OVERWATCH_SCHEMA_MIGRATION
ORDER BY APPLIED_AT DESC
LIMIT 5;

SELECT LOAD_NAME, STATUS, LOAD_STARTED_AT, LOAD_FINISHED_AT, MESSAGE
FROM OVERWATCH_LOAD_AUDIT
ORDER BY LOAD_STARTED_AT DESC
LIMIT 20;

SELECT 'FACT_MONITORING_COST_DAILY' AS RETIRED_OBJECT, COUNT(*) AS PRESENT
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = CURRENT_SCHEMA()
  AND TABLE_NAME = 'FACT_MONITORING_COST_DAILY'
UNION ALL
SELECT 'OVERWATCH_EXECUTIVE_PACKET', COUNT(*)
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = CURRENT_SCHEMA()
  AND TABLE_NAME = 'OVERWATCH_EXECUTIVE_PACKET'
UNION ALL
SELECT 'OVERWATCH_AUTOMATION_HEALTH_V', COUNT(*)
FROM INFORMATION_SCHEMA.VIEWS
WHERE TABLE_SCHEMA = CURRENT_SCHEMA()
  AND TABLE_NAME = 'OVERWATCH_AUTOMATION_HEALTH_V';
```

## Resume Tasks

`OVERWATCH_MART_SETUP.sql` resumes the current task chain. If you manually suspended
tasks after setup, resume the child tasks first and the scheduled roots last:

```sql
ALTER TASK IF EXISTS OVERWATCH_EXECUTIVE_OBSERVABILITY_REFRESH RESUME;
ALTER TASK IF EXISTS OVERWATCH_COST_MONITORING_REFRESH RESUME;
ALTER TASK IF EXISTS OVERWATCH_REFRESH_CONTROL_ROOM RESUME;
ALTER TASK IF EXISTS OVERWATCH_LOAD_CORTEX RESUME;
ALTER TASK IF EXISTS OVERWATCH_LOAD_TASK_CRITICAL_PATH RESUME;
ALTER TASK IF EXISTS OVERWATCH_LOAD_SNAPSHOTS RESUME;
ALTER TASK IF EXISTS OVERWATCH_LOAD_PROCEDURE_RUN RESUME;
ALTER TASK IF EXISTS OVERWATCH_LOAD_TASK_RUN RESUME;
ALTER TASK IF EXISTS OVERWATCH_LOAD_OBJECT_CHANGE RESUME;
ALTER TASK IF EXISTS OVERWATCH_LOAD_QUERY_DETAIL RESUME;
ALTER TASK IF EXISTS OVERWATCH_LOAD_QUERY_HOURLY RESUME;
ALTER TASK IF EXISTS OVERWATCH_LOAD_HOURLY RESUME;
ALTER TASK IF EXISTS OVERWATCH_LOAD_DAILY RESUME;
ALTER TASK IF EXISTS OVERWATCH_ANOMALY_CHECK RESUME;
```

The hourly root now loads warehouse metering first, then the `AFTER` chain runs
query summary, detail, object change, task run, procedure run, snapshots, task
critical path, Cortex, Control Room, cost monitoring, and executive observability.

## Current Retired Objects Covered

The drop script intentionally removes these old deployment objects even though the
setup script no longer creates them:

| Retired object | Current replacement |
| --- | --- |
| `FACT_MONITORING_COST_DAILY` | `FACT_COST_DAILY`, `FACT_COST_MONITORING_SIGNAL`, `FACT_COST_INCIDENT_TIMELINE` |
| `OVERWATCH_AUTOMATION_RUN` | Alert delivery log plus action queue telemetry |
| `OVERWATCH_EXECUTIVE_PACKET` | `MART_EXECUTIVE_OBSERVABILITY` |
| `OVERWATCH_AUTOMATION_HEALTH_V` | Alert Center and executive observability marts |
| `SP_OVERWATCH_REFRESH_AUTOMATION` | Cost monitoring and executive observability refresh procedures |
| `OVERWATCH_AUTOMATION_REFRESH` | Current cost and executive refresh task chain |
| `OVERWATCH_COST_SAVINGS_VERIFICATION_RUN`, `OVERWATCH_COST_SAVINGS_VERIFICATION_HEALTH_V`, `SP_OVERWATCH_VERIFY_COST_SAVINGS`, `OVERWATCH_COST_SAVINGS_VERIFY` | Removed cost-savings verification workflow; current advisor estimates stay in app/session telemetry. |
| `OVERWATCH_EXTERNAL_CONTROL_FEED`, `OVERWATCH_SOURCE_CONTROL_CHANGE`, `OVERWATCH_OWNER_APPROVAL` | Removed external/change-governance placeholders; DBA monitoring keeps only current Snowflake telemetry and action queue state. |
| `OVERWATCH_OWNER_DIRECTORY`, `OVERWATCH_OWNER_DIRECTORY_ACTIVE_V` | Removed owner directory workflow; owner tag configuration remains in `OVERWATCH_OWNER_TAG_NAMES` and `DIM_COST_OWNER_TAG`. |
| `OVERWATCH_PLATFORM_FUTURES_CONTROL_REGISTER`, `OVERWATCH_PLATFORM_FUTURES_EVIDENCE`, platform futures views | Removed architecture/futures readiness workflow; current scope is operational monitoring. |
| `OVERWATCH_COMMAND_INTELLIGENCE_CAPABILITY`, `OVERWATCH_REFRESH_POLICY`, `OVERWATCH_COMPANY_SCOPE`, `OVERWATCH_COMPLIANCE_READINESS_V` | Removed static metadata/control tables; current contracts live in docs, Python config, and validation SQL. |

No additional retired objects were identified in the latest mart/SP audit. The
current refresh chain no longer recreates the retired automation or monitoring
cost objects listed above.

## Rollback

If setup fails after the drop:

1. Keep tasks suspended.
2. Capture the failing SQL statement and Snowflake error.
3. Re-run only the failed section after fixing the setup script.
4. Run the validation script again.
5. Resume root tasks only after validation passes.
