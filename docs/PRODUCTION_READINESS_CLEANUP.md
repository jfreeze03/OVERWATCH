# Production Readiness Cleanup

This cleanup is release-readiness work only. It does not add features, refactor
the app, execute grants, or drop legacy objects.

## Current Readiness State

The live Production Readiness score was `58 / Review` after Phase 2F
validation. The app is usable for an admin pilot, but broad production signoff
requires closing these review items:

- Schema drift: extra legacy/perf objects remain in the deployed schema.
- Alert email: `DEFAULT_ALERT_EMAIL` must be configured with approved
  recipients before scheduled email delivery is enabled.
- Data freshness: several company-scoped trust rows are missing or stale,
  especially sparse Trexis workload/cost/task telemetry.
- Role readiness: target `OVERWATCH_*` roles and `SNOW_SYSADMINS` still need
  grant proof.

Do not inflate the readiness score by relaxing these checks. Move to `Ready`
only after the evidence rows show no blocked or review findings.

## Drift Inventory

Classifications:

- `keep`: current production object.
- `migrate`: review data and move useful rows to the current model before drop.
- `deprecated but harmless`: not used by app runtime; may be retained for local
  history or dropped in a reset window.
- `safe to drop`: outside the current product scope and not required by current
  setup, pending dependency check.
- `requires human approval`: possible audit/business history; do not drop until
  an owner approves.

| Object | Type | Classification | Recommendation |
|---|---|---|---|
| `FACT_COST_GOVERNANCE_SIGNAL` | Table | safe to drop | Replaced by current cost monitoring, scorecard, forecasting, Command Center, and closed-loop marts. |
| `FACT_MONITORING_COST_DAILY` | Table | safe to drop | Superseded by `FACT_COST_DAILY`, `FACT_COST_MONITORING_SIGNAL`, and `MART_EXECUTIVE_OBSERVABILITY`. |
| `OVERWATCH_COMPANY_SCOPE` | Table | migrate | Review for useful ALFA/Trexis scope rules before dropping. |
| `OVERWATCH_COST_SAVINGS_VERIFICATION_RUN` | Table | migrate | Move useful proof to `OVERWATCH_ACTION_VERIFICATION` or `OVERWATCH_VALUE_LEDGER`. |
| `OVERWATCH_ITSM_TICKET` | Table | requires human approval | Potential ticket/audit history. Export or migrate before any drop. |
| `OVERWATCH_OWNER_DIRECTORY` | Table | migrate | Move active routes to `OVERWATCH_OPERATIONAL_OWNER_MAP`; generic directory is retired. |
| `OVERWATCH_PLATFORM_FUTURES_CONTROL_REGISTER` | Table | safe to drop | Retired platform futures scope. |
| `OVERWATCH_PLATFORM_FUTURES_EVIDENCE` | Table | safe to drop | Retired platform futures evidence. |
| `OVERWATCH_ROI_LOG` | Table | migrate | Move useful value proof to `OVERWATCH_VALUE_LEDGER`. |
| `OVERWATCH_SOURCE_CONTROL_CHANGE` | Table | migrate | Move useful change rows to `OVERWATCH_CHANGE_EVENT`. |
| `PERF_TEST_*` tables/views/procedure | Mixed | deprecated but harmless | Not production runtime. Drop only if local perf history is no longer needed. |
| `OVERWATCH_COST_SAVINGS_VERIFICATION_*` views | View | migrate | Replace with closed-loop verification/value ledger detail. |
| `OVERWATCH_OWNER_DIRECTORY_ACTIVE_V` | View | migrate | Drop after owner routes are migrated. |
| `OVERWATCH_PLATFORM_FUTURES_*` views | View | safe to drop | Retired platform futures scope. |
| `SP_OVERWATCH_REFRESH_COST_GOVERNANCE` | Procedure | safe to drop | Old cost governance refresh outside current scope. |
| `SP_OVERWATCH_VERIFY_COST_SAVINGS` | Procedure | migrate | Replace with closed-loop verification workflow. |

`snowflake/OVERWATCH_MART_VALIDATION.sql` now emits a read-only drift inventory
with reviewable SQL text. Do not execute that SQL until the owner approves.

## Alert Email Configuration

`DEFAULT_ALERT_EMAIL` is blank by default. This prevents the app from pretending
that `dba-alerts@yourcompany.com` is a real production route.

Reviewable configuration SQL:

```sql
UPDATE DBA_MAINT_DB.OVERWATCH.OVERWATCH_SETTINGS
SET SETTING_VALUE = '<approved-alert-recipient-list>',
    UPDATED_AT = CURRENT_TIMESTAMP(),
    UPDATED_BY = CURRENT_USER()
WHERE SETTING_NAME = 'DEFAULT_ALERT_EMAIL';
```

If the value is blank, generated alert rows use `CONFIG_REQUIRED` and the app
Settings panel warns that email delivery is not configured.

## Data Freshness Guidance

`FACT_TASK_RUN` itself can be healthy while company-scoped rows are missing. In
the live validation pass, the task facts had recent rows, but Trexis-specific
trust rows were still missing because no matching Trexis task telemetry was
available in the current scope.

Use this sequence before signoff:

```sql
CALL SP_OVERWATCH_LOAD_HOURLY();
CALL SP_OVERWATCH_REFRESH_ENTERPRISE_OPERATING_MODEL();
CALL SP_OVERWATCH_REFRESH_PRODUCTION_READINESS();

SELECT COMPANY, SOURCE_NAME, SOURCE_OBJECT, STATUS, FRESHNESS_MINUTES, NEXT_ACTION
FROM MART_DATA_TRUST_SUMMARY
WHERE SNAPSHOT_TS = (SELECT MAX(SNAPSHOT_TS) FROM MART_DATA_TRUST_SUMMARY)
  AND STATUS <> 'Ready'
ORDER BY COMPANY, SOURCE_OBJECT;

SELECT COMPANY, COUNT(*) AS TASK_ROWS, MAX(SCHEDULED_TIME) AS LAST_TASK_RUN
FROM FACT_TASK_RUN
GROUP BY COMPANY
ORDER BY COMPANY;
```

If `FACT_TASK_RUN` has rows for `ALL`/`ALFA` but not `Trexis`, treat that as a
company coverage issue, not a failed refresh.

## Grant Proof SQL

These are reviewable statements only. Do not execute grants without approval.

```sql
CREATE ROLE IF NOT EXISTS OVERWATCH_VIEWER;
GRANT USAGE ON DATABASE DBA_MAINT_DB TO ROLE OVERWATCH_VIEWER;
GRANT USAGE ON SCHEMA DBA_MAINT_DB.OVERWATCH TO ROLE OVERWATCH_VIEWER;
GRANT SELECT ON ALL TABLES IN SCHEMA DBA_MAINT_DB.OVERWATCH TO ROLE OVERWATCH_VIEWER;
GRANT SELECT ON FUTURE TABLES IN SCHEMA DBA_MAINT_DB.OVERWATCH TO ROLE OVERWATCH_VIEWER;
GRANT SELECT ON ALL VIEWS IN SCHEMA DBA_MAINT_DB.OVERWATCH TO ROLE OVERWATCH_VIEWER;

CREATE ROLE IF NOT EXISTS OVERWATCH_OPERATOR;
GRANT ROLE OVERWATCH_VIEWER TO ROLE OVERWATCH_OPERATOR;
GRANT INSERT, UPDATE ON TABLE DBA_MAINT_DB.OVERWATCH.ALERT_ACKNOWLEDGEMENTS TO ROLE OVERWATCH_OPERATOR;
GRANT INSERT, UPDATE ON TABLE DBA_MAINT_DB.OVERWATCH.ALERT_REMEDIATION_LOG TO ROLE OVERWATCH_OPERATOR;
GRANT INSERT, UPDATE ON TABLE DBA_MAINT_DB.OVERWATCH.OVERWATCH_ACTION_QUEUE TO ROLE OVERWATCH_OPERATOR;
GRANT USAGE ON ALL PROCEDURES IN SCHEMA DBA_MAINT_DB.OVERWATCH TO ROLE OVERWATCH_OPERATOR;

CREATE ROLE IF NOT EXISTS OVERWATCH_ADMIN;
GRANT ROLE OVERWATCH_OPERATOR TO ROLE OVERWATCH_ADMIN;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA DBA_MAINT_DB.OVERWATCH TO ROLE OVERWATCH_ADMIN;
GRANT USAGE ON WAREHOUSE OVERWATCH_WH TO ROLE OVERWATCH_ADMIN;
GRANT OPERATE ON WAREHOUSE OVERWATCH_WH TO ROLE OVERWATCH_ADMIN;
GRANT OPERATE ON TASK OVERWATCH_LOAD_HOURLY TO ROLE OVERWATCH_ADMIN;
GRANT OPERATE ON TASK OVERWATCH_LOAD_DAILY TO ROLE OVERWATCH_ADMIN;

SHOW GRANTS TO ROLE SNOW_SYSADMINS;
SHOW GRANTS OF ROLE SNOW_SYSADMINS;
SHOW GRANTS TO USER <ADMIN_USER>;
```

## Ready Criteria

The Production Readiness score should reach `Ready` only when:

- schema drift is approved and either cleaned up or documented as intentionally
  retained,
- `DEFAULT_ALERT_EMAIL` is configured or email delivery is explicitly disabled,
- data trust rows required for the selected company view are `Ready`,
- target `OVERWATCH_*` roles are granted or formally deferred,
- `SNOW_SYSADMINS` activation is proven for an appropriate test user,
- validation SQL has no unexpected failures.
