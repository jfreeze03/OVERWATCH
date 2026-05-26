# OVERWATCH Documentation

Last updated: May 26, 2026

OVERWATCH is a Snowflake usage, cost, performance, security, and DBA operations
dashboard built with Streamlit. The active application lives in
`.overwatch_final/app.py` and is deployed from the `main` branch.

## Deployment Targets

The repository supports two primary runtimes:

- Streamlit Community Cloud, using root `requirements.txt`
- Snowflake Streamlit-in-Snowflake, using `.overwatch_final/environment.yml`

Streamlit Community Cloud settings:

```text
Repository: jfreeze03/OVERWATCH
Branch: main
Main file path: .overwatch_final/app.py
```

Local Windows run:

```powershell
.\run_overwatch_local.ps1
```

Manual local run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run .overwatch_final/app.py
```

## Required Secrets

Do not commit credentials. For Streamlit Community Cloud, add a Snowflake
connection block in app secrets:

```toml
[connections.snowflake]
account = "your_account_identifier"
user = "your_user"
password = "your_password"
role = "SNOW_ACCOUNTADMIN"
warehouse = "COMPUTE_WH"
database = "DBA_MAINT_DB"
schema = "OVERWATCH"
```

For local development, use the same block in `.streamlit/secrets.toml`.

## Required Snowflake Access

The runtime role needs visibility into Snowflake account usage and access to the
OVERWATCH persistence schema.

```sql
GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE <role>;
GRANT MONITOR ON ACCOUNT TO ROLE <role>;
GRANT USAGE ON DATABASE DBA_MAINT_DB TO ROLE <role>;
GRANT USAGE ON SCHEMA DBA_MAINT_DB.OVERWATCH TO ROLE <role>;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA DBA_MAINT_DB.OVERWATCH TO ROLE <role>;
GRANT SELECT, INSERT, UPDATE, DELETE ON FUTURE TABLES IN SCHEMA DBA_MAINT_DB.OVERWATCH TO ROLE <role>;
```

Some DBA actions, such as warehouse setting changes, query cancellation, task
control, and account parameter changes, require elevated Snowflake privileges.

## Application Structure

```text
.overwatch_final/
  app.py                 Main Streamlit entry point
  config.py              Defaults, thresholds, company filters, role navigation
  theme.py               Theme engine and theme picker
  sections/              Feature modules
  utils/                 Session, SQL, display, bookmarks, alerts, cost helpers
  util/                  Legacy compatibility helpers
  environment.yml        Snowflake Streamlit package list
```

## Navigation

Navigation is grouped in `config.py` and filtered by current Snowflake role.
The default company view is `ALFA`.

Monitoring:

- Account Health
- Usage Overview
- Adoption Analytics
- Service Health
- Live Monitor
- Detailed Diagnosis
- Query Analysis
- Query Search & History
- Warehouse Health

Infrastructure:

- Storage Monitor
- Pipeline Health
- Platform Topology
- SPCS Tracker
- Task Management

Cost & Performance:

- Cost Center
- Credit Contract
- Recommendations & Anomalies
- Snowflake Value
- AI & Cortex Monitor

Security & Ops:

- Security & Access
- Who Changed What?
- Stored Proc Tracker
- Data Sharing
- DBA Tools

## Major Capabilities

Account Health is the executive landing page. It includes an overview, resource
monitor view, morning report, and executive briefing export.

Warehouse Health combines warehouse utilization, cache efficiency, scaling
events, spill pressure, concurrency heatmaps, and optimization guidance.

Cost Center includes cost by user, warehouse, role, database, schema,
application/client, chargeback by company view, budget tracking, burn rate, and
contract utilization.

Recommendations & Anomalies provides an action queue with severity, owner,
status, proof SQL, generated fixes, and alert setup.

Security & Access includes login audit, login posture, roles and grants, dormant
user detection, MFA coverage, exfiltration signals, and access-history lineage.

DBA Tools includes query kill list, warehouse settings manager, data loading,
network and sessions, unused objects, Snowpipe, QAS, schema compare, recent
objects, pre-aggregation DDL, dynamic tables, replication, serverless costs,
Cortex limits, task graph control, and OVERWATCH usage log.

Object Change Monitoring answers "who changed what" across DDL, access grants,
policy changes, ownership changes, and drift indicators.

Stored Proc Tracker attributes stored procedure and downstream child-query cost
where Snowflake query lineage is available.

## Company Filtering

Company filtering is centralized in `COMPANY_CONFIG` in `config.py`.

- `ALFA` excludes Trexis warehouses and focuses on ALFA/Admin database patterns.
- `Trexis` focuses on `WH_TRXS_%`, `TRXS_%` database patterns, and Trexis users.
- `ALL` removes company-specific filters.

When changing company view, cached datasets are invalidated so each section
re-runs with the selected company scope.

## Global Filters

The sidebar supports shared filters for:

- Date range
- Warehouse contains
- User contains
- Role contains
- Database contains

Sections use these where supported. Some specialized DBA tools use their own
section-local controls because they target administrative operations.

## Themes

The theme picker lives under sidebar Settings. Available themes:

- Midnight: dark glassmorphism with cyan accents
- ALFA: light ALFA-inspired theme with red and teal accents
- Terminal: green-on-black operations theme
- Aurora: dark teal/emerald theme
- Carbon: dark charcoal and orange operations theme

The former Corporate theme has been replaced by the ALFA theme. Shared tab
styling now supports horizontal scrolling so long tab sets remain readable.

## Persistence Tables

OVERWATCH uses the configured `DBA_MAINT_DB.OVERWATCH` schema for app-owned
state such as:

- Saved views/bookmarks
- Alert history
- Recommendation action queue
- Snowflake value log

The app can generate setup DDL for saved views from the sidebar Saved Views
panel.

## Alerts

Alerting is designed for Microsoft Teams/webhook and email-oriented workflows.
Slack webhook language has been removed from the current direction.

Recommendations and alert setup should write actionable items into the action
queue with status values such as New, Acknowledged, Fixed, and Ignored.

## Runtime Notes

- `SNOWFLAKE.ACCOUNT_USAGE` can lag by up to roughly 45 minutes.
- `INFORMATION_SCHEMA` views are used for fresher operational detail where
  practical.
- Some features are best-effort because Snowflake account history availability
  depends on edition, privileges, retention, and account settings.
- Keep credentials in Streamlit secrets or local `.streamlit/secrets.toml`.
- Do not commit Streamlit log files or Python cache directories.

## Recent Design Updates

- Corporate theme replaced by ALFA theme based on ALFA brand colors.
- Sidebar icon text leaks were fixed by protecting Streamlit Material icon
  ligatures from broad font overrides.
- Navigation labels were standardized with native Streamlit captions where
  possible.
- Optimization was consolidated under Warehouse Health.
- Dormant Users was removed from DBA Tools and remains available in Security &
  Access.
- Migration Confidence and Teradata-oriented executive language were removed.

## Troubleshooting

If the app fails at startup, check that all support modules are present:

- `theme.py`
- `config.py`
- `utils/`
- `sections/`

If a section fails with an invalid identifier, the Snowflake view in that account
may not expose the same column names as another Snowflake release or view family.
Prefer defensive SQL patterns using available `ACCOUNT_USAGE` columns and avoid
assuming optional columns exist everywhere.

If Streamlit Community Cloud fails during install, confirm `requirements.txt`
contains only PyPI packages and Snowflake Streamlit-specific packages remain in
`.overwatch_final/environment.yml`.
