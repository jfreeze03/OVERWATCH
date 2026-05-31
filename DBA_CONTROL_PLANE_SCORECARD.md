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
| DBA Control Room | 84.6 | 84.6 | Operational | Admin safety/audit, governance/ownership |
| Workload Operations | 87.0 | 87.0 | Operational | None below hard-cap threshold; still below 95 on mart depth and control excellence |
| Warehouse Health | 79.9 | 79.9 | Pilot | Weak control component, data correctness, admin safety/audit, governance/ownership |
| Cost & Contract | 86.0 | 86.0 | Operational | Data correctness, admin safety/audit |
| Security Posture | 80.3 | 80.3 | Operational | Data correctness, admin safety/audit, governance/ownership |
| Change & Drift | 76.1 | 76.1 | Pilot | Weak control component, data correctness, admin safety/audit, governance/ownership |
| Account Health | 69.0 | 69.0 | Not Ready | Weak control component, data correctness, admin safety/audit, governance/ownership |

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

1. Admin Readiness panel.
2. Warehouse Settings Control Center.
3. Role & Grant Control Center owner/approval workflow and verification evidence.
4. Task/Procedure SLA Center polish.
5. Unified Action Queue upgrade.

## Scope Correction

Account Health should be demoted, merged, or re-scoped as a Daily DBA Checklist.
As a broad health page it is too generic for a 95 DBA control-plane score. It
becomes valuable only when it routes the DBA to owned actions with proof,
urgency, and verification.
