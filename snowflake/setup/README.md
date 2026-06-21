# OVERWATCH Mart Setup — ordered deployment files

These numbered files are an ordered, reviewable split of
[`../OVERWATCH_MART_SETUP.sql`](../OVERWATCH_MART_SETUP.sql). Concatenating them
in numeric order reproduces that monolith **byte-for-byte** (enforced by
`tests/test_mart_setup_split.py`), so deploying the parts in order is exactly
equivalent to deploying the single file.

The monolith remains the canonical artifact referenced by the app and the
existing deployment/validation tooling. Use whichever you prefer — they produce
the same Snowflake objects and grants.

## Deployment order

Run as a role that can `CREATE DATABASE / SCHEMA / WAREHOUSE / TASK / PROCEDURE`,
`SELECT` from `SNOWFLAKE.ACCOUNT_USAGE`, and `MONITOR ACCOUNT`.

| # | File | Contents |
|---|------|----------|
| 01 | `01_runtime_warehouse.sql` | Database, schema, app warehouse, resource monitor, `USE` context |
| 02 | `02_roles_grants.sql` | Access roles and schema/table/view grants (uses `FUTURE` grants) |
| 03 | `03_config_audit_tables.sql` | Settings, schema-migration, audit, action-queue, usage-log tables |
| 04 | `04_mart_tables.sql` | Transient mart tables |
| 05 | `05_load_procedures.sql` | Load/refresh stored procedures |
| 06 | `06_alert_framework.sql` | Alert framework objects |
| 07 | `07_tasks.sql` | Task graph (hourly/daily refresh tasks) |
| 08 | `08_validation.sql` | Smoke checks / validation |

The files **must run in order in the same session**: `01` sets the
`USE DATABASE/SCHEMA` context that the later files rely on, and `02` installs
`FUTURE` grants so that objects created in `03`–`07` inherit the correct
privileges.

## How to run

### Option A — snowsql, file by file (recommended)

```bash
./deploy.sh <snowsql_connection_name>
```

`deploy.sh` runs `01_*.sql` … `08_*.sql` in order through `snowsql`. Omit the
connection name to use your default snowsql connection.

### Option B — snowsql, single session via runner

From this directory:

```bash
snowsql -c <connection> -f 00_run_all.sql
```

`00_run_all.sql` uses snowsql `!source` to execute each numbered file in order.

### Option C — the original single file

```bash
snowsql -c <connection> -f ../OVERWATCH_MART_SETUP.sql
```

## Reset

To tear down, use [`../OVERWATCH_MART_DROP.sql`](../OVERWATCH_MART_DROP.sql).
To validate after deployment, use
[`../OVERWATCH_MART_VALIDATION.sql`](../OVERWATCH_MART_VALIDATION.sql).
