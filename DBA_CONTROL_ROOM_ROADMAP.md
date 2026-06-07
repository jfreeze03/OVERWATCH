# OVERWATCH DBA Control Room Roadmap

Last updated: June 6, 2026

The roadmap target is a closed-loop Snowflake DBA operating platform:

```text
Detect -> explain -> route -> act -> verify -> report
```

OVERWATCH already has the foundations: mart-first telemetry, role-aware
sections, action queue, alert ledger, owner routing, cost attribution, warehouse
evidence, security posture, change evidence, executive packets, and automation
objects. The remaining work is focused on closure and production polish.

## Current Foundation

| Capability | Current state |
|---|---|
| DBA triage | DBA Control Room and Account Health show exceptions, source health, and action routing. |
| Cost governance | Cost & Contract explains spend, attributes warehouse/user/role cost, tracks Cortex spend, and supports savings verification. |
| Workload operations | Query/task/procedure status, pipeline health, errors, and Control-M style job evidence are consolidated in Workload Operations. |
| Warehouse governance | Warehouse Health tracks pressure, settings, rollback context, and verified action evidence. |
| Security governance | Security Posture surfaces MFA/login/grant/sharing evidence with owner-ready rows. |
| Change governance | Change & Drift combines object changes, schema compare, Terraform/Jira/Flyway/Git evidence, and approval context. |
| Architecture readiness | Architecture Readiness holds objectives, source health, future Snowflake controls, and control register evidence. |
| Executive interface | Executive Landing provides board-ready KPIs, charts, and copyable narrative. |

## Priority 1: Closed-Loop Verification

The highest-value improvement is automatic closure proof.

Target behavior:

1. A DBA action is created with owner, severity, proof query, and expected
   savings or risk reduction.
2. The action is executed through a guarded workflow.
3. Audit rows capture success or failure.
4. Scheduled verification compares post-action evidence to baseline.
5. The action queue updates to `VERIFIED_SAVED`, `VERIFIED_NO_CHANGE`, or
   `NEEDS_REVIEW`.
6. Executive packets and cost governance include the verified result.

Primary objects:

- `OVERWATCH_ACTION_QUEUE`
- `OVERWATCH_ADMIN_ACTION_AUDIT`
- `OVERWATCH_WORKLOAD_RECOVERY_AUDIT`
- `OVERWATCH_COST_SAVINGS_VERIFY`
- `OVERWATCH_AUTOMATION_RUN`

## Priority 2: Real Alert Delivery

Alert Center already prepares owner-routed alert content. The production gap is
delivery.

Target behavior:

- critical alerts send through Snowflake email notification integration
- daily digest sends automatically
- dry-run mode remains available for testing
- delivery success/failure is written to `OVERWATCH_ALERTS`
- repeated failures become action queue items

## Priority 3: External Control Evidence

OVERWATCH should not require DBAs to manually paste proof when proof already
exists in another system.

Priority feeds:

| Feed | Evidence |
|---|---|
| Control-M | task/job status, start/end time, duration, SLA, error text, owner, run id. |
| Jira | ticket id, approval state, approver, closure, linked object, target release. |
| Terraform | plan/apply state, drift result, workspace, module, resource, actor. |
| Flyway | migration id, schema, checksum, status, installed by, execution time. |
| Git | commit, branch, PR, reviewer, deployment tag, changed files. |

These should land in `OVERWATCH_EXTERNAL_CONTROL_FEED` or a dedicated evidence
table when the feed needs richer history.

## Priority 4: Ownership Everywhere

Owner inference from names is useful, but production governance needs declared
ownership.

Target owner sources:

1. Snowflake object tags
2. `OVERWATCH_OWNER_DIRECTORY`
3. approved external ownership feed
4. fallback route only when no stronger owner exists

The owner record should include owner email, on-call owner, backup, approval
group, escalation target, service tier, and default route.

## Priority 5: Mart-First Performance

Every section should follow the same performance pattern:

1. render action brief and primary metrics quickly
2. use mart facts for default evidence
3. use static metadata for filters where possible
4. put heavy inventories and source health behind explicit load gates
5. show clear load state for multi-second operations

Section smoke should stay part of release validation.

## Priority 6: Cost RCA Narratives

Cost & Contract should explain not just what changed, but why.

Target narrative inputs:

- top warehouse movement
- top user or role movement
- top Cortex user/spend
- query pattern movement
- task/procedure failures or duration spikes
- warehouse setting changes
- schema/deployment/change evidence
- action queue status and verification outcome

The output should be paste-ready for executive updates.

## Priority 7: UX Cleanup

The production UI should stay compact and operator-focused.

Standards:

- topbar filters for common triage inputs
- exception-first rendering
- no deep tab nesting
- no internal build/test metrics in user UI
- explicit load buttons for heavy evidence
- chart/data toggle paths
- consistent section labels
- current navigation group order:
  Command Center, Financial Control, Operations, Governance, Architecture

## Priority 8: Test Coverage

Add or maintain tests for:

- cost formula source labels
- company and environment scope
- role/experience view access
- SQL builders and setup DDL
- admin audit write behavior
- alert digest packaging
- external feed parsing
- action queue verification state
- navigation and stale label prevention

## Release Principle

Do not add surface area that cannot be owned, verified, or explained. OVERWATCH
is strongest when every chart, table, action, and executive bullet can point to
source evidence.
