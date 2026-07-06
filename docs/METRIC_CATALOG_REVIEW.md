# OVERWATCH Metric Catalog Review

Last updated: July 6, 2026

This review documents the product-facing metric cleanup for the six primary
Decision Workspace sections. The executable catalog lives in
`.overwatch_final/metrics/metric_registry.py`; section first-paint metric
contracts continue to be generated from `config/decision_brief_contracts.json`.

## Rules

- Keep the six primary sections: Executive Landing, DBA Control Room, Alert
  Center, Cost Intelligence, Workload Operations, and Security Monitoring.
- Preserve the internal `Cost & Contract` route key where compatibility needs
  it, but use `Cost Intelligence` in user-facing labels.
- Do not create standalone leadership monitor or leadership watchlist sections.
- Do not create role-pattern-specific grant-count KPIs from one-off queries.
- Keep owner-routing coverage out of daily metric strips. Route context can
  still exist on actions and findings, but it is not a product KPI.
- First paint uses compact Decision packet metrics. Evidence, raw rows, and
  deep details remain behind explicit action.
- First-paint metrics must use the shared mart data states from
  `.overwatch_final/utils/data_state.py`: current, stale, no rows for scope,
  setup required, refresh required, connection unavailable, or query failed.
  Detail-action labels should use domain language such as `Open Cost Drivers`
  and `Open Security Details`.

## Renamed Metrics

| Old label | New label |
|---|---|
| Queue Pressure | Queries Waiting |
| Queue / Blocked Pressure | Queries Waiting plus Blocked Time |
| Data Trust | Source Freshness |
| Open Actions | Open Work Items |
| Top DBA Risk | Top Operational Signal |
| Hottest Warehouse | Top Warehouse by Cost or Top Warehouse by Queued Time |
| Cost & Contract | Cost Intelligence |

## Removed Or Demoted Metrics

| Metric | Decision | Replacement |
|---|---|---|
| Owner Coverage | Removed from user-facing metrics | Routed findings and Open Work Items |
| Unassigned Findings | Removed from user-facing metrics | Routed findings and overdue security work items |
| Unassigned Alerts | Removed from user-facing metrics | Alert lifecycle metrics and Open Work Items |
| Owner Route / Owner Approval / Cost Owner wording | Removed from metric vocabulary | Route/action context only |
| Unverified Savings | Demoted to Cost Intelligence detail | Verified value and savings verification detail |
| Monitoring Overhead | Demoted from Executive main view | Settings/Admin Setup Health or Cost detail |

## Executive Landing

| Metric | Calculation | Window | Unit | Threshold summary | First paint | Recommendation |
|---|---|---|---|---|---|---|
| Platform Health | Weighted packet score across required executive signals | selected window | score | green >=85, yellow 70-84, red <70 | yes | keep |
| Spend Movement | Current spend vs comparison baseline | selected window | percent | green flat/down, yellow +10% to +25%, red >25% | yes | keep |
| Critical / High Issues | Count open critical/high findings | selected window | issues | green 0, yellow 1-2 high, red any critical or >2 high | yes | keep |
| Source Freshness | Required source availability and staleness score | current packet | percent | green current, yellow optional stale, red required stale/missing | no | rename from Data Trust |
| Open Work Items | Open action queue work items and overdue context | selected window | work items | green 0 overdue, red critical/high overdue | yes | rename from Open Actions |
| Cortex AI Spend | Sum Cortex AI billed cost using AI pricing | selected window | USD | stable expected use is good; unexplained spike is bad | drill-through | demote from main rollup when space is tight |
| Budget Headroom / Run-rate | Budget pace from forecast/run-rate packet | selected window | days/USD | green projected within budget, red over budget | drill-through | create/keep as executive budget signal |

## DBA Control Room

| Metric | Calculation | Window | Unit | Threshold summary | First paint | Recommendation |
|---|---|---|---|---|---|---|
| Failed Queries | Failed query count and failure-rate context | selected window | queries | green <0.5%, yellow 0.5%-2%, red >2% | yes | keep |
| Pipeline Failures | Failed task/procedure/copy/load events | selected window | events | green 0, red critical or repeated failure | yes | keep |
| Queries Waiting | Queued seconds or queued-query percent | selected window | seconds/percent | green <1% queued or p95 <1s, red >5% or p95 >5s | yes | rename from Queue Pressure |
| Cost 24h | Current 24h cost vs DBA baseline | 24h | USD | green <=10%, yellow 10%-25%, red >25% over baseline | yes | keep |
| Overdue Work Items | Overdue DBA action rows | current packet | work items | green 0, red >0 | detail | rename from Overdue Actions |
| Top Warehouse by Cost | Highest warehouse cost driver | selected window | warehouse | qualified by dimension | detail | rename from Hottest Warehouse |
| Top Operational Signal | Highest DBA-ranked incident signal | current packet | signal | critical/high severity is bad | detail | rename from Top DBA Risk |

## Alert Center

| Metric | Calculation | Window | Unit | Threshold summary | First paint | Recommendation |
|---|---|---|---|---|---|---|
| Active Alerts | Dedupe-adjusted active alerts | current packet | alerts | green stable/down, red rapid growth | yes | keep |
| Critical / High | Active critical/high alerts | current packet | alerts | green 0 critical, red any critical | yes | keep |
| Overdue Alerts | Alerts past action/SLA window | current packet | alerts | green 0, red >0 | yes | keep |
| Notification Failures | Failed alert delivery events | selected window | events | green 0, yellow 1 transient, red repeated | detail | keep |
| Open Work Items | Alert-linked action work items | current packet | work items | green 0 overdue, red overdue high/critical | detail | rename from Open Action Queue |
| Noise Ratio | Noisy/flapping alerts divided by active alerts | selected window | percent | green <20%, yellow 20%-50%, red >50% | detail | create |
| MTTA / MTTR | Acknowledge and resolution latency | selected window | minutes | green <15m for critical/high MTTA, red >60m | detail | create |

Alert Center default remains an alert inbox/queue view. Kanban-style boards are
not the first-paint default.

## Cost Intelligence

| Metric | Calculation | Window | Unit | Threshold summary | First paint | Recommendation |
|---|---|---|---|---|---|---|
| Total Spend | Primary account-billed scoped spend | selected completed window | USD | green within budget, red projected over budget | yes | keep |
| Spend Movement | Current spend vs baseline | selected window | percent | green flat/down, red >25% | yes | keep |
| Forecast / Run-rate | Projected spend from run-rate/forecast packet | selected window | USD | green <= budget, red over budget | yes | keep |
| Cortex Spend Share | Cortex AI spend divided by total spend | selected window | percent | yellow >10% or +25% vs baseline, red unexplained spike | yes | keep |
| Credit Burn Rate | Credits used divided by elapsed days | selected window | credits/day | green inside budget pace, red over pace | detail | create/keep |
| 24h Credit Comparison | Current 24h credits vs prior 24h | 24h | percent | green <=10%, yellow 10%-25%, red >25% | detail | create |
| Storage Growth | Storage/fail-safe growth vs baseline | daily | percent/bytes | yellow >5% day over day, red >10% or >1 TB unexpected | detail | create |
| Cloud Services Ratio | Cloud services cost divided by compute cost | selected window | percent | green <10%, yellow 10%-20%, red >20% | detail/admin | create |
| Cortex Code Usage | Tokens, requests, AI credits, and cost by stable user | last 30 days | tokens/credits/USD | unexplained user/source spike is bad | detail | create |

Cost reconciliation remains available for audit/admin use, not as default
overview clutter.

## Workload Operations

| Metric | Calculation | Window | Unit | Threshold summary | First paint | Recommendation |
|---|---|---|---|---|---|---|
| Failed Queries | Failed SQL count | selected window | queries | green <0.5% failure rate, critical >5% | yes | keep |
| Query Failure Rate | Failed queries divided by total queries | selected window | percent | green <0.5%, red >2%, critical >5% | detail | create |
| Error Code Frequency | Failed queries grouped by normalized error code | last 24h/details | errors | repeated high-impact errors are bad | detail | create |
| Failed Query Trend | Failed SQL by time bucket | selected window | queries | rising or sharp increase is bad | detail | create |
| Pipeline Failures | Failed task/procedure/copy/load events | selected window | events | green 0, red critical/repeated | yes | keep |
| Task Success Rate | Successful tasks divided by total task runs | selected window | percent | green >=99%, red <98% | detail | create |
| Queries Waiting | Queued seconds or queued-query percent | selected window | seconds/percent | green <1% queued/p95 <1s, red >5%/p95 >5s | yes | rename |
| Blocked Time | Blocking seconds from compact detail when available | detail window | seconds | repeated/growing blocking is bad | detail | create |
| Spill Bytes / Remote Spill GB | Spill volume from query facts | selected window | bytes/GB | green 0, red repeated/growing | detail | keep/create |
| Suspended Tasks | Unexpected suspended production tasks | current packet | tasks | green 0, red unexpected prod suspension | detail | keep |

Workload owns query errors, failure trend, top error code, and affected
warehouse/user/database context.

## Security Monitoring

| Metric | Calculation | Window | Unit | Threshold summary | First paint | Recommendation |
|---|---|---|---|---|---|---|
| Failed Logins | Failed login count | security window | logins | green 0-3 last hour, red >10 or 3x baseline | yes | keep |
| Failed Logins Last Hour | Failed login events in the latest hour | last hour | logins | green 0-3, yellow 4-10, red >10 | detail | create |
| Login Success/Failure 7-Day Trend | Daily success/failure counts | 7 days | logins | rising failure share is bad | detail | create |
| Suspicious Login Attempts | High-risk login patterns by user/IP/client/error | selected window | attempts | green 0, red any high-risk pattern | detail | create |
| Risky Grants | Unexpected elevated grant posture | selected window | grants | green 0 unexpected, red unexpected elevated grant | yes | keep |
| Privilege Changes | Recent privilege changes | selected window | changes | unexpected elevated/off-hours change is bad | detail | keep |
| Sharing Exposure | Unknown or unapproved sharing exposure | selected window | databases | approved only is good, unknown exposure is bad | detail | keep |
| Credential Expirations | Expired plus expiring-within-30d credentials | 30 days | credentials | yellow expiring 30d, red expired or urgent 7d | yes | keep |
| Security Alerts | Active security alerts | current packet | alerts | critical/high active alerts are bad | detail | keep |

Generic grant posture remains in Risky Grants, Privilege Changes, and Access
Changes. No role-pattern-specific grant-count KPI was added.

## Catalog Enforcement

`tests/test_metric_catalog.py` verifies that:

- every command brief metric exists in `.overwatch_final/metrics/metric_registry.py`
- every registry row has description, calculation, unit, directionality,
  thresholds, section owner, workflow owner, tooltip, and recommended action
- banned user-facing labels stay out of generated command contracts
- Queries Waiting has thresholds
- Cost Intelligence remains the display label for the internal Cost route
- boss-requested monitoring needs are covered by the owning section
- Alert Center default is not Kanban-first
