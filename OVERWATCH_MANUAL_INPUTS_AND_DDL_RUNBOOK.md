# OVERWATCH Manual Inputs And DDL Runbook

Last updated: June 6, 2026

This runbook lists the manual values and durable Snowflake objects that must
stay aligned for OVERWATCH to be production-ready.

## Source Of Truth

| Area | Primary location | Why it matters |
|---|---|---|
| App defaults, navigation, roles, company scope, environment scope | `.overwatch_final/config.py` | Controls Streamlit behavior before and alongside mart data. |
| Snowflake setup, facts, procedures, tasks, seed rows | `snowflake/OVERWATCH_MART_SETUP.sql` | Creates the durable production objects. |
| Release remediation SQL | `snowflake/OVERWATCH_RELEASE_REMEDIATION.sql` | Applies backward-compatible fixes for existing deployments that predate the current setup file. |
| Owner routing | `.overwatch_final/utils/owner_directory.py` and `OVERWATCH_OWNER_DIRECTORY` | Routes cost, security, workload, warehouse, change, and architecture work. |
| Alert rules | `.overwatch_final/utils/alerts.py` and `OVERWATCH_ALERT_RULES` | Controls alert category, severity, SLA, owner route, and delivery packaging. |
| Cost rates | `.overwatch_final/config.py` and `OVERWATCH_SETTINGS` | Keeps dollarized metrics aligned across sections. |
| Regression expectations | `tests/` | Prevents formula, navigation, role, and setup regressions. |

If a value exists in both app config and setup SQL, update both in the same
change.

For an existing deployment, run `snowflake/OVERWATCH_RELEASE_REMEDIATION.sql`
after reviewing the setup SQL diff when the release notes call for a
remediation pass.

## Current Company Scope

### Trexis Warehouses

Only these warehouses are Trexis:

| Warehouse | Company |
|---|---|
| `WH_TRXS_LOAD` | Trexis |
| `WH_TRXS_QUERY` | Trexis |
| `WH_TRXS_TRANSFORM` | Trexis |
| `WH_TRXS_UNLOAD` | Trexis |

### ALFA Warehouses

All other listed account warehouses are ALFA unless a future explicit scope row
assigns them elsewhere. Current static ALFA options include:

| Warehouse |
|---|
| `BLCOMPUTE_WH` |
| `COMPUTE_WH` |
| `CROWDSTRIKE_WH` |
| `DOC_ALWH` |
| `POSIT_WORKBENCH` |
| `SNOWFLAKE_LEARNING_WH` |
| `SYSTEM$STREAMLIT_NOTEBOOK_WH` |
| `WH_ALFA_ANALYTICS` |
| `WH_ALFA_LOAD` |
| `WH_ALFA_QA` |
| `WH_ALFA_QUERY` |
| `WH_ALFA_TRANSFORM` |
| `WH_ALFA_UNLOAD` |

`OVERWATCH_WH` is the app runtime warehouse. It is monitored as OVERWATCH
platform cost, not as an ALFA or Trexis business workload warehouse.

`COMPUTE_WH` currently runs the OVERWATCH mart task graph. Keep its task cost
visible and separate from business workload recommendations.

## Current Database And Environment Scope

### Trexis

| Database | Rollup |
|---|---|
| `TRXS_ABC_METADATA_PRD` | PROD |
| `TRXS_EDW_PRD` | PROD |
| `TRXS_GW_DATA_PRD` | PROD |
| `TRXS_ABC_METADATA_DEV` | DEV_ALL |
| `TRXS_ABC_METADATA_SIT` | DEV_ALL |
| `TRXS_EDW_DEV` | DEV_ALL |
| `TRXS_EDW_SIT` | DEV_ALL |
| `TRXS_GW_DATA_DEV` | DEV_ALL |
| `TRXS_GW_DATA_SIT` | DEV_ALL |

### ALFA

| Database | Rollup |
|---|---|
| `ALFA_EDW_PROD` | PROD |
| `ALFA_EDW_MGM` | PROD |
| `ALFA_EDW_DEV` | DEV_ALL |
| `ALFA_EDW_SAN` | DEV_ALL |
| `ALFA_EDW_PHX` | DEV_ALL |
| `ALFA_EDW_SEA` | DEV_ALL |
| `ALFA_EDW_SIT` | DEV_ALL |

Rows without reliable database context must remain `No Database Context`.
Do not silently recode them into ALFA production or development.

## Role And Experience View Inputs

The experience views are configured in `.overwatch_final/config.py`.

| View | Intended use |
|---|---|
| DBA | Full DBA/admin control with guarded execution and audit proof. |
| Manager | DSA-style manager view with broad health, cost, governance, and queue evidence. |
| Analyst | DTI-style analyst view with Workload Operations and supporting analysis. |
| Executive | Leadership view with limited high-level evidence. |

When changing role access, update:

1. `ROLE_SECTIONS`
2. role detection or role-to-experience mapping
3. navigation tests
4. admin-control tests when DBA-only behavior changes

## Cost Defaults

| Value | Current default | Used for |
|---|---:|---|
| Compute credit price | `$3.68` | Warehouse compute/spend/savings estimates. |
| Cortex AI credit price | `$2.20` | Cortex AI spend estimates. |
| Storage cost per TB | `$23.00` | Storage estimates where exact billed dollars are unavailable. |

Formula rules:

- Total warehouse credits come from `CREDITS_USED`.
- Compute warehouse credits prefer `CREDITS_USED_COMPUTE`.
- Cortex AI cost uses the configured Cortex rate.
- Official service/billed credits come from `METERING_DAILY_HISTORY`.
- Currency reconciliation uses organization billing views only when visible.

## Durable Snowflake Objects

Core setup objects:

| Object | Type | Purpose |
|---|---|---|
| `OVERWATCH_WH` | Warehouse | Dedicated Streamlit app runtime. |
| `OVERWATCH_WH_RM` | Resource monitor | Runtime warehouse guardrail. |
| `OVERWATCH_SETTINGS` | Table | Durable settings and rates. |
| `OVERWATCH_COMPANY_SCOPE` | Table | Company warehouse/database scope. |
| `OVERWATCH_OWNER_DIRECTORY` | Table | Owner and approval routing. |
| `OVERWATCH_ACTION_QUEUE` | Table | Open DBA work and verification status. |
| `OVERWATCH_ALERTS` | Table | Alert history and delivery state. |
| `OVERWATCH_ADMIN_ACTION_AUDIT` | Table | Admin action evidence. |
| `OVERWATCH_WORKLOAD_RECOVERY_AUDIT` | Table | Recovery and savings proof. |
| `OVERWATCH_EXECUTIVE_PACKET` | Table | Executive packet history. |
| `OVERWATCH_EXTERNAL_CONTROL_FEED` | Table | Terraform, Jira, Flyway, Git, and Control-M style evidence. |
| `OVERWATCH_AUTOMATION_RUN` | Table | No-touch automation run ledger. |

Core task graph:

| Task | Warehouse | Purpose |
|---|---|---|
| `OVERWATCH_LOAD_HOURLY` | `COMPUTE_WH` | Refresh hourly marts. |
| `OVERWATCH_LOAD_CORTEX` | `COMPUTE_WH` | Refresh Cortex spend facts. |
| `OVERWATCH_REFRESH_CONTROL_ROOM` | `COMPUTE_WH` | Refresh control-room summaries. |
| `OVERWATCH_COST_GOVERNANCE_REFRESH` | `COMPUTE_WH` | Refresh cost governance signals. |
| `OVERWATCH_AUTOMATION_REFRESH` | `COMPUTE_WH` | Refresh automation, executive packet, and external-feed evidence. |
| `OVERWATCH_ANOMALY_CHECK` | `COMPUTE_WH` | Seed anomaly alerts. |
| `OVERWATCH_COST_SAVINGS_VERIFY` | `COMPUTE_WH` | Verify post-action cost savings. |
| `OVERWATCH_LOAD_DAILY` | `COMPUTE_WH` | Refresh daily facts. |

## Adding A Warehouse

1. Decide the company.
2. If it is Trexis, add it explicitly to the Trexis warehouse list in config and
   setup SQL.
3. If it is ALFA, confirm it should be covered by the ALFA catch-all behavior or
   add an explicit ALFA scope row for clarity.
4. Add owner routing in `OVERWATCH_OWNER_DIRECTORY`.
5. Add or update an architecture objective if the warehouse has a special
   workload class, approval path, or recovery expectation.
6. Add regression coverage if the scope change affects filtering or cost
   attribution.

## Adding A Database Or Environment

1. Add the database to the company database list in config.
2. Add matching rows to `OVERWATCH_COMPANY_SCOPE`.
3. Update the environment classifier in setup SQL.
4. Add owner routing for the database.
5. Update schema-compare metadata if the database should appear in dependent
   schema dropdowns.
6. Add tests for production/development rollup and company filter behavior.

## Adding An Integration Feed

Use `OVERWATCH_EXTERNAL_CONTROL_FEED` unless a dedicated evidence table is
needed.

Recommended fields:

- `SOURCE_SYSTEM`: `TERRAFORM`, `JIRA`, `FLYWAY`, `GIT`, `CONTROL_M`, or other
  approved system.
- `ENTITY_TYPE`: warehouse, database, schema, task, procedure, role, user, or
  account.
- `ENTITY_NAME`: exact target when known.
- `STATUS`: open, closed, approved, failed, passed, drifted, or similar.
- `OWNER`: accountable owner.
- `TICKET_ID` or external identifier.
- `EVIDENCE_URL`: link to approved source when available.
- `RAW_PAYLOAD`: compact JSON evidence for audit review.

## Adding Admin Controls

Do not add a state-changing button unless it has:

1. current-state proof
2. changed-only SQL
3. owner or approval route
4. typed confirmation or equivalent guardrail
5. rollback SQL
6. audit write
7. failure-path audit write
8. verification query
9. action queue closure rule

## Release Maintenance

When changing manual inputs:

1. Update config.
2. Update setup SQL.
3. Update documentation.
4. Update tests.
5. Run focused tests and the full suite.
6. Run section smoke if app behavior changed.
7. Do not commit or push until explicitly instructed.
