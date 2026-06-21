# Production Readiness Cleanup

This cleanup is release-readiness work only. It does not add features, refactor
the app, execute grants, or drop legacy objects.

## Governance Alignment Release Candidate

The prior live Production Readiness score was `58 / Review` after Phase 2F
validation. The governance alignment release candidate removes penalties for
approved business decisions and keeps warnings visible where migration is still
pending.

Approved assumptions:

- Alert email recipient: `jdees@alfains.com`.
- Trexis is ALFA-equivalent for telemetry coverage expectations.
- `OVERWATCH_VIEWER`, `OVERWATCH_OPERATOR`, and `OVERWATCH_ADMIN` are approved
  target roles.
- `SNOW_ACCOUNTADMINS` and `SNOW_SYSADMINS` are approved interim access roles
  until migration is completed.

The in-app `SP_OVERWATCH_REFRESH_PRODUCTION_READINESS()` score is an operator
triage signal, not the release decision. Release go/no-go is judged against the
externally verifiable gates in `docs/PRODUCTION_READINESS.md` (CI green, all
sections render, mart validation passes, no committed secrets, role-based viewer
smoke test passes, no first-paint full ACCOUNT_USAGE scans, deployment SQL runs
in order). Do not manually inflate the in-app score; true stale or missing
source rows should remain visible.

Remaining broad production review items:

- Data freshness: company-scoped trust rows must be refreshed or disclosed,
  including any true Trexis gaps.
- Schema drift: extra legacy/perf objects remain in the deployed schema and
  need owner-approved retention, migration, or cleanup.
- Role migration: approved target roles still need review-only grants applied
  through a controlled Snowflake change.

## Drift Inventory

Release-candidate classifications:

- `approved legacy`: retained as accepted validation/history evidence for now.
- `migration candidate`: review data and move useful rows to the current model
  before drop.
- `cleanup candidate`: outside current product scope, pending dependency check.
- `required retention`: possible audit/business history; do not drop until an
  owner approves export, migration, or retention.

| Object | Type | Classification | Recommendation |
|---|---|---|---|
| `FACT_COST_GOVERNANCE_SIGNAL` | Table | cleanup candidate | Replaced by current cost monitoring, scorecard, forecasting, Command Center, and closed-loop marts. |
| `FACT_MONITORING_COST_DAILY` | Table | cleanup candidate | Superseded by `FACT_COST_DAILY`, `FACT_COST_MONITORING_SIGNAL`, and `MART_EXECUTIVE_OBSERVABILITY`. |
| `OVERWATCH_COMPANY_SCOPE` | Table | migration candidate | Review for useful ALFA/Trexis scope rules before dropping. |
| `OVERWATCH_COST_SAVINGS_VERIFICATION_RUN` | Table | migration candidate | Move useful proof to `OVERWATCH_ACTION_VERIFICATION` or `OVERWATCH_VALUE_LEDGER`. |
| `OVERWATCH_ITSM_TICKET` | Table | required retention | Potential ticket/audit history. Export or migrate before any drop. |
| `OVERWATCH_OWNER_DIRECTORY` | Table | migration candidate | Move active routes to `OVERWATCH_OPERATIONAL_OWNER_MAP`; generic directory is retired. |
| `OVERWATCH_PLATFORM_FUTURES_CONTROL_REGISTER` | Table | cleanup candidate | Retired platform futures scope. |
| `OVERWATCH_PLATFORM_FUTURES_EVIDENCE` | Table | cleanup candidate | Retired platform futures evidence. |
| `OVERWATCH_ROI_LOG` | Table | migration candidate | Move useful value proof to `OVERWATCH_VALUE_LEDGER`. |
| `OVERWATCH_SOURCE_CONTROL_CHANGE` | Table | migration candidate | Move useful change rows to `OVERWATCH_CHANGE_EVENT`. |
| `PERF_TEST_*` tables/views/procedure | Mixed | approved legacy | Retain as validation/history evidence until local perf history is formally retired. |
| `OVERWATCH_COST_SAVINGS_VERIFICATION_*` views | View | migration candidate | Replace with closed-loop verification/value ledger detail. |
| `OVERWATCH_OWNER_DIRECTORY_ACTIVE_V` | View | migration candidate | Drop after owner routes are migrated. |
| `OVERWATCH_PLATFORM_FUTURES_*` views | View | cleanup candidate | Retired platform futures scope. |
| `SP_OVERWATCH_REFRESH_COST_GOVERNANCE` | Procedure | cleanup candidate | Old cost governance refresh outside current scope. |
| `SP_OVERWATCH_VERIFY_COST_SAVINGS` | Procedure | migration candidate | Replace with closed-loop verification workflow. |

`snowflake/OVERWATCH_MART_VALIDATION.sql` now emits a read-only drift inventory
with reviewable SQL text. Do not execute that SQL until the owner approves.

## Alert Email Configuration

`DEFAULT_ALERT_EMAIL` is configured to the approved recipient
`jdees@alfains.com` by default. Blank or placeholder deployments are upgraded to
this value during setup; existing custom non-placeholder values are preserved.

Reviewable configuration SQL:

```sql
UPDATE DBA_MAINT_DB.OVERWATCH.OVERWATCH_SETTINGS
SET SETTING_VALUE = 'jdees@alfains.com',
    UPDATED_AT = CURRENT_TIMESTAMP(),
    UPDATED_BY = CURRENT_USER()
WHERE SETTING_NAME = 'DEFAULT_ALERT_EMAIL';
```

If the value is later blanked, generated alert rows use `CONFIG_REQUIRED` and
the app Settings panel warns that email delivery is not configured.

## Data Freshness Guidance

Trexis is governed with ALFA-equivalent telemetry expectations. A missing Trexis
row is therefore a true coverage gap, not a lower-standard exception.

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
company coverage issue, not a failed refresh, and keep it visible until Trexis
task telemetry exists or the source is formally marked not applicable.

## Grant Proof SQL

These are reviewable statements only. `OVERWATCH_VIEWER`, `OVERWATCH_OPERATOR`,
and `OVERWATCH_ADMIN` are approved target roles, but grants must still move
through a reviewed Snowflake change. Do not execute grants without approval.

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

SHOW GRANTS TO ROLE SNOW_ACCOUNTADMINS;
SHOW GRANTS OF ROLE SNOW_ACCOUNTADMINS;
SHOW GRANTS TO USER <ADMIN_USER>;
```

## Ready Criteria

The Production Readiness score should reach `Ready` only when:

- schema drift is approved and either cleaned up, migrated, retained, or
  documented as intentionally legacy,
- `DEFAULT_ALERT_EMAIL` remains configured to the approved recipient,
- data trust rows required for the selected company view are `Ready`,
- target `OVERWATCH_*` grants are applied through reviewed migration,
- `SNOW_ACCOUNTADMINS` and `SNOW_SYSADMINS` remain documented transitional
  access until migration completes,
- validation SQL has no unexpected failures.
