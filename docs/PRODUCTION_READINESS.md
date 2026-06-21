# Production Readiness

Phase 2A adds live production validation without changing the Phase 1 app
architecture. It gives DBAs and leadership one place to see whether the
OVERWATCH deployment can be trusted today.

## Operating Boundary

The Production Readiness Dashboard is mart-first:

- Executive Landing reads `MART_PRODUCTION_READINESS_SUMMARY`.
- DBA Control Room detail panels read `OVERWATCH_PRODUCTION_VALIDATION_STATUS`.
- First paint does not run `ACCOUNT_USAGE`, `INFORMATION_SCHEMA`, `SHOW`, or
  grant-probing queries.
- Role, privilege, refresh, config, and environment detail remains behind
  explicit Load buttons.

## Snowflake Objects

| Object | Purpose |
|---|---|
| `OVERWATCH_PRODUCTION_CHECKLIST` | Production validation checklist catalog. |
| `OVERWATCH_ROLE_READINESS_REQUIREMENT` | Target and legacy role readiness requirements. |
| `OVERWATCH_PRIVILEGE_READINESS_REQUIREMENT` | Required privilege families and manual proof SQL. |
| `OVERWATCH_PRODUCTION_VALIDATION_STATUS` | Latest detail validation rows by domain. |
| `MART_PRODUCTION_READINESS_SUMMARY` | Compact first-paint readiness dashboard mart. |
| `SP_OVERWATCH_REFRESH_PRODUCTION_READINESS` | Refreshes checklist, role, privilege, refresh health, config drift, data freshness, and environment readiness summaries. |

## Dashboard Signals

The summary mart exposes:

- deployment version,
- last deployment,
- last validation run,
- validation status,
- missing privilege blockers inferred from failed refresh audit rows,
- failed mart refreshes,
- missing summary mart data,
- data freshness issue count,
- configuration drift,
- environment readiness,
- readiness signal for triage (not a standalone production signoff),
- top risk,
- next action.

## Explicit Detail Panels

DBA Control Room exposes explicit Load buttons for:

- Production Validation Checklist,
- Role Readiness,
- Privilege Readiness,
- Refresh Health.

These panels are intended to support deployment signoff and incident
troubleshooting. They do not execute remediation.

## What Phase 2A Does Not Prove Automatically

Snowflake role existence and full grant coverage still require manual DBA
validation because broad live grant scans should not run during first paint.
The readiness procedure marks target OVERWATCH roles as review items until a
DBA confirms them. Privilege readiness is marked ready only when no recent
privilege-related refresh failure appears in `OVERWATCH_LOAD_AUDIT`; grant proof
still comes from `OVERWATCH_MART_VALIDATION.sql` and the listed `SHOW GRANTS`
steps.

## Manual Snowflake Validation

After deploying setup SQL:

```sql
CALL SP_OVERWATCH_REFRESH_PRODUCTION_READINESS();
```

Then run `snowflake/OVERWATCH_MART_VALIDATION.sql` and review:

- required production readiness objects are present,
- object count contract passes,
- `MART_PRODUCTION_READINESS_SUMMARY` has recent rows,
- `OVERWATCH_PRODUCTION_VALIDATION_STATUS` has rows for each readiness domain,
- `PRODUCTION_PRIVILEGE_BLOCKERS` shows no blocked privilege failures,
- caller context matches the intended database, schema, role, and warehouse.

Run the `SHOW GRANTS` statements listed in
`OVERWATCH_PRIVILEGE_READINESS_REQUIREMENT` before declaring production ready.

## External Signoff Gates

Do not declare broad production readiness from a self-assigned score. Require
evidence that:

- CI is green, including compileall, unit tests, CodeQL, Ruff critical lint,
  focused mypy helper checks, and mojibake scan,
- every primary section renders through the role-appropriate smoke runner,
- `snowflake/OVERWATCH_MART_VALIDATION.sql` passes,
- no committed secrets are present,
- a role-based viewer smoke test passes,
- first paint does not perform full `ACCOUNT_USAGE` scans, and
- `snowflake/mart_setup/01_roles.sql` through `09_validation.sql` run in order.

For the remaining broad-production cleanup checklist, including schema drift
classification, alert email configuration, data freshness triage, and
reviewable role grant SQL, use
`docs/PRODUCTION_READINESS_CLEANUP.md`.

Governance-alignment release candidate assumptions are documented there as
well: `jdees@alfains.com` is the approved alert recipient, Trexis has
ALFA-equivalent telemetry expectations, target `OVERWATCH_*` roles are approved
for reviewed migration, and `SNOW_ACCOUNTADMINS`/`SNOW_SYSADMINS` remain the
approved interim access model.
