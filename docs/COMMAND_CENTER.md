# Command Center

Phase 2F adds OVERWATCH's correlated Command Center. It helps operators and
leaders answer:

- Why did costs spike?
- Why is this warehouse slow?
- What changed recently?
- Why did this fail?
- What should I do next?
- What is the business impact?
- Who owns this?
- What evidence supports the recommendation?
- What value can be created or protected?

The Command Center is mart-first. Executive Landing first paint uses the
current section command brief packet, then renders a command-center dashboard
from packet-safe values. Finding, evidence, and recommendation detail are
explicit Load only.

## Snowflake Objects

| Object | Purpose |
| --- | --- |
| `OVERWATCH_COMMAND_CENTER_QUESTION` | Investigation catalog for cost spike, warehouse slow, recent change, failure/SLA, security risk, and executive risk questions. |
| `OVERWATCH_COMMAND_CENTER_FINDING` | Deterministic root-cause candidate findings with evidence summary, owner route, related changes, alerts, scorecard drivers, forecasts, action refs, value/risk, and verification path. |
| `OVERWATCH_COMMAND_CENTER_EVIDENCE` | Evidence rows tied to each finding and source object. |
| `OVERWATCH_COMMAND_CENTER_RECOMMENDATION` | Review-gated recommended actions tied to closed-loop execution plan references when available. |
| `MART_COMMAND_CENTER_SUMMARY` | Compact first-paint summary by investigation type. |
| `SP_OVERWATCH_REFRESH_COMMAND_CENTER` | Refreshes findings, evidence, recommendations, and compact summary rows from existing OVERWATCH marts. |
| `MART_EXECUTIVE_COMMAND_CENTER_KPI` | Packet-aligned KPI strip values for the Executive Landing command-center presentation. |
| `MART_EXECUTIVE_COMMAND_CENTER_TIMESERIES` | Compact command-center trend points for packet-backed Executive Landing visuals. |
| `MART_EXECUTIVE_COMMAND_CENTER_WAREHOUSE` | Warehouse credit split used by the Executive Landing warehouse donut when refreshed data exists. |
| `MART_EXECUTIVE_COMMAND_CENTER_ALERTS` | Compact recent-status rows derived from command brief exceptions and top signals. |
| `MART_EXECUTIVE_COMMAND_CENTER_CONTEXT` | Compact operational-context rows for source, freshness, evidence, and snapshot status. |
| `SP_OVERWATCH_REFRESH_EXECUTIVE_COMMAND_CENTER` | Refreshes the Executive Landing command-center presentation marts from existing packet/fact marts without querying live account history. |

## UI Placement

| Section | Panel | Load behavior |
| --- | --- | --- |
| Executive Landing | Command Center | First-paint dashboard from the current section command brief packet; the new presentation marts are refresh/setup proof and future packet feeders. |
| DBA Control Room | Command Center Investigations | Explicit Load for findings, evidence, and recommendations. |
| Alert Center | Alert Command Findings | Explicit Load for alert and incident-related findings. |
| Cost & Contract | Cost Command Findings | Explicit Load for cost-spike investigations. |
| Workload Operations | Workload Command Findings | Explicit Load for warehouse slow and failure/SLA investigations. |
| Security Monitoring | Security Command Findings | Explicit Load for security-risk investigations. |

## Causality Wording

Command Center language must stay conservative:

- use `root-cause candidate` when evidence suggests a plausible driver,
- use `likely driver` for strong deterministic signals,
- use `possible correlation` for timing/entity proximity,
- do not claim causality unless a future proof workflow explicitly verifies it.

## Non-AI Explanation Strategy

The Command Center does not require Cortex or any AI call. The required path is
deterministic and uses compact marts:

- cost, query, task, alert, and freshness summaries,
- scorecard drivers,
- forecasts,
- change intelligence,
- closed-loop operations,
- ownership coverage,
- value ledger,
- production readiness,
- data trust.

Optional AI/Cortex summarization can be added later only as a clearly labeled
assistive layer. It must not be required for first paint and must not replace
the deterministic evidence.

## Safety Model

- No silent remediation.
- No auto-remediation.
- No broad live `ACCOUNT_USAGE`, `INFORMATION_SCHEMA`, `SHOW`, or query-history
  scans on initial render.
- Generated SQL/action plans remain review-gated through Closed Loop
  Operations.
- Command Center recommendations do not execute `ALTER`, `CREATE`, `DROP`,
  `GRANT`, `REVOKE`, `SUSPEND`, or `RESUME`.
- Expected value/risk is not realized value until verification evidence exists.

## Manual Snowflake Validation

After deploying DDL, run:

```sql
CALL SP_OVERWATCH_REFRESH_COMMAND_CENTER();
CALL SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS();
CALL SP_OVERWATCH_REFRESH_EXECUTIVE_COMMAND_CENTER();
```

Then run `snowflake/OVERWATCH_MART_VALIDATION.sql` and confirm:

- `MART_COMMAND_CENTER_SUMMARY` has rows for all six investigation types,
- confidence labels are `exact`, `allocated`, `estimated`, or `fallback`,
- causality labels are `root-cause candidate`, `likely driver`, or
  `possible correlation`,
- no finding overclaims root cause,
- recommendations are review-gated,
- execution plan references point to Closed Loop Operations when available,
- no remediation SQL was executed by the refresh procedure.
- Executive command-center marts exist, refresh cleanly, and are covered by
  `OVERWATCH_MART_VALIDATION.sql`.
