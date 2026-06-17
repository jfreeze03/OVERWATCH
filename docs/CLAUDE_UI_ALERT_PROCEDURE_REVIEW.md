# CLAUDE-UI Alert and Stored Procedure Review

Date: 2026-06-17

Reference repo inspected: `jfreeze03/CLAUDE-UI`

Reference commit: `919bc2c feat: Enhance security detections with evidence-first approach and new metrics`

Primary files reviewed:

- `snowmonitor/lib/alerts.py`
- `snowmonitor/lib/security_intel.py`
- `snowmonitor/lib/sp_intel.py`
- `snowmonitor/lib/tasks_intel.py`
- `snowmonitor/lib/metrics.py`
- `snowmonitor/sections/alerts.py`
- `snowmonitor/setup/setup.sql`

## Summary

CLAUDE-UI added a compact alert engine, native Snowflake `ALERT` SQL generation,
task intelligence, stored procedure intelligence, and evidence-first security
detections. OVERWATCH already has the stronger lifecycle model, action queue,
stored procedure mart, task mart, alert rule catalog, delivery/remediation log,
and scheduled anomaly task. The safest path is to port the detection ideas, not
the smaller framework wholesale.

The highest-value gaps for OVERWATCH are:

1. Evidence-first security detections for account takeover, single-factor
   password login, new IP login, and privileged role/ownership grants.
2. Proactive contract/budget pacing by company, not just warehouse credit spike.
3. Task freshness/SLA and consecutive-failure detection, not just single failed
   task runs.
4. Procedure degradation with current-vs-prior p95/average context, not only
   failure/runtime spike.
5. Optional generated native Snowflake `ALERT` SQL for server-side notification
   where the app is not open.

## Stored Procedure Review

CLAUDE-UI detects stored procedure work from `SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY`
rows where `QUERY_TYPE = 'CALL'`. It extracts the procedure name from `QUERY_TEXT`,
then computes:

- calls, average runtime, p95 runtime, max runtime, total minutes, failed calls,
  and last run;
- current-window average/p95 compared with a prior equal window;
- per-procedure daily duration series for anomaly detection;
- separate heavy-query candidates that exclude `CALL` rows so the optimization
  path targets the child statement or real inefficient query pattern.

OVERWATCH already has a deeper version of this:

- `FACT_PROCEDURE_RUN` and `DIM_PROCEDURE_SNAPSHOT` in
  `snowflake/OVERWATCH_MART_SETUP.sql`;
- `SP_OVERWATCH_LOAD_HOURLY()` loading procedure facts from `QUERY_HISTORY`;
- `Workload Operations > Stored procedures` and shared procedure loaders;
- scheduled `OVERWATCH_ANOMALY_CHECK` candidates for stored procedure failure
  and runtime spike.

Recommended action: keep OVERWATCH's mart-first design. Add the CLAUDE-UI
current-vs-prior p95/avg degradation idea and child-query separation to the
Stored Procedure Advisor and alert evidence, but do not replace the existing
procedure mart.

## Alert Coverage Matrix

| Alert idea | Type | CLAUDE-UI source | OVERWATCH status | Recommended action |
|---|---|---|---|---|
| Monthly budget or contract pacing | Proactive | `alerts.evaluate()` | Missing as scheduled alert | Add company-scoped budget/contract pacing using `ALERT_THRESHOLDS` or settings. Route to Cost & Contract. |
| Daily spend spike | Proactive | `alerts.evaluate()` and anomaly mart | Covered/partial | Existing `OVERWATCH_ANOMALY_CHECK` has credit spike and predictive cost anomaly. Add minimum dollar threshold and contract context. |
| Storage growth | Proactive | `alerts.evaluate()` | Missing as alert | Add database-level storage/failsafe growth detection from storage facts or bounded `DATABASE_STORAGE_USAGE_HISTORY`. |
| Warehouse idle/oversized recommendation | Proactive | `recommend.py`, mart efficiency | Partial | Rule exists. Materialize recommendation events only when monthly savings and telemetry confidence pass thresholds. |
| Warehouse queue pressure | Reactive | `alerts.evaluate()` | Covered/partial | Existing task covers queue and p95. Add remote spill and lock/blocked time evidence into the same alert family. |
| Remote spill / memory pressure | Reactive | `alerts.evaluate()` | Partial | OVERWATCH has UI/shared loaders, but scheduled alert should include spill threshold and top query proof. |
| Failed query rate | Reactive | `alerts.evaluate()` | Covered/partial | Existing task uses failed query count. Improve to rate plus error-cluster proof by query hash/error code. |
| Failed task runs | Reactive | `alerts.evaluate()` | Covered | Existing task inserts task failures. Improve with consecutive failure count and root task graph impact. |
| Task freshness/SLA late/stale | Proactive | `tasks_intel.task_sla_sql()` | Missing/partial | Add expected cadence and minutes-since-last-success event using `FACT_TASK_RUN` or `TASK_HISTORY`. |
| Task duration anomaly | Proactive | `tasks_intel.task_duration_daily_sql()` | Partial | Add duration anomaly to task health alerts after baseline confidence. |
| Serverless task cost spike | Proactive | `tasks_intel.serverless_task_cost_sql()` | Missing/partial | Add cost alert if serverless task credits exceed threshold or baseline. |
| Stored procedure failure | Reactive | `sp_intel.sp_performance_sql()` | Covered | Existing `OVERWATCH_ANOMALY_CHECK` includes procedure failures from `FACT_PROCEDURE_RUN`. |
| Stored procedure runtime degradation | Proactive | `sp_intel.sp_degradation_sql()` | Partial | Add current-vs-prior avg/p95 and baseline confidence to alert evidence. |
| Stored procedure cost breach | Proactive | CLAUDE SP/cost idea | Partial | Stored Procedure Advisor has cost watch; materialize only when cost threshold and procedure attribution confidence are present. |
| Failed login spike | Reactive | `alerts.evaluate()` | UI covered, scheduled partial | Add explicit alert event from `LOGIN_HISTORY` or login mart with source IP/user evidence. |
| Account takeover pattern | Reactive/security incident | `security_intel.takeover_candidates_sql()` | Missing | Add failed-login burst followed by successful login detection. Critical/high when success-after is true. |
| Single-factor password login | Reactive/security control gap | `security_intel.single_factor_logins_sql()` | Missing | Add successful password login with no second factor detection where columns are available. |
| Login from new IP | Proactive/security early warning | `security_intel.new_ip_logins_sql()` | Missing | Add recent user/IP not seen in prior 30 days. Route to Security Monitoring. |
| Users without MFA | Reactive/control gap | `alerts.evaluate()` | UI covered | Keep as posture surface; alert only for active/password users or new gaps to avoid noisy daily repeats. |
| Privileged role or ownership grant | Reactive/security incident | `security_intel.privilege_grants_sql()` | Config exists, materialization partial | Add evidence-first event from `GRANTS_TO_ROLES` and `GRANTS_TO_USERS`, not just generic grant/revoke query text. |
| High grant volume | Reactive/change monitoring | `alerts.evaluate()` | Covered/partial | Existing generic grant/revoke activity is useful; keep lower severity unless privileged grant criteria match. |
| Warehouse setting change | Reactive/change monitoring | CLAUDE controls context | Covered | Existing task detects `ALTER WAREHOUSE`. Keep review-only action contract. |
| Sensitive export/share/access | Reactive/security incident | OVERWATCH rule catalog | Rule exists, materialization missing/partial | Add events for `COPY INTO @stage`, external share changes, and sensitive object access if source telemetry is reliable. |
| Copy/load failure | Reactive/pipeline | OVERWATCH rule catalog | Rule exists, materialization missing/partial | Add scheduled event from load history / copy history where available, route to Workload Operations. |
| Native Snowflake alert object for failed tasks | Reactive notification | `build_alert_object_sql()` | Missing as generator | Add optional SQL generator. Do not auto-create native alerts from the app. |

## Proactive Alert Set To Build

These should fire before a budget, SLA, or reliability threshold is fully broken:

1. Company contract/budget pacing.
2. Warehouse daily spend spike with minimum dollar threshold.
3. Storage/failsafe growth by database.
4. Warehouse idle/oversized savings candidate with confidence and monthly savings.
5. Warehouse queue/spill trend worsening before outage.
6. Task freshness/SLA late or stale based on expected cadence.
7. Task duration anomaly against baseline.
8. Stored procedure runtime degradation against prior window.
9. Stored procedure cost breach when attribution confidence is high.
10. Cortex/AI spend run-rate or function/model spike.
11. New IP login for a user.
12. New MFA/control gap for an active password user.

## Reactive Alert Set To Build

These should fire when a current failure, security event, or control-plane change
has already happened:

1. Failed task run or consecutive task failures.
2. Failed query rate/error cluster.
3. Warehouse saturation: queue, spill, lock/blocked time.
4. Stored procedure failed `CALL`.
5. Copy/load failure.
6. Account takeover pattern: failed-login burst followed by success.
7. Single-factor password login.
8. Privileged role grant, admin role grant, or ownership transfer.
9. High grant/revoke volume.
10. Warehouse setting change.
11. Sensitive export/share/access event.
12. Native Snowflake alert failure or notification delivery failure.

## Implementation Plan

1. Keep the current OVERWATCH lifecycle model.
   `OVERWATCH_ALERTS`, `OVERWATCH_ALERT_TRIAGE_V`, `ALERT_EVENTS`,
   `ALERT_ACKNOWLEDGEMENTS`, `ALERT_NOTIFICATION_LOG`, and
   `ALERT_REMEDIATION_LOG` already cover more operator workflow than CLAUDE-UI.

2. Decide and document the alert event source of truth.
   Short term, `OVERWATCH_ANOMALY_CHECK` can continue inserting into
   `OVERWATCH_ALERTS` and then materialize into `ALERT_EVENTS`. Medium term,
   new detection procedures should write directly into `ALERT_EVENTS` and keep
   `OVERWATCH_ALERTS` as legacy compatibility.

3. Add detection SQL in small groups.
   Start with evidence-first security detections because they are high-impact
   and currently the clearest gap:
   account takeover, single-factor login, new IP login, and privileged grant.

4. Add proactive cost/SLA detections next.
   Company budget pacing, task freshness, procedure degradation, and storage
   growth are the best next fit because they are DBA/admin monitoring signals
   and do not overlap with Snowflake's own Cost Management too heavily.

5. Keep heavy scans behind scheduled mart/procedure refresh.
   New detections should be loaded by `SP_OVERWATCH_*` procedures/tasks or small
   bounded alert tasks, not by first-paint UI loads.

6. Generate native Snowflake `ALERT` SQL as an optional admin artifact.
   The app should show SQL for task failure, security incident, and cost pacing
   native alerts, but should not auto-create or resume native alerts without a
   reviewed DBA deployment step.

7. Add tests before expanding DDL.
   For every new alert family, add tests that assert the expected source views,
   company scoping, dedupe key, proof query, severity, and route.

## Do Not Port Directly

Do not copy the CLAUDE-UI alert UI or setup SQL wholesale. It is useful as a
prototype, but OVERWATCH already has:

- company-aware scoping;
- action queue and remediation contracts;
- alert lifecycle history;
- stored procedure and task marts;
- command-center triage views;
- DDL setup/drop/validation contracts.

Port the detection logic and native-alert SQL generation pattern, then adapt it
to OVERWATCH's existing DBA/admin monitoring architecture.
