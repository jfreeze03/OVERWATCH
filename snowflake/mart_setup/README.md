# OVERWATCH Mart Setup (split deployment)

These numbered files are an **order-preserving split** of
[`../OVERWATCH_MART_SETUP.sql`](../OVERWATCH_MART_SETUP.sql). Concatenating them
in numeric order reproduces the original monolithic setup script
**byte-for-byte** (enforced by `tests/test_mart_setup_split.py`), so deploying
the parts in order is exactly equivalent to running the monolith.

The monolith remains the canonical source of truth; these parts make the DDL
easier to review and deploy in stages.

## Deployment order

Run the files **in numeric order** in a single session (they share session
context such as `USE DATABASE DBA_MAINT_DB; USE SCHEMA OVERWATCH;`, which is
established in `01_runtime_objects.sql`):

| Order | File | Contents |
|-------|------|----------|
| 1 | `01_runtime_objects.sql` | Database, schema, dedicated `OVERWATCH_WH` warehouse, and resource monitor. Establishes the session `USE DATABASE/SCHEMA` context. |
| 2 | `02_roles_and_grants.sql` | Access roles (`SNOW_ACCOUNTADMINS`, `SNOW_SYSADMINS`) and their warehouse/database/schema/table/view grants. |
| 3 | `03_config_and_audit_tables.sql` | Configuration, schema-migration, audit, action-queue, checklist, change-control, and alert tables, plus the environment UDF and supporting views. |
| 4 | `04_mart_tables.sql` | Transient mart/fact/dimension tables and their views. |
| 5 | `05_load_procedures.sql` | Load / refresh stored procedures (`SP_OVERWATCH_*`). |
| 6 | `06_alert_framework.sql` | Alert Command Center tables and procedures. |
| 7 | `07_tasks.sql` | Task graph that schedules the load procedures. |
| 8 | `08_validation.sql` | Smoke checks: `SHOW TASKS`, row-count validation, and an initial `CALL` of each refresh procedure. |

The hourly refresh is intentionally chunked. `SP_OVERWATCH_LOAD_HOURLY_UNIT`
loads one bounded unit/window at a time, and `07_tasks.sql` chains those units
through separate tasks. This prevents a single `CALL SP_OVERWATCH_LOAD_HOURLY()`
from being the only production path on accounts with a 1000-second statement
timeout. The no-argument procedure remains as a guarded compatibility wrapper
and is disabled by default through `HOURLY_REFRESH_COMPAT_WRAPPER_ENABLED`.
Operators should use the task chain or explicit unit calls for backfill.

> The numbering reflects the dependency-safe order of the original script:
> runtime objects and roles first, then tables, then the procedures/tasks that
> populate them, and finally validation. (Roles intentionally come *after* the
> warehouse/database in step 1 because the role grants in step 2 reference
> those objects.)

## Running

### Option A: the bundled runner

```bash
# Requires snowsql on PATH and a configured connection.
./run_mart_setup.sh <snowsql-connection-name>
```

### Option B: snowsql by hand

```bash
for f in 01_*.sql 02_*.sql 03_*.sql 04_*.sql 05_*.sql 06_*.sql 07_*.sql 08_*.sql; do
  snowsql -c <connection> -f "$f"
done
```

### Option C: the original monolith

```bash
snowsql -c <connection> -f ../OVERWATCH_MART_SETUP.sql
```

All three options produce the same end state.
