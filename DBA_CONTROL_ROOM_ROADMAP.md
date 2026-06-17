# OVERWATCH DBA/Admin Monitoring Roadmap

Last updated: June 17, 2026

OVERWATCH is a Snowflake DBA/admin monitoring command center. The product loop is:

```text
Monitor -> recommend -> guarded admin action -> verify -> summarize
```

The app should stay focused on Snowflake usage, cost, performance, workload
health, alerts, security telemetry, and guarded DBA/admin controls. New feature
ideas belong in docs first, then in the app only when they support that loop.

## Current Foundation

| Capability | Current state |
|---|---|
| Executive Landing | Precomputed Snowflake observability facts, platform health, cost/Cortex/workload signals, and loaded advisor lanes. |
| DBA Control Room | Fast DBA triage, morning brief, route status, data health, release risk, and Admin Tools entry point. |
| Cost & Contract | Cost movement, official service/warehouse spend, Cortex spend, run-rate, chargeback, recommendations, action queue, and Warehouse Advisor. |
| Workload Operations | Query contention, task/procedure health, Stored Procedure Advisor, pipeline/SLA risk, and bounded live triage. |
| Alert Center | Active issue inbox, alert lifecycle, suppression windows, delivery logs, remediation notes, and action queue routing. |
| Security Monitoring | Access posture, MFA/login/grant exceptions, data sharing, and security telemetry. |
| Admin Tools | Guarded warehouse settings, Cortex limits, task graph controls, query kill list, and audit logging. |
| Mart Refresh | Scheduled tasks and stored procedures populate transient facts; live account scans stay behind explicit operator actions. |

## Priority 1: Mart And DDL Safety

Keep the mart architecture physical and refreshable:

1. Use task/procedure-loaded transient tables for monitoring facts.
2. Do not use Dynamic Tables where the source path can include secure views.
3. Keep `snowflake/OVERWATCH_MART_SETUP.sql` as the single deployable setup file.
4. Keep `snowflake/OVERWATCH_MART_DROP.sql` as the mass-drop/reset script.
5. Update refresh stored procedures whenever a fact is renamed, merged, or retired.
6. Validate every object against app reads, refresh outputs, tests, and retention needs before removal.

## Priority 2: Advisor Calibration

Warehouse and procedure recommendations should be decision-grade:

1. Document thresholds and savings assumptions outside the app UI.
2. Show estimated savings separately from verified savings.
3. Require a complete post-change telemetry window before savings are treated as confirmed.
4. Route state-changing actions to DBA Control Room Admin, not recommendation cards.
5. Capture p95, queue, spill, failures, credits, and workload comparability as verification signals.

## Priority 3: Stored Procedure Advisor

Make procedure analysis a first-class Workload Operations surface:

1. Rank runtime regressions, cost regressions, orchestration gaps, and child-query anti-patterns.
2. Show calls, total runtime, p95 or latest runtime, estimated cost, failures, and child-query coverage.
3. Separate outer-CALL estimates from ROOT_QUERY_ID or mart-attributed child telemetry.
4. Queue findings only with proof query, safe next action, and guardrail text.
5. Do not rerun, redeploy, or change warehouse settings from the advisor itself.

## Priority 4: Executive Sync

Executive Landing should answer the current operating question without live scans:

1. Include loaded Warehouse Advisor and Stored Procedure Advisor signals.
2. Reflect Cortex spend, contract/run-rate pressure, task/procedure health, alert risk, and admin posture.
3. Keep first paint mart-first and bounded.
4. Use specialist sections for drilldown and guarded action.

## Priority 5: Production Polish

Keep the UI tight and Snowflake-admin focused:

1. Remove dev-only reload shims from app startup.
2. Keep Snowflake Dark and Snowflake White as the only visible themes.
3. Remove internal build/test/performance labels from user-facing screens.
4. Avoid redundant summary/detail pairs where the same data appears twice.
5. Keep heavy ACCOUNT_USAGE, metadata, compare, and admin paths behind explicit actions.

## Priority 6: Validation

Every meaningful change should run:

1. Python compile on changed files.
2. Focused unit tests for touched contracts.
3. Full unit test suite before commit.
4. Bad-character scan.
5. `git diff --check`.
6. Browser sanity across primary sections.
7. Section smoke when UX or navigation changes.

## Release Principle

Do not add surface area that cannot be monitored, explained, safely acted on, and
verified. OVERWATCH is strongest when every chart, table, action, and executive
bullet points back to Snowflake telemetry and a clear DBA/admin route.
