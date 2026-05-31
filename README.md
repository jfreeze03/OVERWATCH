# OVERWATCH

OVERWATCH is a Streamlit-based Snowflake DBA command center for account health,
cost attribution, warehouse performance, security posture, object change
monitoring, and operational recommendations.

Start daily work in the DBA Control Room. It triages exceptions, routes DBAs
into specialist tools, and produces report-ready leadership evidence without
requiring executives to access the app.

Use Query Workbench for query incidents. It consolidates live triage,
slow-query diagnosis, pattern analysis, and historical query search into one
DBA workflow.

Use the DBA Workflows group for investigations:

- Query Workbench consolidates live query triage, diagnosis, pattern analysis,
  and history search.
- Warehouse Health consolidates scaling, efficiency, spill, heatmap, and
  optimization work.
- Cost & Contract consolidates bill explanation, cost attribution, contract
  utilization, recommendations, Snowflake value, Cortex, and SPCS spend.
- Security Posture consolidates login posture, MFA, grants, exfiltration,
  lineage, and data sharing exposure.
- Change & Drift consolidates object/access changes, stored procedure lineage,
  schema/object drift checks, dynamic tables, replication, and DBA controls.

Cost & Contract's Explain This Bill tab is the starting point for billing
questions. It compares exact warehouse-metered credits to the prior comparable
period, identifies the largest warehouse and workload deltas, calls out
unallocated/idle overhead, and exports a report-ready explanation for
leadership follow-up.

## Quick Start

Streamlit Community Cloud settings:

- Repository: `jfreeze03/OVERWATCH`
- Branch: `main`
- Main file path: `streamlit_app.py`

Local run:

```powershell
.\run_overwatch_local.ps1
```

Production Snowflake mart setup:

- Run `snowflake/OVERWATCH_MART_SETUP.sql` in Snowflake to create the low-cost
  OVERWATCH mart schema, persistence tables, refresh procedures, and scheduled
  tasks.
- The mart uses an X-Small `OVERWATCH_WH` with 60-second auto-suspend and
  incremental hourly/daily loads so the Streamlit app can read compact tables
  instead of repeatedly scanning `SNOWFLAKE.ACCOUNT_USAGE`.

For full setup, feature notes, Snowflake grants, and operating guidance, see
[OVERWATCH_DOCUMENTATION.md](OVERWATCH_DOCUMENTATION.md).

For the low-cost Snowflake mart design, table inventory, and task load flow, see
[SNOWFLAKE_ARCHITECTURE.md](SNOWFLAKE_ARCHITECTURE.md).

For the workflow roadmap and 95+ red-team target, see
[DBA_CONTROL_ROOM_ROADMAP.md](DBA_CONTROL_ROOM_ROADMAP.md).

For the strict DBA control-plane scoring rubric, hard caps, and current section
baseline, see [DBA_CONTROL_PLANE_SCORECARD.md](DBA_CONTROL_PLANE_SCORECARD.md).
