# OVERWATCH Alert Command Center Runbook

## Purpose

The Alert Center should tell a DBA what is risky, expensive, broken, late, or
worth optimizing before it becomes an incident. It is not just a message list.
It is the operating layer for detection, priority, ownership, notification,
acknowledgement, suppression, remediation approval, and closure proof.

## Setup Objects

Run `snowflake/OVERWATCH_MART_SETUP.sql` with a role allowed to create objects
in the OVERWATCH schema. The command-center contract creates:

- `ALERT_CONFIG`
- `ALERT_EVENTS`
- `ALERT_RUN_HISTORY`
- `ALERT_ACKNOWLEDGEMENTS`
- `ALERT_REMEDIATION_LOG`
- `ALERT_NOTIFICATION_LOG`
- `ALERT_THRESHOLDS`
- `ALERT_OWNER_ROUTING`
- `ALERT_DATA_QUALITY_CHECKS`

`ALERT_THRESHOLDS` and `ALERT_CONFIG` are seeded with default security,
Cost/FinOps, performance, task/pipeline, data-quality, and optimization signals.
Tune thresholds by updating the tables, not the Streamlit code.

Use `ALERT_DATA_QUALITY_CHECKS` for metadata-driven checks. Each row defines the
database, schema, table, column, check type, threshold, severity, owner,
notification channel, and enabled flag. Keep starter rows disabled until the
owning data team confirms the SLA and expected volume/null/duplicate behavior.

The Setup pane also generates event materialization SQL. Schedule it only after
the alert source views are populated; it merges `OVERWATCH_ALERT_TRIAGE_V` rows
into `ALERT_EVENTS` with a dedupe key, owner, severity, recommended action, proof
query, and run-history row.

## Required Privileges

- Imported privileges on the `SNOWFLAKE` database for `ACCOUNT_USAGE` views.
- `USAGE` on monitored databases and schemas for `INFORMATION_SCHEMA` checks.
- `SELECT` on OVERWATCH tables and views for the Streamlit role.
- State-changing privileges only for approved remediation workflows.
- Notification integration usage only when email/webhook/cloud routing is
  approved.

## Optional Integrations

- Snowflake `ALERT` objects for scheduled condition checks.
- Email notification integration for `SYSTEM$SEND_EMAIL`.
- Webhook, Slack, Teams, or cloud messaging integrations where allowed.
- Event tables with task/stored procedure logging and `LOG_LEVEL` at least
  `ERROR`.
- ITSM/Jira/Control-M bridge for ticket, owner, and pipeline lifecycle sync.

## Telemetry Freshness

`SNOWFLAKE.ACCOUNT_USAGE` views are authoritative for historical proof, but many
of them can lag. Label those checks as delayed. For near-real-time triage, use
`INFORMATION_SCHEMA` table functions, Snowflake task graph notifications,
Snowflake `ALERT` objects, and event tables where configured.

## Daily DBA Flow

1. Open Alert Center, then load Command Center or DBA Morning Brief.
2. Work the Incident Action Board in priority order. It combines severity, SLA
   age, owner, ticket state, proof query, source freshness, and remediation
   mode.
3. Work Critical and High rows first.
4. Check Security, Cost/FinOps, Performance, and Task/Pipeline before
   optimization items.
5. Use the proof query and freshness note before declaring an incident.
6. Acknowledge, suppress, or resolve only with an evidence note.
7. Route owner-backed work to the action queue with ticket, approver,
   verification SQL, and closure proof.

## Remediation Policy

Default mode is `RECOMMEND`. Dangerous actions require approval:

- Cancel query.
- Suspend or resize warehouse.
- Resume or retry task graph.
- Disable user.
- Revoke grant.
- Change policy, network, stage, integration, or task settings.

Every remediation must log trigger, timestamp, actor, approval, SQL/action,
before state, after state, result, rollback guidance, affected object, and
verification result in `ALERT_REMEDIATION_LOG`.

## Alert Families

Security:
Failed login spikes, privileged role grants, unusual access, sensitive exports,
public/broad grants, ownership changes, policy removal, and share changes.

Cost/FinOps:
Warehouse metering spikes, long-running warehouses, auto-suspend gaps,
multi-cluster changes, serverless task cost, cloud-services ratio, storage
growth, retries, and budget threshold risk.

Performance:
Long-running, queued, blocked, spilled, high-scan, low-pruning, explosive-join,
full-scan, timeout, and degraded-query patterns.

Task/Pipeline:
Task failures, skipped runs, late runs, task graph failures, stored procedure
failures, COPY failures, dynamic table refresh failures, stream backlog, and
SLA misses.

Data Quality:
Metadata-driven freshness, row-count, null-rate, duplicate, schema-change,
cardinality, load-volume, and invalid-value checks.

Optimization:
Oversized/undersized warehouses, unused warehouses/tables/roles/users, stale
transient objects, repeated expensive queries, cache misses, and objects that
need clustering or search optimization review.
