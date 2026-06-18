# Change Intelligence

Phase 2D adds mart-first change intelligence so OVERWATCH can answer:

`What changed? Who changed it? When? What was affected? Is there a possible correlation with cost, performance, security, or alert issues?`

This is not a root-cause engine. The app uses `possible correlation` unless an operator has separate evidence proving causality.

## Operating Model

Change Intelligence follows the same enterprise operating path:

`Finding -> Owner -> Trust Level -> Business Impact -> Action -> Value Verified`

The change layer helps route work by combining object-change telemetry, grant telemetry, alert events, and cost monitoring signals into normalized mart rows.

## Snowflake Objects

| Object | Purpose |
| --- | --- |
| `OVERWATCH_CHANGE_RULE` | Change category catalog, risk labels, owner routes, confidence labels, source objects, and business impact defaults. |
| `OVERWATCH_CHANGE_EVENT` | Normalized change events with object, actor, timestamp, before/after values where available, owner route, and related alert count. |
| `OVERWATCH_CHANGE_CORRELATION` | Explicit-load possible correlation rows between changes and later alert, cost, security, or workload signals. |
| `MART_CHANGE_INTELLIGENCE_SUMMARY` | Compact first-paint recent-change and risk summary for Executive Landing. |
| `SP_OVERWATCH_REFRESH_CHANGE_INTELLIGENCE` | Refreshes events, possible correlations, and summary rows from existing OVERWATCH marts. |

## Change Categories

| Category | Notes |
| --- | --- |
| Warehouse changes | Warehouse DDL and setting movement that can affect cost, queueing, auto-suspend, timeout, and workload behavior. |
| Role changes | Role DDL or role-like object changes that can alter access boundaries. |
| Grant changes | Grant/revoke telemetry from grant facts or object-change facts. |
| Task changes | Task DDL that can affect orchestration freshness and SLA. |
| Procedure changes | Stored procedure DDL that can affect workload behavior and downstream task outcomes. |
| Network policy changes | Access-control changes that can alter connectivity posture. |
| Integration changes | External access, storage, notification, or data movement integration changes. |
| Database/schema/object changes | Object DDL that can break dependent workloads or explain incident timing. |
| Security-sensitive changes | Ownership, security policy, admin, integration, and privileged-access-adjacent changes. |

## UI Placement

| Surface | Behavior |
| --- | --- |
| Executive Landing | First-paint compact summary from `MART_CHANGE_INTELLIGENCE_SUMMARY`. |
| DBA Control Room | Explicit Load for recent high-risk changes and possible correlation candidates. |
| Security Monitoring | Explicit Load for security-sensitive changes. |
| Workload Operations | Explicit Load for task, procedure, and object changes. |
| Cost & Contract | Explicit Load for changes possibly correlated to spend or warehouse pressure. |
| Alert Center | Explicit Load for related changes around alert, cost, security, and workload signals. |

## Labels

Risk labels are constrained to `Critical`, `High`, `Medium`, and `Low`.

Confidence labels are constrained to `exact`, `allocated`, `estimated`, and `fallback`.

Correlation labels are constrained to `possible correlation`. OVERWATCH should not claim root cause unless a later, separate capability stores proof.

## Safety Boundaries

- First paint reads `MART_CHANGE_INTELLIGENCE_SUMMARY` only.
- Event evidence and possible correlations require explicit Load buttons.
- No broad live `ACCOUNT_USAGE` or `INFORMATION_SCHEMA` scans are introduced on initial render.
- No silent remediation is executed.
- The refresh procedure writes OVERWATCH mart rows only.

## Manual Snowflake Validation

After deployment:

```sql
CALL SP_OVERWATCH_REFRESH_CHANGE_INTELLIGENCE();
```

Then run `snowflake/OVERWATCH_MART_VALIDATION.sql` and confirm:

- all five Change Intelligence objects exist,
- `MART_CHANGE_INTELLIGENCE_SUMMARY` has rows for all nine change types,
- risk labels are `Critical`, `High`, `Medium`, or `Low`,
- confidence labels are `exact`, `allocated`, `estimated`, or `fallback`,
- correlation labels are only `possible correlation`,
- evidence text does not make unsupported root-cause claims.

## Known Limitations

- Before values are populated only when the upstream telemetry can provide them.
- Actor quality depends on object-change and grant mart completeness.
- Grant telemetry can be allocated rather than exact when source facts do not include a direct query id.
- Correlations are timing/entity candidates only; operators still validate causality.
