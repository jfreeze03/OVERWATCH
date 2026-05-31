# DBA Control Plane Scorecard

## Purpose

This scorecard is the fixed readiness standard for OVERWATCH as a Snowflake DBA
administration control plane. It is not a feature-completeness score, a visual
polish score, or a live account-health score.

A section earns 95 only when it is ready for disciplined DBA operation: scoped
correctly, sourced defensibly, actionable, safe for administration, auditable,
performant, accountable, and tested. A section can look impressive and still be
capped below 95 if it cannot safely guide cost control, access control,
task/procedure reliability, or warehouse administration.

## Rubric

| Component | Weight | 95 Requirement |
| --- | ---: | --- |
| DBA Domain Coverage | 20 | Covers the section's assigned DBA work deeply enough to operate from it, not just observe it. |
| Data Correctness & Scope | 15 | Uses the right Snowflake sources, company and environment scope, freshness/confidence labels, and defensible formulas. |
| Actionability | 15 | Converts findings into clear next actions with severity, owner path, proof, and generated or suggested remediation. |
| Admin Safety & Audit | 15 | Every state-changing path has guardrails, confirmation, before/after context, immutable audit, and rollback guidance. |
| Performance & Mart Strategy | 10 | Reads compact mart facts by default, avoids surprise live scans, caches appropriately, and exposes source health. |
| DBA Workflow UX | 10 | Supports observe, diagnose, act, audit, and verify without burying the first move. |
| Governance & Ownership | 10 | Links objects, warehouses, roles, users, tasks, procedures, and findings to owners and approval context. |
| Tests & Operability | 5 | Has regression coverage, deployment checks, role capability checks, and clear fallback behavior. |

## Hard Caps

These caps make the score repeatable. They are enforced by
`.overwatch_final/utils/scorecards.py`.

| Condition | Maximum Score | Reason |
| --- | ---: | --- |
| Any component is below 70 | 84 | The section is not a reliable DBA operating surface. |
| Data Correctness & Scope is below 85 | 89 | The section cannot be scored as production-ready. |
| Admin Safety & Audit is below 85 | 89 | The section cannot be trusted as a control plane. |
| Governance & Ownership is below 80 | 92 | Findings are not consistently accountable. |
| Raw score is at least 95 but any component is below 90 | 94 | A 95+ score requires every rubric component to be at least 90. |
| Raw score is at least 95 but data correctness, admin safety/audit, or governance/ownership is below 95 | 94 | The critical control-plane dimensions must be excellent, not merely good. |

## Current Baseline

This is the strict DBA-control-plane baseline as of the 95% scoring reset. These
scores should not be inflated until the missing control-plane evidence exists.

| Section | Score | Raw Score | Label | Main Score Cap Drivers |
| --- | ---: | ---: | --- | --- |
| DBA Control Room | 86.9 | 86.9 | Operational | Admin safety/audit, governance/ownership |
| Alert Center | 91.8 | 91.8 | Near Target | Still below 95 on approved Snowflake email integration, owner on-call mapping, and delivery evidence replay |
| Workload Operations | 93.2 | 93.2 | Near Target | None below hard-cap threshold; still below 95 on owner/on-call enrichment and approved recovery execution audit |
| Warehouse Health | 85.3 | 85.3 | Operational | Admin safety/audit |
| Cost & Contract | 91.2 | 91.2 | Near Target | Still below 95 on verified savings closure and optional CMDB owner enrichment |
| Security Posture | 85.0 | 85.0 | Operational | Data correctness/scope, admin safety/audit |
| Change & Drift | 85.2 | 85.2 | Operational | Data correctness, admin safety/audit, governance/ownership |
| Account Health | 80.4 | 80.4 | Operational | Data correctness, admin safety/audit, governance/ownership |

## What 95 Requires

- Every component is at least 90.
- Data Correctness & Scope, Admin Safety & Audit, and Governance & Ownership are
  each at least 95.
- Every admin action is guarded, confirmed, audited, and paired with before/after
  context plus rollback guidance.
- Every database-context section respects company and environment scope.
- Login-only data without database context does not receive artificial
  environment filters.
- Cost views label database-attributed warehouse cost as allocated or estimated
  where Snowflake metering cannot prove exact PROD/DEV split.
- Every important number has source, freshness, and confidence labels.
- Mart-first queries are the default; live ACCOUNT_USAGE fallback is explicit.
- Every finding has action, owner path, status, proof, and verification evidence.

## Near-Term Priorities

1. Live warehouse-owner tags, approval closure, rollback execution evidence, and verified savings trends.
2. Live IAM/access-owner inventory, ticket integration, and automated security closure evidence.
3. Live change-ticket ingestion, source-control comparison, and approval closure automation for Change & Drift.
4. Named owner/on-call enrichment across action queue rows.
5. Live service/on-call owner integration and automated closure analytics.

## Scope Correction

Account Health is being re-scoped as a Daily DBA Checklist. It remains below
95 because broad health and briefing panels are not enough for DBA operation.
Failed checks now route to owned action-queue items with proof, urgency,
approval state, verification SQL, owner/escalation hints, and persisted trend
history. It still needs live service/on-call owner integration and automated
closure analytics before it can score as a mature DBA operating surface.

Change & Drift now stores change-control evidence snapshots with ticket,
IaC/source-control, execution-audit, owner, escalation, approver, query-id,
and blast-radius requirements. It is still capped because ticket and IaC
status are inferred from query tags/text until integrated with the real
change-management and source-control systems.

Warehouse Health now stores setting-review snapshots with owner/escalation,
approval path, rollback requirement, baseline pressure metrics, and
post-change verification SQL. It remains capped because owner routing is still
partly name/signal inferred, and rollback/savings closure is not yet proven
from executed admin audit plus after-state trend evidence.

Security Posture now separates database-context exposure from login-only and
account-role findings, stores access-review snapshots, keeps login-only rows
visible under environment filters, and requires owner, approver, ticket,
review-by, capability, and verification evidence before queue closure. It
remains capped because owner/approver routing is inferred until connected to
live IAM/access-owner inventory, ticket workflow, and closure evidence.
