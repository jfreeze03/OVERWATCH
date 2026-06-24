# OVERWATCH Production UX Guidelines

Last updated: June 24, 2026

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

Current canonical production sections:

1. Executive Landing
2. DBA Control Room
3. Alert Center
4. Workload Operations
5. Cost & Contract
6. Security Monitoring

Do not introduce a new top-level section unless it represents a distinct DBA
workflow. Thin evidence pages should become tabs or load panels inside the
section that owns the workflow.

## UI Direction

Facts come first, evidence opens on demand, and first paint must be useful
without live Snowflake reads. A section entry should show the active view,
scope, freshness, expected lanes, and the next safe load action before detailed
rows, exports, and specialist diagnostics appear.

Visible section subtitles should explain the current operating surface in one
short line. Workflow selectors may collapse advanced choices when the selected
workflow remains visible and deep-link/session-state behavior is preserved.
High-traffic workflow hubs such as Executive Landing and DBA Control Room should
show the selected workflow detail inline, keep the primary/default workflow in
the first row, and move less common workflows into a clearly named expander.
Alert Center first paint should show cached counts when they are already in
session state, otherwise it should stay explicitly on demand until Load is used.
Use shared first-paint shell helpers for status strips, KPI rows, and snapshots
when a section can do so without moving data-load decisions out of the owning
section. Workload Operations uses this pattern for its session-only overview;
specialist workload evidence remains behind the selected workflow and explicit
load actions. Security Monitoring uses the same shell for active-view, scope,
expected evidence lanes, and next-action wayfinding while detailed security
evidence stays in the selected workflow or explicit load path. Security
Monitoring first paint must not auto-load the security summary; Refresh
Security Summary is the current-facts boundary. Cost & Contract uses the same
contract for Cost Overview: scope, window, evidence state, expected cost lanes,
and Refresh Cost are visible before official spend, forecast, reconciliation,
or contract evidence loads.

Use `FirstPaintSummarySpec` through `render_section_first_paint_shell()` when a
section needs the standard first-paint contract. Keep one-off shell rendering
only for specialized loaded-context surfaces that already have a narrower
contract.

## Charts And Tables

Charts should explain movement. Tables should prove details.

Rules:

- Show dollars beside credits when spend, savings, or forecast is involved.
- Provide a way back to the chart after exposing the chart data table.
- Avoid duplicate chart/table pairs that show the same fact twice.
- Prefer ranking charts for top spenders and trend charts for movement.
- Prefer shared OVERWATCH Altair helpers for time-series and area charts.
- Treat native `st.line_chart`, `st.area_chart`, and `st.bar_chart` usage as
  legacy-only unless a source-level test allowlists the specialist surface.
- Remove legacy chart allowlist entries when the final native chart call leaves
  that file. New loaded-data charts should use `render_time_series_chart`,
  `render_area_time_series_chart`, or `render_ranked_bar_chart`.
- Use source/freshness help where a metric depends on delayed Snowflake views.

## Text And Labels

Use current production section names only:

- Executive Landing
- DBA Control Room
- Alert Center
- Workload Operations
- Cost & Contract
- Security Monitoring

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
