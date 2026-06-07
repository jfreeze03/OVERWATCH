# OVERWATCH Production UX Guidelines

Last updated: June 6, 2026

These guidelines keep OVERWATCH focused on DBA morning triage, safe operations,
and executive-ready evidence.

## Core Layout

1. Keep global filters in a persistent topbar.
2. Keep navigation in the sidebar.
3. Render the action brief before charts and tables.
4. Show exceptions first.
5. Put heavy evidence behind explicit load buttons.
6. Keep first-entry section load fast and calm.

## Section Pattern

Each production section should follow this order:

1. brief state or top priority
2. three to five operator metrics
3. exception strip or action queue rows
4. primary chart or graph
5. drilldown evidence behind load gates
6. proof/export controls

Healthy sections should not fill the page with low-value tables. When there are
no issues, show a compact healthy state and let the DBA move on.

## Navigation

Current group order:

1. Command Center
2. Financial Control
3. Operations
4. Governance
5. Architecture

Do not introduce a new top-level section unless it represents a distinct DBA
workflow. Thin evidence pages should become tabs or load panels inside the
section that owns the workflow.

## Charts And Tables

Charts should explain movement. Tables should prove details.

Rules:

- Show dollars beside credits when spend, savings, or forecast is involved.
- Provide a way back to the chart after exposing the chart data table.
- Avoid duplicate chart/table pairs that show the same fact twice.
- Prefer ranking charts for top spenders and trend charts for movement.
- Use source/freshness help where a metric depends on delayed Snowflake views.

## Text And Labels

Use current production section names only:

- Executive Landing
- DBA Control Room
- Alert Center
- Account Health
- Cost & Contract
- Workload Operations
- Warehouse Health
- Security Posture
- Change & Drift
- Architecture Readiness

Avoid internal build/test language in the app UI. Avoid stale page names in
comments, docs, help text, saved-view labels, and screenshots.

## Admin Controls

Admin controls should look and feel serious:

- current state first
- changed-only SQL
- typed confirmation or clear approval step
- rollback SQL
- audit and failure audit evidence
- verification query
- owner and ticket context

Do not hide destructive actions inside generic chart/table panels.

## Executive Output

Executive Landing should produce content that can be pasted into slides:

- headline KPI movement
- charts with numbers
- top cost driver
- top reliability risk
- top governance blocker
- verified savings or no-change result
- next action and accountable owner

## Performance Feel

If a section needs multiple seconds to load secondary evidence, use a clear load
state and keep the primary view visible. The user should know whether the app is
working, waiting on Snowflake, or intentionally waiting for a load button.
