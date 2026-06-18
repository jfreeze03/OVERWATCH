# Closed Loop Operations

Phase 2E moves OVERWATCH from detect/analyze/recommend into a review-gated
operating loop:

Detect -> Analyze -> Recommend -> Approve -> Execute -> Verify -> Measure.

The implementation is mart-first. Executive Landing reads only the compact
`MART_CLOSED_LOOP_OPERATIONS_SUMMARY` mart on first paint. Action queues,
approval status, review-gated SQL, rollback guidance, verification steps,
evidence, and measured value stay behind explicit Load buttons in the owning
sections.

## Snowflake Objects

| Object | Purpose |
| --- | --- |
| `OVERWATCH_ACTION_WORKFLOW` | Durable action lifecycle rows sourced from alerts, action queue entries, value-ledger items, and remediation dry-runs. |
| `OVERWATCH_ACTION_APPROVAL` | Approval-state history with approver, approval timestamp, risk, owner route, and business impact. |
| `OVERWATCH_ACTION_EXECUTION_PLAN` | Review-gated SQL/action text, rollback guidance, verification steps, and execution safety flags. |
| `OVERWATCH_ACTION_VERIFICATION` | Post-action verification status, verification window, evidence, expected savings, and actual verified savings. |
| `OVERWATCH_ACTION_EVIDENCE` | Evidence trail for workflow, source telemetry, rollback notes, verification proof, and closure context. |
| `MART_CLOSED_LOOP_OPERATIONS_SUMMARY` | Compact first-paint summary by company, environment, and action domain. |
| `SP_OVERWATCH_REFRESH_CLOSED_LOOP_OPERATIONS` | Refreshes the closed-loop marts from existing OVERWATCH facts. It does not execute remediation SQL. |

## UI Placement

| Section | Panel | Load behavior |
| --- | --- | --- |
| Executive Landing | Closed Loop Operations | First-paint summary from `MART_CLOSED_LOOP_OPERATIONS_SUMMARY`. |
| DBA Control Room | Closed Loop Operations | Explicit Load for action queue, review plans, and verification queue. |
| Alert Center | Alert Action Workflows | Explicit Load for alert and incident action workflows. |
| Cost & Contract | Savings Verification Workflow | Explicit Load for expected versus actual verified savings. |
| Workload Operations | Operational Action Workflow | Explicit Load for workload and operational remediation plans. |
| Security Monitoring | Security Action Approval Workflow | Explicit Load for security approvals and review-gated security plans. |

## Safety Model

- No silent execution.
- No auto-remediation without explicit approval.
- Dangerous SQL/action text is review-gated.
- OVERWATCH does not execute `ALTER`, `CREATE`, `DROP`, `GRANT`, `REVOKE`,
  `SUSPEND`, or `RESUME` actions from Phase 2E panels.
- `OVERWATCH_ACTION_EXECUTION_PLAN.EXECUTION_ALLOWED_IN_APP` is always false
  for generated plans.
- Execution status is stored as review state, not proof that Snowflake was
  changed by the app.
- Actual verified savings require post-action telemetry in
  `OVERWATCH_ACTION_VERIFICATION`.
- Forecasted or expected savings do not count as actual verified savings.

## Manual Snowflake Validation

After deploying DDL, run:

```sql
CALL SP_OVERWATCH_REFRESH_CLOSED_LOOP_OPERATIONS();
```

Then run `snowflake/OVERWATCH_MART_VALIDATION.sql` and confirm:

- `MART_CLOSED_LOOP_OPERATIONS_SUMMARY` has recent rows.
- `OVERWATCH_ACTION_WORKFLOW` has lifecycle rows from alerts, action queue,
  value ledger, or dry-run policy sources when those sources contain data.
- approval status values are constrained to expected labels.
- verification status values are constrained to expected labels.
- `OVERWATCH_ACTION_EXECUTION_PLAN.EXECUTION_ALLOWED_IN_APP` is false.
- generated review SQL/action text is present only as review evidence.
- actual verified savings do not exceed expected savings without explicit
  post-action evidence.

## Known Limits

- Phase 2E records and summarizes action state. It does not replace ticketing,
  IAM approval, Snowflake change management, or human review.
- Source quality depends on existing action queue, alert, value ledger, and
  remediation dry-run rows.
- External execution can be recorded, but external execution proof must be
  validated manually until a later integration is deliberately added.
