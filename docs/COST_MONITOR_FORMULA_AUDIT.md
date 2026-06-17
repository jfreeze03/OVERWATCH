# COST_MONITOR Formula Audit

Source reference:
`C:/Users/jfree/Downloads/COST_MONITOR_DB.txt`

Source dashboard identifier:
Snowflake Streamlit Cost Monitoring Dashboard, optimized version,
code version `2025-03-04-A`.

This audit records how OVERWATCH cost metrics reconcile to the original
COST_MONITOR dashboard formulas. The goal is not to force every OVERWATCH
surface back to the original formulas. The goal is to make formula changes
intentional, visible, and testable.

## High Confidence Parity

| Metric family | Source dashboard formula | OVERWATCH basis | Status |
| --- | --- | --- | --- |
| Monthly service costs | `METERING_HISTORY` by `SERVICE_TYPE`, current/prior periods, completed 24-hour window | Same official account service source, with compute/cloud/total credit split and configured dollar rates | Aligned |
| Warehouse consumption | `WAREHOUSE_METERING_HISTORY`, compute plus cloud services, active warehouses | Same warehouse metering source, with OVERWATCH company scope and completed windows where billing-facing | Aligned with scope change |
| SPCS | `SNOWPARK_CONTAINER_SERVICES_HISTORY.CREDITS_USED` | SPCS tracker uses the same source; service lens classifies SPCS as managed service spend | Aligned |
| Automatic clustering | `AUTOMATIC_CLUSTERING_HISTORY.CREDITS_USED` | Clustering helper uses the same source; service summaries classify clustering as managed service spend | Aligned |
| Service period movement | Current period minus previous period divided by previous period | Same current/prior movement pattern in official service-cost lens | Aligned |

## Intentional Formula Changes

| Metric family | Source dashboard formula | OVERWATCH basis | Why it changed |
| --- | --- | --- | --- |
| Credit price | Source dashboard defaulted mostly to `$2.00` with local `$3.00`/`$4.00` usages | Settings-driven compute credit rate, defaulting to the OVERWATCH contract value, with a separate Cortex/AI credit rate | Contract rates replaced legacy demo defaults |
| Service dollars | `TOTAL_CREDITS * credit_price` | Snowflake services use compute credit price; Cortex/AI services use AI credit price | Prevents AI credits from being dollarized at the compute rate |
| Cloud services | `QUERY_HISTORY.CREDITS_USED_CLOUD_SERVICES` for successful query overhead | `METERING_HISTORY` service totals for billing reconciliation plus warehouse cloud-service split where exposed | Query history overhead is useful, but it is not the full service bill |
| Query/client cost | Client cost was query-level cloud-services credits only | Prefer `QUERY_ATTRIBUTION_HISTORY`; otherwise allocate metered warehouse compute by query execution share | More complete workload cost, still labeled allocated |
| Forecast | Annual all-service projection from YTD `METERING_HISTORY` and observed recent-day average | 30-day warehouse forecast from `WAREHOUSE_METERING_HISTORY`, zero-filled calendar days | DBA operating forecast, not an annual contract forecast |
| Company chargeback | Account-wide | ALFA/Trexis warehouse/database/user/environment boundaries | Required for OVERWATCH's operational scope |

## Gaps To Fix Or Keep Explicit

| Metric family | Source dashboard formula | Current OVERWATCH gap | Recommended next step |
| --- | --- | --- | --- |
| Storage footprint | Database, stage, failsafe, hybrid, archive cool, and archive cold bytes | OVERWATCH storage surfaces focus on database/failsafe/stage; hybrid/archive are not fully surfaced | Add account-wide hybrid/archive storage rows with clear non-company-scoped labeling |
| Storage dollars | Standard TB at `$23/TB/month`, hybrid GB at `$0.34/GB/month`, archive cool TB at `$4/TB/month`, archive cold TB at `$1/TB/month` | OVERWATCH applies one configured standard storage rate to total storage TB | Split storage cost formulas by storage class before contract reconciliation |
| Cortex details | Cortex REST API, Intelligence, Agents, Functions, Analyst, Search, Document AI, Fine-Tuning, Cortex Code | OVERWATCH has broad AI/Cortex service billing plus Cortex Code and optional AI Functions detail | Add explicit-load detail panes for enabled Cortex sub-services |
| Annual service projection | YTD `METERING_HISTORY` daily credits plus recent observed-day annualization | OVERWATCH has a 30-day warehouse forecast instead | Add a separate annual service projection only if leadership wants the original dashboard view back |
| Replication drilldown | `REPLICATION_GROUP_USAGE_HISTORY` | Account service movement is covered; detailed replication group spend is not first-class | Add only if replication spend becomes material |
| Serverless task drilldown | `SERVERLESS_TASK_HISTORY` | Account service movement is covered; task health is operational | Use `SERVERLESS_TASK_HISTORY` for task-specific cost detail if needed |

## DBA Rule

When a cost formula changes, update:

1. `.overwatch_final/utils/compatibility.py::build_cost_formula_audit`
2. Any affected cost SQL helper or shared metric loader
3. `tests/test_formula_regressions.py`
4. This document
5. `docs/IMPLEMENTATION_NOTES.md` when the implementation changes user-facing behavior
