# OVERWATCH DBA Control Plane Scorecard

Last updated: June 6, 2026

The scorecard is a strict production-readiness rubric. A section should not
score as production-grade because it has many charts. It scores well when it
has trusted evidence, owners, safe actions, verification, and low-friction DBA
workflows.

## Scoring Dimensions

| Dimension | Weight | What earns credit |
|---|---:|---|
| Data correctness | 20 | Uses the right Snowflake source, grain, formula, freshness label, and regression coverage. |
| Operator value | 20 | Shows the exception, owner, impact, and next action before raw detail. |
| Admin safety | 15 | Guarded execution, typed confirmation, audit writes, rollback, and failure evidence. |
| Closed-loop verification | 15 | Proves whether an action worked and updates the queue/reporting state. |
| Governance and ownership | 15 | Owner, approver, ticket/control evidence, escalation path, and service tier are visible. |
| Performance and cost | 10 | Mart-first, cached/deferred heavy loads, no unnecessary live scans, low runtime cost. |
| UX clarity | 5 | Current labels, compact layout, no stale/internal/test language, chart/data toggle paths. |

## Hard Caps

A section cannot exceed the listed score while any cap condition is true.

| Cap | Maximum | Trigger |
|---|---:|---|
| Formula uncertainty | 80 | Cost, credit, freshness, or scope formula is ambiguous or untested. |
| No owner route | 85 | High-severity rows cannot identify owner/approval/escalation. |
| Unsafe admin action | 85 | Production-impacting action lacks audit, rollback, or failure-path evidence. |
| No verification loop | 90 | Recommendations can be marked done without post-action proof. |
| Heavy first load | 90 | Section performs expensive scans or renders large tables on entry. |
| Stale UX or labels | 92 | Visible labels, help text, docs, or comments use retired terminology. |
| Manual-only process | 94 | Required evidence exists externally but must be pasted manually. |

These are scoring caps for individual control-plane gaps, not a production
readiness rating. Production readiness is proven by external gates such as CI,
section render smoke, mart validation, secret scan, role smoke, first-paint scan
guard, and ordered SQL deployment.

## Current Production Targets

| Section | Target behavior |
|---|---|
| Executive Landing | Paste-ready KPI summary with cost, risk, incidents, verified wins, and open governance blockers. |
| DBA Control Room | Top priority brief, exception queue, live state where needed, and action routing. |
| Alert Center | Alert rules, owner routing, digest packaging, delivery state, and escalation evidence. |
| Account Health | Exceptions-first account checklist with source health and DBA next action. |
| Cost & Contract | Formula-aligned cost overview, spend RCA, contract pacing, Cortex spend, and verified savings. |
| Workload Operations | Live query/task/procedure status, Control-M style job state, errors, and performance indicators. |
| Warehouse Health | Capacity/efficiency/settings evidence with safe changed-only admin workflows. |
| Security Posture | MFA/login/grant/share posture with owners and remediation routes. |
| Change & Drift | Object/schema/change evidence with Terraform, Jira, Flyway, Git, and approval context. |
| Architecture Readiness | Objectives, source health, ownership, future-platform controls, and evidence register. |

## Minimum Evidence For High-Risk Rows

Every high-risk row should carry:

1. severity
2. business impact
3. owner or route
4. source and freshness
5. proof query or evidence link
6. recommended next action
7. rollback or non-action rationale when relevant
8. verification method

## Production Review Checklist

Use this checklist before calling a section production-ready:

1. Are all cost formulas documented and tested?
2. Are current-state metrics using live sources where needed?
3. Are delayed Snowflake sources labeled by freshness?
4. Are exceptions shown before bulk tables?
5. Is the first render fast enough for morning triage?
6. Are admin actions guarded and audited?
7. Does closure require verification evidence?
8. Are owners, approvers, and tickets visible where needed?
9. Are old labels, aliases, and internal build/test terms absent from the UI?
10. Can an executive summary be produced without manually reconstructing the
    numbers?

## Scorecard Principle

The best OVERWATCH section is not the one with the most widgets. It is the one
that tells the DBA what matters, what proof exists, who owns it, what to do
next, and whether the fix worked.
