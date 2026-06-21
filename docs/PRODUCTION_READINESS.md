# Production Readiness

Phase 2A adds live production validation without changing the Phase 1 app
architecture. It gives DBAs and leadership one place to see whether the
OVERWATCH deployment can be trusted today.

## Externally Verifiable Readiness Gates

Go/no-go is decided against externally verifiable gates, not a self-assigned
readiness score. Each gate is something a reviewer can independently confirm
from CI output, the test suite, the repository, or a Snowflake validation run.
The in-app `readiness score` (below) is a triage signal for operators, not the
release decision.

| Gate | What it proves | How to verify |
|---|---|---|
| **CI is green** | The committed code compiles, lints, type-checks, and passes the full test suite. | `Validate` and `CodeQL` GitHub Actions workflows are green on the release commit. |
| **All sections render** | Every navigation section and shell contract renders without error. | `python -m unittest discover -s tests` passes (includes `test_navigation_integrity` render/contract guards). |
| **Mart validation passes** | Required Snowflake objects, object-count contract, and recent mart rows exist. | Run `snowflake/OVERWATCH_MART_VALIDATION.sql` after deployment and confirm no failures. |
| **No committed secrets** | No credentials, keys, or connection secrets live in the repo. | Repository scan is clean; `.gitignore` excludes `.env*`, `*.pem`, `*.key`, and `.streamlit/secrets.toml`. |
| **Role-based viewer smoke test passes** | A read-only viewer role is correctly scoped and cannot perform admin actions. | `python -m unittest tests.test_session_role` (and `tests.test_admin_controls`) pass. |
| **No first-paint full `ACCOUNT_USAGE` scans** | First paint stays mart-first; expensive live scans stay behind explicit Load buttons. | `python -m unittest tests.test_query_guardrails` passes; first paint reads marts only (see Operating Boundary). |
| **Deployment SQL runs in order** | The setup DDL deploys deterministically and reproducibly. | `snowflake/setup/` parts run in numeric order and reproduce `OVERWATCH_MART_SETUP.sql` byte-for-byte (`python -m unittest tests.test_mart_setup_split`). |

A deployment is "production ready" when **all** gates above are satisfied. The
gates supersede any single composite score for release decisions.

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
- readiness score,
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

For the remaining broad-production cleanup checklist, including schema drift
classification, alert email configuration, data freshness triage, and
reviewable role grant SQL, use
`docs/PRODUCTION_READINESS_CLEANUP.md`.

Governance-alignment release candidate assumptions are documented there as
well: `jdees@alfains.com` is the approved alert recipient, Trexis has
ALFA-equivalent telemetry expectations, target `OVERWATCH_*` roles are approved
for reviewed migration, and `SNOW_ACCOUNTADMINS`/`SNOW_SYSADMINS` remain the
approved interim access model.
