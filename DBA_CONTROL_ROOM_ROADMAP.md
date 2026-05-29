# OVERWATCH DBA Control Room Roadmap

## Target

OVERWATCH is a DBA command center and executive evidence engine. Executives do not use the app directly. DBAs use it to triage Snowflake operations, investigate root cause, control cost, validate security/governance posture, and produce report-ready leadership summaries.

The red-team target is 95+ across DBA usefulness, Snowflake engineering depth, operational readiness, executive reporting support, UX for working DBAs, and risk/control maturity.

## Operating Model

The app should route work by DBA workflow:

- Morning triage: failures, queue pressure, cost spikes, suspicious access, object changes, open recommendations.
- Incident investigation: query, warehouse, task, stored procedure, user, role, object, and cost impact.
- Cost control: explain spend changes, identify owners, estimate savings, and track remediation.
- Security and audit: logins, grants, MFA, object changes, data sharing, and proof queries.
- Admin actions: controlled warehouse, task, and query operations with confirmation and audit logging.
- Executive evidence: concise summaries that quantify impact, risk, owner, and recommended action.

## Current High-Value Foundation

- DBA Control Room landing page.
- Consolidated Query Workbench for live triage, diagnosis, patterns, and history search.
- Consolidated Cost & Contract workflow for bill explanation, contract pacing, recommendations, value evidence, Cortex, and SPCS spend.
- Consolidated Security Posture workflow for access posture and data-sharing exposure.
- Consolidated Change & Drift workflow for object changes, stored procedure lineage, drift checks, and controlled DBA tools.
- Exceptions-only operating mode for DBA morning triage.
- Account Health command center and report exports.
- Metered warehouse-credit allocation.
- Company scoping for ALFA, Trexis, and ALL.
- Query budget telemetry.
- Recommendations/action queue.
- Warehouse health and optimization advisor.
- Security/access monitoring behind the Security Posture workflow.
- Object-change monitoring behind the Change & Drift workflow.
- Task management and Change & Drift controls.
- Cost formula audit and monitoring-cost panel.

## Remaining Work To Reach 95+

1. Continue splitting Change & Drift controls by risk level.
   - Safe Observability.
   - Controlled Actions.
   - Setup and Maintenance.
   - Add action audit logging for every destructive or state-changing command.

2. Build a persistent semantic mart.
   - Task or dynamic-table aggregates for daily cost, failures, warehouse pressure, storage growth, grants, logins, and object changes.
   - Keep live queries only for true operational needs.

3. Harden company scoping.
   - Create one reusable ownership mapping table for database, warehouse, role, user, task, and application.
   - Stop relying only on naming conventions as the enterprise grows.

4. Make recommendations operational.
   - Every recommendation needs owner, status, severity, confidence, estimated savings, proof query, generated SQL fix, notes, and due date.

5. Improve executive evidence.
   - Add weekly cost report, incident report, optimization win report, governance change report, and contract-risk report.
   - Keep exported language factual and source-backed.

6. Add confidence and freshness everywhere.
   - Exact, Allocated, Estimated, Account-wide, Forecast.
   - ACCOUNT_USAGE, INFORMATION_SCHEMA, ORGANIZATION_USAGE, session-local.

7. Add RCA narratives.
   - Explain cost spikes and incidents across query, user, warehouse, task, stored procedure, object change, and time window.

8. Add test coverage.
   - Unit tests for SQL builders, company filters, scoring formulas, route mappings, and no-HTML-leak rendering helpers.
   - Smoke-test checklist for Snowflake role capabilities.

## Design Rules

- No metric without action.
- No chart without an owner, risk, trend, or decision.
- No admin action without confirmation and logging.
- No cost number without confidence.
- No live query where a pre-aggregated mart can answer the question.
- No executive report without proof data behind it.
