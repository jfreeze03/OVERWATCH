# Executive Scorecard

Phase 2B adds leadership-facing health scoring without changing the platform
core or adding first-paint live Snowflake scans.

## Scores

| Score | Purpose | Primary workflow route |
|---|---|---|
| Snowflake Health Score | DBA platform health, failed refreshes, failed tasks, and app failures. | DBA / Platform |
| Cost Efficiency Score | Cost signals, Cortex/cost alerts, verified value, and unverified savings exposure. | DBA / Cost attribution |
| Security Score | Security alert pressure and security ownership gaps. | Security / DBA |
| Operational Risk Score | Critical/high alerts, open high-priority actions, and ownership gaps. | DBA Review |
| Data Trust Score | Missing, stale, or low-confidence source trust rows. | DBA / Platform |
| Production Readiness Score | Deployment, validation, privilege, refresh, config, and environment readiness. | DBA / Platform |

Each score includes current score, green/yellow/red status, trend, drivers,
recommended action, workflow route or workflow gap, value/risk, confidence, and last
refreshed timestamp.

## Snowflake Objects

| Object | Purpose |
|---|---|
| `OVERWATCH_EXECUTIVE_SCORECARD_CONFIG` | Score catalog, thresholds, workflow route, driver source, and recommended action defaults. |
| `OVERWATCH_EXECUTIVE_SCORECARD_HISTORY` | Score snapshots and driver history retained for explicit Load panels. |
| `MART_EXECUTIVE_SCORECARD_SUMMARY` | Compact first-paint source for Executive Landing. |
| `SP_OVERWATCH_REFRESH_EXECUTIVE_SCORECARD` | Refreshes score history and summary from existing OVERWATCH marts and app tables. |

`SP_OVERWATCH_REFRESH_EXECUTIVE_OBSERVABILITY` calls the scorecard refresh after
enterprise operating model and production readiness refreshes.

## UI Placement

| Section | Behavior |
|---|---|
| Executive Landing | First-paint compact scorecard summary from `MART_EXECUTIVE_SCORECARD_SUMMARY`. |
| DBA Control Room | Explicit Load for all score drivers from `OVERWATCH_EXECUTIVE_SCORECARD_HISTORY`. |
| Cost & Contract | Explicit Load for Cost Efficiency Score drivers. |
| Security Monitoring | Explicit Load for Security Score drivers. |
| Alert Center | Explicit Load for Operational Risk Score drivers. |

## Safety Rules

- First paint reads the compact summary mart only.
- Driver history is behind explicit Load buttons.
- The scorecard procedure reads existing OVERWATCH marts/app tables.
- No broad first-paint `ACCOUNT_USAGE`, `INFORMATION_SCHEMA`, or `SHOW` scans are introduced.
- No remediation SQL is executed.
- Confidence labels are constrained to `exact`, `allocated`, `estimated`, or `fallback`.
- Scores are bounded from 0 to 100 and statuses are constrained to `Green`, `Yellow`, or `Red`.

## Manual Snowflake Validation

After deploying the DDL, run:

```sql
CALL SP_OVERWATCH_REFRESH_EXECUTIVE_OBSERVABILITY();
CALL SP_OVERWATCH_REFRESH_EXECUTIVE_SCORECARD();
```

Then run `snowflake/OVERWATCH_MART_VALIDATION.sql` and confirm:

- object count contract passes,
- all six score keys have recent rows,
- status/confidence labels pass validation,
- score values are between 0 and 100,
- `MART_EXECUTIVE_SCORECARD_SUMMARY` has rows for `ALL`, `ALFA`, and `Trexis`
  where source marts have company-specific data,
- detail panels load only after clicking their Load buttons.
