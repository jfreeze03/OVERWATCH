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
4. Keep a copy of the current `snowflake/OVERWATCH_MART_SETUP.sql` and
   `snowflake/OVERWATCH_MART_DROP.sql` from the same Git revision.

## Reset Sequence

Run the scripts in this order from a Snowflake worksheet or SnowSQL session:

```sql
-- 1. Remove current OVERWATCH mart objects.
!source snowflake/OVERWATCH_MART_DROP.sql

-- 2. Recreate current OVERWATCH mart objects and seed configuration.
!source snowflake/OVERWATCH_MART_SETUP.sql
```

If your SQL client does not support `!source`, open each file and run it as a script.

The drop script suspends tasks before dropping them, drops dependent tasks/views/
procedures before tables, and keeps extra `DROP IF EXISTS` statements for retired
objects from older deployments.

## Required Refresh Calls

The setup script already runs the bootstrap calls near the end. If you need to rerun
them manually after setup, use:

```sql
CALL SP_OVERWATCH_LOAD_HOURLY();
CALL SP_OVERWATCH_LOAD_CORTEX();
CALL SP_OVERWATCH_REFRESH_CONTROL_ROOM();
CALL SP_OVERWATCH_REFRESH_COST_MONITORING();
CALL SP_OVERWATCH_LOAD_DAILY();
CALL SP_OVERWATCH_REFRESH_EXECUTIVE_OBSERVABILITY();
```

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

Also confirm:

```sql
SELECT *
FROM OVERWATCH_SCHEMA_MIGRATION
ORDER BY APPLIED_AT DESC
LIMIT 5;

SELECT LOAD_NAME, STATUS, LOAD_STARTED_AT, LOAD_FINISHED_AT, MESSAGE
FROM OVERWATCH_LOAD_AUDIT
ORDER BY LOAD_STARTED_AT DESC
LIMIT 20;
```

## Resume Tasks

`OVERWATCH_MART_SETUP.sql` resumes the current task chain. If you manually suspended
tasks after setup, resume the root tasks only:

```sql
ALTER TASK IF EXISTS OVERWATCH_LOAD_HOURLY RESUME;
ALTER TASK IF EXISTS OVERWATCH_LOAD_DAILY RESUME;
ALTER TASK IF EXISTS OVERWATCH_ANOMALY_CHECK RESUME;
```

Child tasks resume from the setup script and run through their `AFTER` dependencies.

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

## Rollback

If setup fails after the drop:

1. Keep tasks suspended.
2. Capture the failing SQL statement and Snowflake error.
3. Re-run only the failed section after fixing the setup script.
4. Run the validation script again.
5. Resume root tasks only after validation passes.
