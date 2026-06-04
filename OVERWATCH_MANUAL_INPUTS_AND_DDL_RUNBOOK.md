# OVERWATCH Manual Inputs and DDL Runbook

Last updated: June 1, 2026

This document is the maintenance map for every manual input that drives
OVERWATCH. Use it when adding or changing warehouses, databases, environments,
roles, costs, alert recipients, owners, or Snowflake DDL.

## Source Of Truth

| Input area | Primary file or object | Purpose |
|---|---|---|
| App defaults, thresholds, company scope, environment selector, role navigation | `.overwatch_final/config.py` | Runtime defaults used by Streamlit before or alongside mart settings. |
| Durable Snowflake setup, settings, seed rows, marts, tasks, procedures | `snowflake/OVERWATCH_MART_SETUP.sql` | Snowflake database/schema, state tables, facts, procedures, task graph, alert objects. |
| Owner and on-call routing defaults | `.overwatch_final/utils/owner_directory.py` and `OVERWATCH_OWNER_DIRECTORY` | Routes warehouse, database, architecture, task, procedure, cost, alert, security, change, and account-health work. |
| Architecture objectives | `.overwatch_final/config.py` under `ARCHITECTURE_OBJECTIVES` | Manual workload class, owner, RPO/RTO, isolation, cache, clustering, and DR expectations for Architecture Readiness. |
| Forward platform controls | `.overwatch_final/config.py` under `FORWARD_PLATFORM_CONTROLS` | Manual DBA guardrails for Adaptive Compute, Cortex Agents, MCP servers, AI usage, Openflow, Horizon, semantic trust, BCDR drill ledger, and AI-assisted change governance. |
| Alert rules and email delivery helpers | `.overwatch_final/utils/alerts.py` and `OVERWATCH_ALERT_RULES` | Alert categories, severities, SLA hours, delivery status, email package generation. |
| Deployment and baseline grants | `OVERWATCH_DOCUMENTATION.md`, `STREAMLIT_CLOUD_DEPLOY.md` | App runtime access grants and deployment notes. |
| Score expectations and target gaps | `.overwatch_final/utils/scorecards.py` | Manual section readiness scoring and next-move language. |

Treat `config.py` plus `OVERWATCH_MART_SETUP.sql` as a pair. If a manual value
exists in both, update both in the same change.

## Current Manual Values

### Companies

Defined in `.overwatch_final/config.py` under `COMPANY_CONFIG`.

| Company | Warehouse scope | Database scope | Exclusions | Notes |
|---|---|---|---|---|
| `ALFA` | `WH_ALFA_%`, `BI_COMPUTE_WH`, `COMPUTE_WH`, `CROWDSTRIKE_WH`, `DOC_AI_WH`, `POSIT_WORKBENCH`, `SNOWFLAKE_LEARNING_WH`, `SYSTEM$STREAMLIT%` | `ADMIN`, `ALFA%` | Excludes `WH_TRXS_%`, `TRXS_%` databases, `TRXS_%` users | Default company. |
| `Trexis` | `WH_TRXS_%` | `TRXS_%` | None | Trexis-specific scope. |
| `ALL` | No filter | No filter | None | Account-wide view. |

Durable Snowflake scope rows are seeded in `OVERWATCH_COMPANY_SCOPE` inside
`snowflake/OVERWATCH_MART_SETUP.sql`.

### ALFA Environments

Defined in `.overwatch_final/config.py` under `ENVIRONMENT_CONFIG` and mirrored
in `OVERWATCH_DATABASE_ENVIRONMENT()` in `snowflake/OVERWATCH_MART_SETUP.sql`.

| Selector value | Database pattern | Rollup |
|---|---|---|
| `ALL` | No filter | All database contexts. |
| `PROD` | `ALFA_EDW_PROD` | ALFA PROD. |
| `DEV_ALL` | `ALFA_EDW_DEV`, `ALFA_EDW_SAN`, `ALFA_EDW_PHX`, `ALFA_EDW_SEA`, `ALFA_EDW_SIT` | ALFA DEV/Sandbox family. |
| `ALFA_EDW_DEV` | `ALFA_EDW_DEV` | Individual DEV view. |
| `ALFA_EDW_SAN` | `ALFA_EDW_SAN` | Individual DEV/Sandbox view. |
| `ALFA_EDW_PHX` | `ALFA_EDW_PHX` | Individual DEV/Sandbox view. |
| `ALFA_EDW_SEA` | `ALFA_EDW_SEA` | Individual DEV/Sandbox view. |
| `ALFA_EDW_SIT` | `ALFA_EDW_SIT` | Individual DEV/Sandbox view. |

Login-only data with no database context must not be forced into PROD or DEV.
Use `No Database Context` for account-level login, security, or warehouse rows
where Snowflake does not provide a reliable database signal.

### Architecture Objectives

Defined in `.overwatch_final/config.py` under `ARCHITECTURE_OBJECTIVES`.
These rows are manual control objectives. They tell Architecture Readiness what
the intended workload class, owner route, RPO/RTO, isolation policy, cache
policy, clustering guardrail, and DR expectation should be before DBAs act on
Snowflake telemetry.

| Scope | Current objective |
|---|---|
| `ALFA_EDW_PROD` database | Tier 0 production EDW, PROD environment, 120 minute RPO, 240 minute RTO, owner-approved PROD routing required. |
| `ALFA_EDW_DEV`, `ALFA_EDW_SAN`, `ALFA_EDW_PHX`, `ALFA_EDW_SEA` databases | Tier 2 DEV/Sandbox EDW, DEV_ALL environment, restore/clone posture unless a stricter owner objective is documented. |
| `ALFA_EDW_SIT` database | Tier 1 SIT EDW, DEV_ALL environment, release-test recovery expectations should be documented. |
| `OVERWATCH_WH` warehouse | Dedicated OVERWATCH Streamlit app execution warehouse. Setup assigns `OVERWATCH_WH_RM`; monitor its cost separately from ALFA/Trexis business workload warehouses. |
| `COMPUTE_WH` warehouse | Current OVERWATCH mart task and utility warehouse. Monitor its cost separately from ALFA/Trexis business workload warehouses. |
| `BI_COMPUTE_WH` warehouse | BI/reporting compute where repeated dashboard workloads may justify warm-cache tuning. |
| `WH_ALFA_%` warehouses | ALFA application workload compute; routing and settings should have application owner approval. |
| `WH_TRXS_%` warehouses | Trexis workload compute; keep Trexis isolation separate from ALFA unless approved. |

When adding a new database family or warehouse class, add an
`ARCHITECTURE_OBJECTIVES` row and, if it needs a specific owner route, add a
matching `OVERWATCH_OWNER_DIRECTORY` row. Architecture findings should not be
closed until the objective, owner, approval group, verification query, and
RPO/RTO or recovery expectation are visible.

### Forward Platform Controls

Defined in `.overwatch_final/config.py` under `FORWARD_PLATFORM_CONTROLS`.
These rows tell Architecture Readiness how to govern newly adopted Snowflake
capabilities before they become operational blind spots.

| Control area | Current owner route | Primary evidence |
|---|---|---|
| Adaptive Compute Readiness | `ADAPTIVE_COMPUTE_DEFAULT` / DBA-FinOps route | `SHOW WAREHOUSES`, `QUERY_HISTORY`, `WAREHOUSE_METERING_HISTORY`. |
| Agent & MCP Governance | `AI_AGENT_DEFAULT`, `MCP_SERVER_DEFAULT` | `SHOW AGENTS IN ACCOUNT`, `SHOW MCP SERVERS IN ACCOUNT`. |
| AI Spend & Token Guardrails | `AI_COST_DEFAULT` / FinOps route | `CORTEX_AGENT_USAGE_HISTORY`, `SNOWFLAKE_INTELLIGENCE_USAGE_HISTORY`. |
| AI Security Guardrails | `AI_SECURITY_DEFAULT` / security route | `AI_SETTINGS`, `CORTEX_ENABLED_CROSS_REGION`, `SHOW GRANTS TO ROLE PUBLIC`, Cortex database-role grants, `SNOWFLAKE.DATA_SECURITY` report visibility. |
| Openflow Operations | `OPENFLOW_DEFAULT` | `OPENFLOW_USAGE_HISTORY`. |
| Horizon Governance Readiness | `HORIZON_GOVERNANCE_DEFAULT` / governance route | Classification, policy, access-history, object-dependency, Trust Center, and data-quality views. |
| Semantic Trust & Verified Query Testing | `SEMANTIC_TRUST_DEFAULT` | `SEMANTIC_VIEWS`, `SEMANTIC_TABLES`, `SEMANTIC_METRICS`. |
| BCDR Drill Ledger | `BCDR_DRILL_DEFAULT` | Failover/replication inventory, replication usage, backup operation history, and drill notes. |
| AI Change Governance | `AI_CHANGE_GOVERNANCE_DEFAULT` | Cortex Code, Cortex AISQL, ticket/source-control, rollback, and verification evidence. |

When adding a new Snowflake platform capability, add a
`FORWARD_PLATFORM_CONTROLS` row, add or update the matching
`OVERWATCH_OWNER_DIRECTORY` seed/default route, and decide whether the app
should load live evidence through a button, a mart fact, or manual checklist
evidence. Do not add automatic state-changing behavior until owner approval,
rollback, and verification evidence are durable.

Durable platform-futures objects are included in
`snowflake/OVERWATCH_MART_SETUP.sql` and the setup bundle:

| Object | Purpose |
|---|---|
| `OVERWATCH_PLATFORM_FUTURES_CONTROL_REGISTER` | Durable copy of the manual forward-platform control register. |
| `OVERWATCH_PLATFORM_FUTURES_EVIDENCE` | Immutable evidence ledger for Adaptive Compute/AI/MCP/AI-security/Openflow/Horizon/Semantic/BCDR/AI-change reviews. |
| `OVERWATCH_PLATFORM_FUTURES_EVIDENCE_LATEST_V` | Latest evidence row per control/entity/surface. |
| `OVERWATCH_PLATFORM_FUTURES_CONTROL_COVERAGE_V` | Control coverage state: evidence missing, proof needed, action open, or captured. |

### Cost Defaults

| Value | Current default | App location | Snowflake location |
|---|---:|---|---|
| Contract credit price | `3.68` | `DEFAULTS["credit_price"]` | `OVERWATCH_SETTINGS.CREDIT_PRICE_USD` |
| Cortex AI credit price | `2.20` | `DEFAULTS["ai_credit_price"]` | `OVERWATCH_SETTINGS.AI_CREDIT_PRICE_USD` |
| Storage cost per TB | `23.00` | `DEFAULTS["storage_cost_per_tb"]`, `THRESHOLDS["storage_cost_per_tb"]` | Used by app calculations; not currently a seeded `OVERWATCH_SETTINGS` row. |

The `3.68` compute credit rate is the ALFA contract estimate used for
OVERWATCH dollarized warehouse metrics. Snowflake-official reconciliation is
kept separate: Account Overview-style warehouse credits use
`SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY`, billed warehouse credits
use `SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY.CREDITS_BILLED`, and
official currency spend uses
`SNOWFLAKE.ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY` when the active role has
organization billing access.
Cost & Contract also compares the configured ALFA rate to
`SNOWFLAKE.ORGANIZATION_USAGE.RATE_SHEET_DAILY` when the role can access the
organization rate sheet. `FACT_COST_DAILY` stores account-level daily billed
credits by Snowflake service type from
`SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY` so the dashboard can split
warehouse, AI/Cortex, serverless, storage, and network spend without rescanning
the official history view on every render.

Database-attributed cost split is allocated/estimated unless the source is exact
Snowflake metering. Shared warehouse metering cannot be split exactly by PROD
and DEV without query attribution, tags, or session lineage.

### Alert Email And Delivery

| Value | Current default | Locations |
|---|---|---|
| Default recipients | `dba-alerts@yourcompany.com` | Public-repo placeholder in `config.DEFAULT_ALERT_EMAIL`; replace in Settings or deployment config before enabling alert delivery. |
| Delivery method | `EMAIL` | `config.ALERT_DELIVERY_METHOD`, `OVERWATCH_SETTINGS.ALERT_DELIVERY_METHOD`, alert rows. |
| Notification integration name | `OVERWATCH_EMAIL_INT` | `OVERWATCH_SETTINGS.ALERT_EMAIL_NOTIFICATION_INTEGRATION`, `SP_OVERWATCH_SEND_ALERT_DIGEST`, alert helpers. |

Teams/webhook support is future-facing. The active framework is email-first.
Until the Snowflake email notification integration is approved and configured,
the delivery procedure supports dry-run packaging.

### App Persistence Objects

| Value | Current default | Location |
|---|---|---|
| App database | `DBA_MAINT_DB` | `config.ALERT_DB`, setup SQL |
| App schema | `OVERWATCH` | `config.ALERT_SCHEMA`, setup SQL |
| Alert table | `OVERWATCH_ALERTS` | `config.ALERT_TABLE`, setup SQL |
| Action queue table | `OVERWATCH_ACTION_QUEUE` | `config.ACTION_QUEUE_TABLE`, setup SQL |
| ETL audit table | `ETL_RUN_AUDIT` | `config.ETL_AUDIT_TABLE` |
| Dedicated app runtime warehouse created by setup | `OVERWATCH_WH` | setup SQL, `.overwatch_final/snowflake.yml` |
| Dedicated app runtime resource monitor | `OVERWATCH_WH_RM` | setup SQL |
| Current main load/anomaly task warehouse | `COMPUTE_WH` | setup SQL task definitions |
| Current cost-savings verifier task warehouse | `COMPUTE_WH` | setup SQL task definitions |

Task warehouses are app execution inputs, not monitoring scope inputs. Today
the Streamlit app runs on `OVERWATCH_WH`; the main load, anomaly, and
cost-savings verifier tasks continue to run on `COMPUTE_WH`. OVERWATCH still
monitors ALFA and Trexis warehouses through `COMPANY_CONFIG`,
`OVERWATCH_COMPANY_SCOPE`, `WAREHOUSE_METERING_HISTORY`, `QUERY_HISTORY`, task
history, and the mart facts. If the app execution warehouse changes later,
update the Streamlit manifest, monitoring-cost logic, documentation, and
warehouse regression tests in the same release. If mart task warehouses change,
update the setup SQL task clauses and task-warehouse regression test in the
same release. Do not add monitored warehouses by changing runtime warehouses.

## Adding A Warehouse

Use this checklist when a new warehouse should appear in OVERWATCH scope,
ownership, cost controls, or admin actions.

Adding a monitored warehouse is separate from changing the warehouses that run
the app or mart tasks. `OVERWATCH_WH` is the current Streamlit app execution
warehouse. `COMPUTE_WH` is the current execution warehouse for the main
OVERWATCH load/anomaly task graph. The
monitored warehouse list is driven by company scope, Snowflake account-usage
history, and mart facts.

1. Decide the owning company.
   - ALFA warehouse names should either match an existing ALFA pattern or be
     added explicitly to `COMPANY_CONFIG["ALFA"]["wh_patterns"]`.
   - Trexis warehouse names should match `WH_TRXS_%` or a new Trexis pattern.
2. Update app scope in `.overwatch_final/config.py`.
   - Add the pattern to `wh_patterns`.
   - Add an exclusion to the other company if the name could overlap.
3. Update durable scope in `snowflake/OVERWATCH_MART_SETUP.sql`.
   - Add or merge a row in `OVERWATCH_COMPANY_SCOPE` with
     `SCOPE_TYPE = 'WAREHOUSE'`.
   - Use `ILIKE` for include patterns and `NOT_ILIKE` for exclusions.
4. Add owner routing if needed.
   - Add a specific `OVERWATCH_OWNER_DIRECTORY` row with
     `ENTITY_TYPE = 'WAREHOUSE'` and `ENTITY_PATTERN` matching the warehouse.
   - Set `OWNER_EMAIL`, `ONCALL_PRIMARY`, `APPROVAL_GROUP`,
     `ESCALATION_TARGET`, `DEFAULT_ROUTE`, `SERVICE_TIER`, and
     `MATCH_PRIORITY`.
5. Add or update an architecture objective.
   - Add an `ARCHITECTURE_OBJECTIVES` row with `ENTITY_TYPE = 'WAREHOUSE'`.
   - Set the workload class, service tier, owner, approval group, isolation
     policy, cache policy, and recovery expectation for Architecture Readiness.
6. Add or validate Snowflake tags if you want stronger chargeback.
   - Preferred tag names are seeded in `OVERWATCH_OWNER_TAG_NAMES`:
     `COST_OWNER`, `DATA_OWNER`, `APP_OWNER`, `APPLICATION_OWNER`,
     `BUSINESS_OWNER`, `SERVICE_OWNER`.
7. Validate app-role privileges for admin controls.
   - Read-only dashboard use needs account usage visibility and mart table DML.
   - Warehouse changes need a role with the required Snowflake privileges for
     the target warehouse, such as monitor/operate/modify or ownership through
     your approved role model.
8. Update tests if the new pattern changes expected scoping.
   - Start with `tests/test_company_scope_and_cost.py`.

Example durable scope row:

```sql
INSERT INTO DBA_MAINT_DB.OVERWATCH.OVERWATCH_COMPANY_SCOPE
  (COMPANY, SCOPE_TYPE, SCOPE_PATTERN, MATCH_MODE, ENVIRONMENT, NOTES)
VALUES
  ('ALFA', 'WAREHOUSE', 'WH_ALFA_NEW_%', 'ILIKE', NULL, 'New ALFA warehouse family.');
```

## Adding A Database Or Environment

Use this checklist when adding a new database, ALFA DEV member, company
database family, or environment selector.

1. Update app selector values in `.overwatch_final/config.py`.
   - Add an `ENVIRONMENT_CONFIG` entry for individual views.
   - If it belongs in the ALFA DEV rollup, add the database to
     `ENVIRONMENT_CONFIG["DEV_ALL"]["db_patterns"]`.
2. Update company database scope in `.overwatch_final/config.py`.
   - Add the database pattern to the owning company's `db_patterns`.
   - Add an `exclude_db_pattern` or exclusion if another company could match it.
3. Update durable scope in `snowflake/OVERWATCH_MART_SETUP.sql`.
   - Add rows to `OVERWATCH_COMPANY_SCOPE` for the company and database.
   - Use `ENVIRONMENT` for explicit ALFA PROD/DEV selector mapping.
4. Update `OVERWATCH_DATABASE_ENVIRONMENT()`.
   - Add exact matches before broad `ILIKE` patterns.
   - Keep `DATABASE_NAME IS NULL` returning `No Database Context`.
5. Update cost rollups and alert filters.
   - Update the DEV list in chargeback rollup logic.
   - Update the `DEV_ALL` list in `SP_OVERWATCH_SEND_ALERT_DIGEST`.
6. Add owner routing if needed.
   - Use `ENTITY_TYPE = 'DATABASE'`, `SCHEMA`, `TABLE`, `TASK`,
     `PROCEDURE`, or a workflow type depending on the object.
7. Add or update an architecture objective.
   - Add an `ARCHITECTURE_OBJECTIVES` row for the database or database family.
   - Set `EXPECTED_ENVIRONMENT`, `WORKLOAD_CLASS`, `SERVICE_TIER`,
     `OWNER`, `APPROVAL_GROUP`, `RPO_MINUTES`, `RTO_MINUTES`,
     `ISOLATION_POLICY`, `CACHE_POLICY`, `CLUSTERING_POLICY`, and
     `DR_POLICY`.
8. Validate environment behavior.
   - Company selector and environment selector should apply anywhere database
     context exists.
   - Do not apply environment filters to login-only data with no database
     context.

Example for adding `ALFA_EDW_QA` as a DEV family database:

```python
# .overwatch_final/config.py
ENVIRONMENT_CONFIG["DEV_ALL"]["db_patterns"].append("ALFA_EDW_QA")
ENVIRONMENT_CONFIG["ALFA_EDW_QA"] = {
    "label": "ALFA_EDW_QA",
    "db_patterns": ["ALFA_EDW_QA"],
}
```

```sql
-- snowflake/OVERWATCH_MART_SETUP.sql
WHEN UPPER(DATABASE_NAME) = 'ALFA_EDW_QA' THEN 'ALFA_EDW_QA'
```

Also add the same database to:

- `OVERWATCH_COMPANY_SCOPE` seed rows
- chargeback `DEV_ALL` rollup list
- alert digest `DEV_ALL` filter list
- environment regression tests

## Adding A Company

Adding a company is larger than adding a database because it changes every
scope path.

1. Add a new `COMPANY_CONFIG` entry in `.overwatch_final/config.py`.
   - Include warehouse patterns, warehouse exclusions, database patterns,
     database exclusions, user patterns, user exclusions, label, and color.
2. Add rows to `OVERWATCH_COMPANY_SCOPE` in setup SQL.
3. Decide whether the company needs its own environment selector values.
4. Update owner-directory seed rows for company-specific owners if defaults are
   too generic.
5. Update tests that assert ALFA/Trexis behavior.
6. Review all dashboards that show company rollups so labels remain accurate.

## Adding Roles Or App Permissions

There are two different role concepts:

- App navigation profile in `ROLE_SECTIONS`
- Snowflake RBAC privileges used by the running role

`ROLE_SECTIONS` only controls which pages are visible in the UI. It is not a
security boundary. Snowflake RBAC is the real enforcement layer.

### App Navigation Roles

`ROLE_SECTIONS` lives in `.overwatch_final/config.py`. The app checks the
current Snowflake role name and picks the first profile key contained in that
role name. Current profile keys are:

- `ANALYST`
- `MANAGER`
- `REPORT`
- `DBA`
- `SYSADMIN`
- `ACCOUNTADMIN`

If you add a new profile:

1. Add the profile to `ROLE_SECTIONS`.
2. Put more specific role-name keys before broad keys if substring overlap is
   possible.
3. Add navigation integrity tests in `tests/test_navigation_integrity.py`.

### Baseline Runtime Grants

Use the deployed app role in place of `<role>`.

```sql
GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE <role>;
GRANT MONITOR ON ACCOUNT TO ROLE <role>;
GRANT USAGE ON WAREHOUSE OVERWATCH_WH TO ROLE <role>;
GRANT USAGE ON DATABASE DBA_MAINT_DB TO ROLE <role>;
GRANT USAGE ON SCHEMA DBA_MAINT_DB.OVERWATCH TO ROLE <role>;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA DBA_MAINT_DB.OVERWATCH TO ROLE <role>;
GRANT SELECT, INSERT, UPDATE, DELETE ON FUTURE TABLES IN SCHEMA DBA_MAINT_DB.OVERWATCH TO ROLE <role>;
```

### Elevated DBA Controls

Grant only through your approved production role model. The dashboard can
prepare SQL and record evidence, but Snowflake should enforce execution rights.

| Control area | Typical privilege need |
|---|---|
| Warehouse setting changes | Monitor/operate/modify or ownership on target warehouses. |
| Warehouse suspend/resume | Operate or ownership on target warehouses. |
| Task suspend/resume/retry | Operate/monitor or ownership on target tasks. |
| Role grants/revokes | `MANAGE GRANTS` or ownership/delegated grant path. |
| Query cancel/kill | Sufficient ownership/operator rights for the running query or warehouse. |
| Email delivery | Approved Snowflake email notification integration usable by the procedure owner/caller role. |
| Mart setup | Create database/schema/warehouse/task/procedure plus account usage visibility. |

## Changing Cost Inputs

Update both runtime defaults and Snowflake settings.

1. Update `.overwatch_final/config.py`.
   - `DEFAULTS["credit_price"]`
   - `DEFAULTS["ai_credit_price"]`
   - `DEFAULTS["storage_cost_per_tb"]`
   - any related `THRESHOLDS` values
2. Update `snowflake/OVERWATCH_MART_SETUP.sql`.
   - `OVERWATCH_SETTINGS.CREDIT_PRICE_USD`
   - `OVERWATCH_SETTINGS.AI_CREDIT_PRICE_USD`
   - add a durable storage setting if storage cost should become database-driven
3. Update tests that assert the configured values.
4. Rerun setup or update `OVERWATCH_SETTINGS` directly in Snowflake.

Direct Snowflake setting update:

```sql
MERGE INTO DBA_MAINT_DB.OVERWATCH.OVERWATCH_SETTINGS tgt
USING (
  SELECT 'CREDIT_PRICE_USD' AS SETTING_NAME, '3.68' AS SETTING_VALUE,
         'NUMBER' AS SETTING_TYPE, 'Contract credit price used for estimated cost display.' AS DESCRIPTION
) src
ON tgt.SETTING_NAME = src.SETTING_NAME
WHEN MATCHED THEN UPDATE SET
  SETTING_VALUE = src.SETTING_VALUE,
  SETTING_TYPE = src.SETTING_TYPE,
  DESCRIPTION = src.DESCRIPTION,
  UPDATED_AT = CURRENT_TIMESTAMP(),
  UPDATED_BY = CURRENT_USER()
WHEN NOT MATCHED THEN INSERT (SETTING_NAME, SETTING_VALUE, SETTING_TYPE, DESCRIPTION)
VALUES (src.SETTING_NAME, src.SETTING_VALUE, src.SETTING_TYPE, src.DESCRIPTION);
```

## Changing Emails, Owners, And Escalation Routes

Use the owner directory for routing. Use alert settings for delivery.

### Default Alert Recipient

Update all of these together:

- `.overwatch_final/config.py`: `DEFAULT_ALERT_EMAIL`
- `snowflake/OVERWATCH_MART_SETUP.sql`: `OVERWATCH_SETTINGS.DEFAULT_ALERT_EMAIL`
- `snowflake/OVERWATCH_MART_SETUP.sql`: `SP_OVERWATCH_SEND_ALERT_DIGEST` default `P_RECIPIENT`
- `snowflake/OVERWATCH_MART_SETUP.sql`: hardcoded fallback in `OVERWATCH_ANOMALY_CHECK`
- `.overwatch_final/utils/owner_directory.py`: defaults use `DEFAULT_ALERT_EMAIL`
- tests that assert the placeholder email

### Owner Directory Row

Preferred durable table:

```sql
MERGE INTO DBA_MAINT_DB.OVERWATCH.OVERWATCH_OWNER_DIRECTORY tgt
USING (
  SELECT
    'WH_ALFA_BI_OWNER' AS OWNER_KEY,
    'WAREHOUSE' AS ENTITY_TYPE,
    'BI_COMPUTE_WH' AS ENTITY_PATTERN,
    'BI Product Owner' AS OWNER_NAME,
    'bi-owner@example.com' AS OWNER_EMAIL,
    'DBA On-Call' AS ONCALL_PRIMARY,
    'BI Backup' AS ONCALL_SECONDARY,
    'BI Platform Approver' AS APPROVAL_GROUP,
    'DBA Lead' AS ESCALATION_TARGET,
    'Warehouse Health' AS DEFAULT_ROUTE,
    'Tier 1' AS SERVICE_TIER,
    150 AS MATCH_PRIORITY,
    TRUE AS IS_ACTIVE,
    'Specific route for BI warehouse pressure and setting changes.' AS NOTES
) src
ON UPPER(tgt.OWNER_KEY) = UPPER(src.OWNER_KEY)
WHEN MATCHED THEN UPDATE SET
  ENTITY_TYPE = src.ENTITY_TYPE,
  ENTITY_PATTERN = src.ENTITY_PATTERN,
  OWNER_NAME = src.OWNER_NAME,
  OWNER_EMAIL = src.OWNER_EMAIL,
  ONCALL_PRIMARY = src.ONCALL_PRIMARY,
  ONCALL_SECONDARY = src.ONCALL_SECONDARY,
  APPROVAL_GROUP = src.APPROVAL_GROUP,
  ESCALATION_TARGET = src.ESCALATION_TARGET,
  DEFAULT_ROUTE = src.DEFAULT_ROUTE,
  SERVICE_TIER = src.SERVICE_TIER,
  MATCH_PRIORITY = src.MATCH_PRIORITY,
  IS_ACTIVE = src.IS_ACTIVE,
  NOTES = src.NOTES
WHEN NOT MATCHED THEN INSERT (
  OWNER_KEY, ENTITY_TYPE, ENTITY_PATTERN, OWNER_NAME, OWNER_EMAIL,
  ONCALL_PRIMARY, ONCALL_SECONDARY, APPROVAL_GROUP, ESCALATION_TARGET,
  DEFAULT_ROUTE, SERVICE_TIER, MATCH_PRIORITY, IS_ACTIVE, NOTES
) VALUES (
  src.OWNER_KEY, src.ENTITY_TYPE, src.ENTITY_PATTERN, src.OWNER_NAME,
  src.OWNER_EMAIL, src.ONCALL_PRIMARY, src.ONCALL_SECONDARY,
  src.APPROVAL_GROUP, src.ESCALATION_TARGET, src.DEFAULT_ROUTE,
  src.SERVICE_TIER, src.MATCH_PRIORITY, src.IS_ACTIVE, src.NOTES
);
```

If you want the row to survive a full re-run of setup SQL with seeded defaults,
also add it to the seed block in `snowflake/OVERWATCH_MART_SETUP.sql`.

## Changing Alert Rules

Current built-in rule families:

- `COST_CREDIT_SPIKE`
- `COST_SAVINGS_VERIFIER_FAILURE`
- `QUERY_HIGH_ERROR_RATE`
- `TASK_FAILURE`
- `PROCEDURE_FAILURE_OR_SPIKE`
- `WAREHOUSE_PRESSURE`
- `GRANT_REVOKE_ACTIVITY`
- `WAREHOUSE_SETTING_CHANGE`

To add or change a rule:

1. Update `.overwatch_final/utils/alerts.py` in `DEFAULT_ALERT_RULES`.
2. Update the `OVERWATCH_ALERT_RULES` seed in `snowflake/OVERWATCH_MART_SETUP.sql`.
3. If the rule requires new detection SQL, update `OVERWATCH_ANOMALY_CHECK`.
4. If it needs a new owner class, add an owner-directory route.
5. Add or update alert tests in `tests/test_formula_regressions.py`.

## DDL Inventory

All production DDL currently lives in `snowflake/OVERWATCH_MART_SETUP.sql`.
Alert Center setup objects are part of that bundle; the app no longer exposes a
separate in-interface setup SQL pane.

### Runtime Objects

- Database: `DBA_MAINT_DB`
- Schema: `DBA_MAINT_DB.OVERWATCH`
- Warehouse: `OVERWATCH_WH` (dedicated Streamlit app runtime; mart tasks currently remain on `COMPUTE_WH`)

### Permanent Configuration, Audit, And Workflow Tables

- `OVERWATCH_SETTINGS`
- `OVERWATCH_COMPANY_SCOPE`
- `OVERWATCH_OWNER_TAG_NAMES`
- `OVERWATCH_OWNER_DIRECTORY`
- `OVERWATCH_LOAD_AUDIT`
- `OVERWATCH_ADMIN_ACTION_AUDIT`
- `OVERWATCH_USAGE_LOG`
- `OVERWATCH_ACTION_QUEUE`
- `OVERWATCH_WORKLOAD_RECOVERY_AUDIT`
- `OVERWATCH_COST_SAVINGS_VERIFICATION_RUN`
- `OVERWATCH_DBA_CHECKLIST_HISTORY`
- `OVERWATCH_CHANGE_CONTROL_EVIDENCE`
- `OVERWATCH_SOURCE_CONTROL_CHANGE`
- `OVERWATCH_ITSM_TICKET`
- `OVERWATCH_WAREHOUSE_SETTING_REVIEW`
- `OVERWATCH_SECURITY_ACCESS_REVIEW`
- `OVERWATCH_ALERTS`
- `OVERWATCH_ANNOTATIONS`
- `OVERWATCH_ALERT_DELIVERY_LOG`
- `OVERWATCH_ALERT_RULE_AUDIT`
- `OVERWATCH_ALERT_RULES`
- `OVERWATCH_ROI_LOG`

### Transient Fact, Dimension, And Mart Tables

- `FACT_WAREHOUSE_HOURLY`
- `FACT_WAREHOUSE_OPERABILITY_DAILY`
- `FACT_SECURITY_OPERABILITY_DAILY`
- `FACT_ACCOUNT_HEALTH_OPERABILITY_DAILY`
- `FACT_QUERY_HOURLY`
- `FACT_QUERY_DETAIL_RECENT`
- `FACT_CHARGEBACK_DAILY`
- `DIM_COST_OWNER_TAG`
- `FACT_TASK_RUN`
- `FACT_TASK_CRITICAL_PATH`
- `DIM_TASK_SNAPSHOT`
- `DIM_PROCEDURE_SNAPSHOT`
- `FACT_PROCEDURE_RUN`
- `FACT_LOGIN_DAILY`
- `FACT_OBJECT_CHANGE`
- `FACT_CHANGE_CONTROL_OPERABILITY_DAILY`
- `FACT_GRANT_DAILY`
- `FACT_STORAGE_DAILY`
- `DIM_TABLE_SNAPSHOT`
- `FACT_COPY_LOAD_DAILY`
- `FACT_CORTEX_DAILY`
- `FACT_MONITORING_COST_DAILY`
- `FACT_COST_DAILY`
- `FACT_COST_SOURCE_HEALTH_DAILY`
- `MART_DBA_CONTROL_ROOM`

### Jira, Git, And Terraform Evidence

Change & Drift reads Jira and source-control evidence from Snowflake tables, not
from live app-side API calls. Feed these tables from ALFA CI/CD or a scheduled
Jira export job:

- `OVERWATCH_SOURCE_CONTROL_CHANGE`: one row per Terraform/Git deployment
  object or PR/apply event. Include `COMPANY`, `ENVIRONMENT`, `SOURCE_SYSTEM`,
  `REPOSITORY`, `COMMIT_SHA`, `PR_URL`, `CHANGE_TICKET_ID`,
  `OBJECT_DATABASE`, `OBJECT_SCHEMA`, `OBJECT_NAME`, `OBJECT_FQN`,
  `TERRAFORM_ADDRESS`, `PLANNED_ACTION`, `APPLY_STATUS`, `DEPLOYED_BY`, and
  `APPLY_TS`.
- `OVERWATCH_ITSM_TICKET`: one row per Jira/change ticket snapshot. Include
  `COMPANY`, `ENVIRONMENT`, `TICKET_ID`, `TICKET_URL`, `STATUS`, `ASSIGNEE`,
  `APPROVER`, `APPROVAL_STATUS`, `RISK`, change window timestamps, linked
  repository, linked commit SHA, linked PR URL, and `UPDATED_AT`.
- Terraform/Snowflake deployment jobs should set query tags with at least the
  ticket and commit when possible, for example
  `OVERWATCH:TERRAFORM;repo=alfa-snowflake;commit=<sha>;ticket=<key>`.

The app joins these rows to `FACT_OBJECT_CHANGE` by Jira key, commit SHA in
query tag, object FQN, and database/schema context. Missing joins become Change
& Drift evidence gaps instead of being hidden.

#### Feed Stages And Health

The setup bundle also creates these optional internal stages for CSV handoff
from CI/CD or scheduled Jira exports:

- `OVERWATCH_SOURCE_CONTROL_CHANGE_STAGE`
- `OVERWATCH_ITSM_TICKET_STAGE`
- `OVERWATCH_CHANGE_EVIDENCE_CSV_FORMAT`

Change & Drift now shows feed health for Terraform/Git and Jira evidence:

- `Ready - Empty`: table exists but no feed rows have arrived yet.
- `No Active Scope Rows`: rows exist, but not for the selected
  company/environment/lookback.
- `Stale`: rows exist, but the latest event is outside the active lookback.
- `Flowing`: rows exist for the active scope and can be joined to Snowflake
  change history.

The Terraform CSV load order is:

`SNAPSHOT_TS, COMPANY, ENVIRONMENT, SOURCE_SYSTEM, REPOSITORY, BRANCH_NAME,
COMMIT_SHA, PR_ID, PR_URL, CHANGE_TICKET_ID, OBJECT_DATABASE, OBJECT_SCHEMA,
OBJECT_NAME, OBJECT_TYPE, OBJECT_FQN, TERRAFORM_ADDRESS, PLANNED_ACTION,
APPLY_STATUS, DEPLOYED_BY, APPLY_TS, EVIDENCE_URL, NOTES`

The Jira CSV load order is:

`SNAPSHOT_TS, COMPANY, ENVIRONMENT, TICKET_ID, TICKET_URL, SUMMARY, STATUS,
ASSIGNEE, REQUESTER, APPROVER, APPROVAL_STATUS, RISK, CHANGE_WINDOW_START,
CHANGE_WINDOW_END, LINKED_REPOSITORY, LINKED_COMMIT_SHA, LINKED_PR_URL,
UPDATED_AT, NOTES`

CI/Jira jobs can either insert directly into the tables with these columns or
upload CSVs to the matching stage and run the load SQL shown in the Change &
Drift Terraform/Jira evidence tabs.

### Views, Functions, Procedures, And Tasks

- Views:
  - `OVERWATCH_OWNER_DIRECTORY_ACTIVE_V`
  - `OVERWATCH_WORKLOAD_RECOVERY_AUDIT_LATEST_V`
  - `OVERWATCH_COST_SAVINGS_VERIFICATION_V`
  - `OVERWATCH_COST_SAVINGS_VERIFICATION_HEALTH_V`
  - `OVERWATCH_ALERT_TRIAGE_V`
- Function:
  - `OVERWATCH_DATABASE_ENVIRONMENT(DATABASE_NAME)`
- Procedures:
  - `SP_OVERWATCH_VERIFY_COST_SAVINGS`
  - `SP_OVERWATCH_SEND_ALERT_DIGEST`
  - `SP_OVERWATCH_PRUNE`
  - `SP_OVERWATCH_LOAD_HOURLY`
  - `SP_OVERWATCH_LOAD_DAILY`
  - `SP_OVERWATCH_REFRESH_CONTROL_ROOM`
  - `SP_OVERWATCH_LOAD_CORTEX`
- Tasks:
  - `OVERWATCH_COST_SAVINGS_VERIFY`
  - `OVERWATCH_ANOMALY_CHECK`
  - `OVERWATCH_LOAD_HOURLY`
  - `OVERWATCH_LOAD_CORTEX`
  - `OVERWATCH_REFRESH_CONTROL_ROOM`
  - `OVERWATCH_LOAD_DAILY`

## Setup And Deployment Checklist

1. Edit the app config and setup SQL together.
2. Confirm deployment entrypoints and local-only secrets:

```powershell
git check-ignore -v .streamlit\secrets.toml .env .env.local snowflake_key.pem snowflake_key.key
Select-String -Path .overwatch_final\snowflake.yml -Pattern "main_file: app.py","query_warehouse: OVERWATCH_WH"
Select-String -Path STREAMLIT_CLOUD_DEPLOY.md -Pattern "streamlit_app.py"
```

3. Run local validation:

```powershell
python -m compileall .overwatch_final tests
.\.venv\Scripts\python.exe -m unittest discover -s tests
git diff --check
```

4. Run `snowflake/OVERWATCH_MART_SETUP.sql` in Snowsight with a platform-admin
   role after reviewing DDL changes. For existing deployments that only need
   release drift repaired, review `snowflake/OVERWATCH_RELEASE_REMEDIATION.sql`.
5. Confirm required grants for the app runtime role.
6. Confirm task state:

```sql
SHOW TASKS LIKE 'OVERWATCH_%' IN SCHEMA DBA_MAINT_DB.OVERWATCH;
```

7. Run smoke loads when needed:

```sql
CALL DBA_MAINT_DB.OVERWATCH.SP_OVERWATCH_LOAD_HOURLY();
CALL DBA_MAINT_DB.OVERWATCH.SP_OVERWATCH_LOAD_CORTEX();
CALL DBA_MAINT_DB.OVERWATCH.SP_OVERWATCH_REFRESH_CONTROL_ROOM();
CALL DBA_MAINT_DB.OVERWATCH.SP_OVERWATCH_LOAD_DAILY();
```

8. Confirm rows loaded in key marts:

```sql
SELECT 'FACT_WAREHOUSE_HOURLY' AS TABLE_NAME, COUNT(*) AS ROWS_LOADED
FROM DBA_MAINT_DB.OVERWATCH.FACT_WAREHOUSE_HOURLY
UNION ALL
SELECT 'FACT_QUERY_HOURLY', COUNT(*)
FROM DBA_MAINT_DB.OVERWATCH.FACT_QUERY_HOURLY
UNION ALL
SELECT 'FACT_QUERY_DETAIL_RECENT', COUNT(*)
FROM DBA_MAINT_DB.OVERWATCH.FACT_QUERY_DETAIL_RECENT
UNION ALL
SELECT 'MART_DBA_CONTROL_ROOM', COUNT(*)
FROM DBA_MAINT_DB.OVERWATCH.MART_DBA_CONTROL_ROOM;
```

## Synchronization Checklist

Use this before every release that changes manual inputs.

- Credit price is the same in `config.DEFAULTS["credit_price"]` and
  `OVERWATCH_SETTINGS.CREDIT_PRICE_USD`.
- AI credit price is the same in `config.DEFAULTS["ai_credit_price"]` and
  `OVERWATCH_SETTINGS.AI_CREDIT_PRICE_USD`.
- New ALFA databases exist in all required places:
  - `ENVIRONMENT_CONFIG`
  - `COMPANY_CONFIG`
  - `OVERWATCH_COMPANY_SCOPE`
  - `OVERWATCH_DATABASE_ENVIRONMENT()`
  - chargeback environment rollup logic
  - alert digest `DEV_ALL` filter logic
  - environment tests
- New warehouses exist in:
  - `COMPANY_CONFIG`
  - `OVERWATCH_COMPANY_SCOPE`
  - owner-directory route when ownership should be explicit
  - Snowflake grants for DBA controls when controls should execute
- App role changes exist in:
  - `ROLE_SECTIONS` if navigation visibility changes
  - Snowflake grants if data access or admin execution changes
- Alert email changes exist in:
  - `config.DEFAULT_ALERT_EMAIL`
  - `OVERWATCH_SETTINGS.DEFAULT_ALERT_EMAIL`
  - owner-directory seed/default rows
  - alert procedure defaults and fallback SQL
  - tests
- Alert rule changes exist in:
  - `DEFAULT_ALERT_RULES`
  - `OVERWATCH_ALERT_RULES`
  - anomaly task SQL when detection changes
  - tests
- Owner route changes exist in:
  - `OVERWATCH_OWNER_DIRECTORY`
  - setup SQL seed if the route should be part of baseline deployment
  - `.overwatch_final/utils/owner_directory.py` if offline/default app behavior
    should show the same route
- Task warehouse choices are consistent across:
  - `CREATE WAREHOUSE`
  - all `CREATE OR REPLACE TASK ... WAREHOUSE = ...` clauses
  - monitoring-cost logic
  - docs

## High-Risk Manual Changes

These changes need extra review:

- Changing company or environment patterns. A broad pattern can move cost,
  security, and action ownership between companies.
- Applying environment filters to account-level data with no database context.
- Changing `DEFAULT_ALERT_EMAIL` without updating owner-directory and procedure
  defaults.
- Granting elevated DBA action privileges to the app role instead of a governed
  admin role.
- Claiming exact PROD/DEV chargeback from shared warehouse metering without
  official query attribution, object tags, or a documented allocation rule.
- Repointing task warehouses without updating monitoring-cost logic.
