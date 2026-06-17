# OVERWATCH Alerting and Automation Roadmap

Date: 2026-06-17

Purpose: define the comprehensive alert strategy for OVERWATCH across cost,
system health, user behavior, security, workload reliability, and future
guarded automation.

This plan combines:

- Current OVERWATCH Alert Center, action queue, mart, and remediation contracts.
- The CLAUDE-UI alert/procedure/security review in
  `docs/CLAUDE_UI_ALERT_PROCEDURE_REVIEW.md`.
- Snowflake-native alerting, notification, task, budget, and telemetry features.
- Mature alerting practices from Google SRE, Datadog, PagerDuty, and Azure
  Monitor documentation.

## External Research Anchors

- Snowflake alerts can send notifications and perform actions when data meets a
  condition:
  https://docs.snowflake.com/en/guides-overview-alerts
- Snowflake alert setup and notification integration guidance:
  https://docs.snowflake.com/en/user-guide/alerts
- Snowflake email notifications and `SYSTEM$SEND_EMAIL`:
  https://docs.snowflake.com/en/user-guide/notifications/email-stored-procedures
- Snowflake notifications to email, queues, and webhooks:
  https://docs.snowflake.com/en/user-guide/notifications/about-notifications
- Snowflake tasks run SQL and stored procedures on schedules or events:
  https://docs.snowflake.com/en/user-guide/tasks-intro
- Snowflake triggered tasks avoid compute until an event occurs:
  https://docs.snowflake.com/en/user-guide/tasks-triggered
- Snowflake resource monitors help control warehouse credit usage:
  https://docs.snowflake.com/en/user-guide/resource-monitors
- Snowflake budgets forecast spending and send daily notifications:
  https://docs.snowflake.com/en/user-guide/budgets
- Snowflake cost management overview:
  https://docs.snowflake.com/en/user-guide/cost-management-overview
- Snowflake query cost attribution:
  https://docs.snowflake.com/en/sql-reference/account-usage/query_attribution_history
- Snowflake `QUERY_HISTORY`:
  https://docs.snowflake.com/en/sql-reference/account-usage/query_history
- Snowflake `LOGIN_HISTORY`:
  https://docs.snowflake.com/en/sql-reference/account-usage/login_history
- Snowflake `ACCESS_HISTORY`:
  https://docs.snowflake.com/en/sql-reference/account-usage/access_history
- Snowflake `TASK_HISTORY` table function:
  https://docs.snowflake.com/en/sql-reference/functions/task_history
- Snowflake `NOTIFICATION_HISTORY` table function:
  https://docs.snowflake.com/en/sql-reference/functions/notification_history
- Google SRE monitoring guidance:
  https://sre.google/sre-book/monitoring-distributed-systems/
- Google SRE SLO alerting guidance:
  https://sre.google/workbook/alerting-on-slos/
- Datadog alert fatigue guidance:
  https://www.datadoghq.com/blog/best-practices-to-prevent-alert-fatigue/
- PagerDuty Event Orchestration automation guidance:
  https://support.pagerduty.com/main/docs/event-orchestration
- Azure Monitor action groups and automated actions:
  https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/action-groups

## Design Principles

1. Alert only when the condition is actionable.
   Every alert must have an owner, route, severity, evidence, dedupe key,
   next action, and source freshness note.

2. Prefer symptom and business-impact alerts over raw internals.
   Queue/spill is useful, but the alert should explain which warehouse, company,
   user/role, task, procedure, cost, or SLA is affected.

3. Separate proactive and reactive alerts.
   Proactive alerts warn before a budget/SLA/reliability threshold is crossed.
   Reactive alerts fire when a failure or control-plane event has already
   happened.

4. Keep alert source-of-truth simple.
   New detections should write directly to `ALERT_EVENTS` when possible.
   `OVERWATCH_ALERTS` can stay as compatibility and UI source while the
   migration completes.

5. Dedupe and suppress aggressively.
   Group by company, environment, domain, entity, alert type, and time bucket.
   Suppression windows should mute planned changes without hiding evidence.

6. Keep Snowflake's native Cost Management in the loop.
   Use Snowflake budgets and resource monitors for hard cost guardrails; use
   OVERWATCH for company/user/query behavior, attribution, evidence, and DBA
   routing.

7. Automate only after recommendation quality is proven.
   Future remediation must move through detection, recommendation, dry-run,
   status review, approval guardrails, execution, rollback, and verification.

## Current Implementation Pass

- Alert Center is organized into value lanes: Command Center, Cost & Behavior,
  Reliability, Security, Detection Catalog, Delivery & Automation, and
  Suppression Windows.
- Cost & Behavior spotlights spend spikes, Cortex spend, warehouse cost
  behavior, and user-driven spend anomalies from the same loaded alert/action
  data used by the command view.
- Cost & Contract, Workload Operations, Security Monitoring, and Executive
  Landing can show loaded alert context without issuing additional Snowflake
  reads. The Alert Center load remains the source for those cross-section
  strips.
- Cortex spend spike and quota drift is seeded in Python defaults,
  `ALERT_THRESHOLDS`, `ALERT_CONFIG`, and the detection catalog. Fresh mart
  rebuilds should include the `COST_CORTEX_SPEND_SPIKE` threshold alongside the
  existing `CORTEX_SPEND_AND_QUOTA` event family.

## Alert Domains

### 1. Cost and Contract Alerts

| Alert | Type | Source | Severity logic | First action | Future automation |
|---|---|---|---|---|---|
| Company budget/contract pacing | Proactive | `FACT_COST_DAILY`, Snowflake budgets, `METERING_HISTORY` | High when forecast exceeds budget/contract; Medium at 80-90% | Open Cost & Contract forecast and top drivers | Adjust warehouse/resource monitor threshold only after approval |
| Daily spend spike | Proactive | `FACT_WAREHOUSE_HOURLY`, `WAREHOUSE_METERING_HISTORY` | Baseline multiple plus minimum dollars | Explain top warehouse/user/query movement | Queue resource monitor review |
| User or role spend anomaly | Proactive | `QUERY_ATTRIBUTION_HISTORY`, `FACT_QUERY_ATTR_DAILY`, role-aware company filter | User/role spend exceeds baseline or cohort percentile | Review user behavior and copied query patterns | Notify owner; no auto action initially |
| Warehouse idle burn | Proactive | Warehouse metering plus query activity | High savings + high idle % | Route Warehouse Advisor recommendation | Auto-lower auto-suspend only after repeated verification |
| Warehouse oversized | Proactive | Efficiency, queue, spill, p95, credits/hour | High cost with low pressure | Review downsize recommendation | Generate guarded change request |
| Runaway query cost | Reactive | Query attribution, query history | Query crosses cost/runtime threshold | Contact owner, review query text/hash | Cancel query only in final mature phase |
| Cortex/AI spend spike | Proactive | Cortex/service cost facts and `METERING_HISTORY` | Model/function/user spike or budget pace | Review Cortex settings and users | Revoke/limit access only through approval |
| Storage/failsafe growth | Proactive | Storage usage facts | Database grows above trend/threshold | Review top database/table retention | Recommend retention/table cleanup |
| Serverless/task cost spike | Proactive | `SERVERLESS_TASK_HISTORY`, service cost facts | Task cost exceeds baseline | Review task schedule and workload | Adjust schedule after approval |
| Cloud services anomaly | Proactive | `METERING_HISTORY` account service rows | Account service gap spikes | Compare with query/service activity | None until root cause known |

### 2. System and Workload Alerts

| Alert | Type | Source | Severity logic | First action | Future automation |
|---|---|---|---|---|---|
| Failed query rate/error cluster | Reactive | `FACT_QUERY_DETAIL_RECENT`, `QUERY_HISTORY` | Rate plus error-code/query-hash cluster | Group failures by query hash/error | None |
| Warehouse queue pressure | Reactive | `FACT_QUERY_HOURLY`, `QUERY_HISTORY` | Queue seconds, queued queries, p95 | Open Warehouse Health and query drilldown | Scale up only after approved policy |
| Remote/local spill pressure | Reactive/proactive | Query history spill columns | Spill volume and affected queries | Route optimization/capacity review | None initially |
| Lock/blocking pressure | Reactive | Query history blocking/transaction fields where available | Blocked seconds/query count | Identify blocker and route owner | Cancel blocker only with strict guardrails |
| Long-running query | Reactive | `QUERY_HISTORY` | Runtime threshold by warehouse/workload | Review user, role, query hash | Cancel query in final mature phase |
| Task failure | Reactive | `FACT_TASK_RUN`, `TASK_HISTORY` | Any prod failure; repeated = Critical | Open task graph and root cause | Retry safe idempotent task after policy |
| Consecutive task failure | Reactive | Recent task states | 2+ consecutive failures or critical graph | Escalate owner route | Retry/suspend only after classification |
| Task freshness/SLA late | Proactive | Task run cadence | Late vs expected interval | Route owner before downstream miss | Trigger task only if safe/idempotent |
| Task duration anomaly | Proactive | Daily task duration | p95/avg exceeds baseline | Review dependency and warehouse pressure | None initially |
| Stored procedure failure | Reactive | `FACT_PROCEDURE_RUN` | Failed `CALL` | Open Stored Procedure Advisor | None initially |
| Stored procedure degradation | Proactive | `FACT_PROCEDURE_RUN` current vs prior | p95/avg increase over baseline | Review child queries/release window | None |
| Copy/load failure | Reactive | Copy/load history where available, task logs | Failed load or repeated file error | Route data engineering owner | Re-run only for known safe retry classes |

### 3. User Behavior and Code Pattern Alerts

This is the new layer that addresses users copying bad ideas, spreading
inefficient code patterns, or causing future system issues.

| Alert | Type | Source | Detection idea | First action | Future automation |
|---|---|---|---|---|---|
| Expensive query fingerprint spreading | Proactive | `QUERY_PARAMETERIZED_HASH`, user/role/company | Same expensive hash adopted by new users or roles | Show original/expanded user cohort and sample query | Notify route/owner; no auto action |
| User cost behavior shift | Proactive | Query attribution by user/role | User exceeds own baseline or peer cohort | Review query hashes and warehouse route | Add coaching/action queue row |
| Role-level behavior shift | Proactive | Query attribution by role | Role's cost/queue/spill rises materially | Review role workload and deployment | None |
| Repeated full table scan pattern | Proactive | Query hash, bytes scanned, pruning | Same user/hash repeatedly scans high bytes | Route query optimization recommendation | None |
| Cache-hostile repeated query | Proactive | Query hash, cache %, bytes scanned | Repeated query with poor cache/pruning | Review query pattern and clustering | None |
| New high-cost user or service account | Proactive | Query attribution/login/user metadata | Newly active user/service account enters top spend | Confirm expected workload | Temporary notification only |
| Query pattern copied from bad example | Proactive | Similar query hash/text family and user cohorts | Multiple users begin running similar poor-pruning query | Identify source/cohort and publish fix guidance | None |
| Abnormal DDL/DML activity by user | Reactive | Object change fact/query history | User changes many objects/grants/warehouses | Review actor and change window | None |
| App/session misuse | Reactive | Sessions/query history | Many abandoned sessions or long transactions | Contact user/owner | Kill session only with strict approval |

Implementation note: behavior alerts should not shame users in the UI. Treat
them as coaching and system-protection signals with owner route, sample query,
cost estimate, and safer pattern guidance.

### 4. Security and Access Alerts

| Alert | Type | Source | Severity logic | First action | Future automation |
|---|---|---|---|---|---|
| Account takeover pattern | Reactive | `LOGIN_HISTORY` | Failed burst followed by successful login | Confirm user/session, reset if suspect | Disable user only after approval |
| Failed login spike | Reactive | `LOGIN_HISTORY` | User/IP spike | Review source IP and auth errors | None |
| New IP login | Proactive | `LOGIN_HISTORY` baseline anti-join | New user/IP pair | Confirm location/user | None |
| Single-factor password login | Reactive | `LOGIN_HISTORY` auth factors | Any successful password-only login | Route MFA/SSO enforcement | None |
| New MFA gap | Reactive/control gap | `USERS`, login posture | Active password user lacks MFA | Route IAM owner | Disable user only after approval |
| Privileged role grant | Reactive | `GRANTS_TO_USERS`, `GRANTS_TO_ROLES` | Admin role/ownership grant | Verify ticket and reviewer | Revoke only after approval |
| Ownership transfer | Reactive | Grants/object changes | `OWNERSHIP` grant/change | Review ownership route | None |
| Sensitive export | Reactive | Query history/access history/stages | `COPY INTO @stage`, external movement | Review query/user/stage/object | Suspend integration only after approval |
| Share or integration change | Reactive | Account usage/object changes | External share/integration change | Confirm change ticket | None |
| Suspicious object access | Proactive | `ACCESS_HISTORY` where licensed | Sensitive object accessed by new user/role | Confirm business need | None |

### 5. Alert System Health Alerts

| Alert | Type | Source | Purpose |
|---|---|---|---|
| Alert task failed | Reactive | `TASK_HISTORY`, `ALERT_RUN_HISTORY` | Prove alerting itself is healthy |
| Alert events stale | Reactive | `ALERT_EVENTS`, `OVERWATCH_ALERTS` | Detect broken materialization |
| Notification failed | Reactive | `NOTIFICATION_HISTORY`, `ALERT_NOTIFICATION_LOG` | Catch email/webhook failures |
| Suppression window hiding criticals | Proactive | `OVERWATCH_ANNOTATIONS`, alert tables | Prevent accidental blind spots |
| Threshold/rule changed | Reactive | `OVERWATCH_ALERT_RULE_AUDIT` | Audit alert config drift |
| Mart refresh stale | Reactive | `OVERWATCH_LOAD_AUDIT`, mart max timestamps | Ensure alert sources are current |

## Automation Maturity Model

### Phase 0: Detect and Document

- Alerts create evidence rows only.
- No state-changing SQL.
- Required fields: severity, company, route, owner, entity, source freshness,
  proof query, recommended action, dedupe key.

### Phase 1: Recommend and Queue

- Alerts create action queue rows with suggested action and validation query.
- The app may generate SQL previews, but execution remains outside automation.
- All risky actions stay `RECOMMEND` or `STATUS_REVIEW`.

### Phase 2: Guarded Dry Run

- The remediation engine records before-state, intended SQL, rollback guidance,
  and expected after-state.
- The job can decide "eligible" or "not eligible" but does not execute.
- Operators review false positives and tune thresholds.

### Phase 3: Human-Approved Execution

- Only allow state-changing actions with typed confirmation, route owner,
  ticket ID, before-state, rollback guidance, and verification SQL.
- Good candidates:
  - lower warehouse auto-suspend;
  - add/update resource monitor;
  - retry a known idempotent task;
  - suspend a clearly idle non-production warehouse.
- Bad initial candidates:
  - revoke grants;
  - disable users;
  - cancel queries;
  - change warehouse size;
  - execute arbitrary procedures.

### Phase 4: Policy-Based Auto Remediation

- Only after repeated successful Phase 3 outcomes.
- Use allowlisted actions and explicit policy rows.
- Automation must:
  - re-check the condition immediately before action;
  - write remediation log;
  - execute only scoped SQL;
  - verify after-state;
  - rollback or escalate if verification fails;
  - notify owner with before/after evidence.

## Snowflake-Native vs OVERWATCH Responsibilities

Use Snowflake native capabilities for:

- hard credit limits and warehouse suspension through resource monitors;
- official budget forecasts and budget notifications;
- server-side alert notifications when app is not open;
- task scheduling and triggered task execution;
- notification integrations and notification history.

Use OVERWATCH for:

- ALFA/Trexis company scoping;
- role-aware user and behavior attribution;
- query fingerprint and code-pattern analysis;
- operator triage, evidence, dedupe, suppression, and route ownership;
- remediation contracts and action queue;
- cross-domain correlation across cost, query, task, procedure, and security.

## Implementation Order

### Pass 1: Alert Source of Truth

1. Decide whether new detections write directly to `ALERT_EVENTS`.
2. Keep `OVERWATCH_ALERTS` compatibility until UI reads are migrated.
3. Add a test that confirms scheduled detections and materialization agree on
   dedupe key, status, severity, and route.

### Pass 2: Evidence-First Security Alerts

1. Account takeover pattern.
2. Single-factor password login.
3. New IP login.
4. Privileged role/ownership grant.
5. Notification/system health check for alert delivery.

### Pass 3: Cost and Behavior Alerts

1. Company contract/budget pacing.
2. User/role spend anomaly.
3. Expensive query fingerprint spreading.
4. Daily spend spike with minimum dollar guard.
5. Cortex/AI spend spike.

### Pass 4: Workload SLA Alerts

1. Task freshness/SLA late.
2. Consecutive task failures.
3. Procedure p95/average degradation.
4. Remote spill/lock pressure.
5. Copy/load failure where telemetry is available.

### Pass 5: Native Snowflake Alert SQL Generator

1. Generate Snowflake `CREATE ALERT` SQL for a small set of approved checks.
2. Include notification integration, warehouse, schedule, condition SQL,
   action SQL, and rollback/drop SQL.
3. Do not auto-create/resume native alerts from the app in this phase.

### Pass 6: Guarded Automation Framework

1. Add remediation policy table.
2. Add action allowlist.
3. Add dry-run evaluator.
4. Add human-approved execution path.
5. Later, enable policy-based automation for low-risk, reversible actions.

## Required Data Model Additions

Likely new or extended fields:

- `ALERT_EVENTS.COMPANY`
- `ALERT_EVENTS.ENVIRONMENT`
- `ALERT_EVENTS.ROLE_NAME`
- `ALERT_EVENTS.QUERY_HASH`
- `ALERT_EVENTS.QUERY_PARAMETERIZED_HASH`
- `ALERT_EVENTS.USER_COHORT`
- `ALERT_EVENTS.BASELINE_WINDOW_START`
- `ALERT_EVENTS.BASELINE_WINDOW_END`
- `ALERT_EVENTS.BASELINE_ROWS`
- `ALERT_EVENTS.CONFIDENCE`
- `ALERT_EVENTS.AUTOMATION_ELIGIBLE`
- `ALERT_EVENTS.AUTOMATION_POLICY_ID`
- `ALERT_EVENTS.DRY_RUN_STATUS`

Possible new tables:

- `ALERT_BEHAVIOR_BASELINE`
- `ALERT_REMEDIATION_POLICY`
- `ALERT_REMEDIATION_DRY_RUN`
- `ALERT_NATIVE_OBJECT_REGISTRY`

## Minimum Tests Per Alert Family

Each alert family should include tests for:

1. source SQL uses intended Snowflake views/facts;
2. ALFA/Trexis company scoping is present where possible;
3. dedupe key is stable;
4. severity threshold is deterministic;
5. proof query is present;
6. route and owner are populated;
7. suppression/dedupe prevents repeated noise;
8. remediation mode defaults to `RECOMMEND` or `STATUS_REVIEW`;
9. no dangerous SQL can enter auto mode;
10. setup/drop/validation contracts include any new objects.

## Immediate Next Steps

1. Implement Pass 1 source-of-truth decision.
2. Build security detections first because they are high-impact and currently
   the clearest gap.
3. Add behavior-pattern baselines for query fingerprints by user, role, company,
   warehouse, database, and query hash.
4. Add cost pacing and user/role spend anomalies after behavior baselines exist.
5. Add generated native Snowflake alert SQL only after detection SQL is stable.
6. Keep automation in dry-run/recommend mode until alert quality is proven.
