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

## Snowflake Browser Compatibility

Section modules should treat the Snowflake browser as a conservative runtime:
route shells must be small, query-on-demand, and resilient to hot-reloaded
helper modules. Optional captions, info copy, buttons, and expanders can use
the lightweight wrappers in `sections.ui_compat` when a section needs
empty-value guards or stable keys. Loaded chart surfaces inside section modules
should import through `sections.chart_helpers`, not `utils.display`, so stale
browser sessions keep the native Streamlit fallback path.

## Primary Section First-Paint Contract

Every canonical section must render useful operator context before any live
Snowflake read. The central contract registry in
`sections.first_paint_contracts` owns the primary view, expected lanes, safe
load boundary, cached/session sources, and forbidden first-paint loaders.

| Section | Primary view | Expected lanes | Explicit load CTA |
| --- | --- | --- | --- |
| Executive Landing | Executive Overview | Cost movement, operational risk, security risk, change summary, executive actions | Refresh Summary |
| DBA Control Room | Morning Cockpit | Failures, cost, queue, security, changes, action status | Load Morning Cockpit |
| Alert Center | Active Alerts | Critical and high alerts, overdue alerts, action queue, delivery status | Load Active Alerts |
| Workload Operations | Workload Overview | Slow or failed SQL, task and load failures, performance contention, recent changes, advanced DBA tools | Open the right tool |
| Cost & Contract | Cost Overview | Spend movement, run rate, warehouse drivers, Cortex, savings | Refresh Cost |
| Security Monitoring | Security Overview | Logins, grants, sharing, access changes, security alerts | Refresh Security Summary |

## Primary Section Command Deck

The Command Deck is the route-only action surface that sits beside the
first-paint shell. Its contracts live in `sections.command_deck_contracts` and
reuse the first-paint registry for each section's primary CTA, evidence
boundary, and no-query note. Command Deck buttons may set workflow/session
state or queue section navigation, but they must not load Snowflake evidence on
render and must not replace the explicit load/refresh buttons.

Command Deck v2 owns route actions and evidence-boundary context across primary
sections. Primary CTAs are actionable only when a section passes an explicit
callback; otherwise the deck displays the preserved load/refresh label and key
while the existing section button remains the actual evidence boundary. As
sections migrate, duplicate ad hoc route-button rows should be removed in favor
of the deck, but benchmark load labels and keys must remain stable.

| Section | Primary CTA | Route actions |
| --- | --- | --- |
| Executive Landing | Refresh Summary | Cost movement, operational risk, security risk, executive actions |
| DBA Control Room | Load Morning Cockpit | Failure triage, cost watch, performance watch, action queue |
| Alert Center | Load Active Alerts | Active, cost, reliability, and security alert lanes |
| Workload Operations | Open the right tool | SQL, task/load, performance, change, and comparison workflows |
| Cost & Contract | Refresh Cost | Warehouse cost, forecast, budget, and recommendation workflows |
| Security Monitoring | Refresh Security Summary | Failed logins, risky grants, access changes, and sharing exposure |

## Operator Case File

The Operator Case File is a local handoff packet for already-loaded evidence. It
does not query Snowflake, save to Snowflake, or mutate action queues. Operators
must load evidence explicitly in a section before using Add to Case.

Rules:

- Add to Case is visible only on loaded evidence paths.
- Case export is a Markdown handoff artifact, not an approval, retry, queue, or
  remediation action.
- Each case item must carry section, scope, freshness/source notes, a summary,
  a recommended next action, and a small preview of loaded rows when available.
- Export/copy actions must be explicit and use stable download helpers rather
  than writing files into the repository.

## Charts And Tables

Charts should explain movement. Tables should prove details.

Rules:

- Show dollars beside credits when spend, savings, or forecast is involved.
- Provide a way back to the chart after exposing the chart data table.
- Avoid duplicate chart/table pairs that show the same fact twice.
- Prefer ranking charts for top spenders and trend charts for movement.
- Use shared OVERWATCH Altair helpers for time-series, area, and ranked bar
  charts.
- Section modules import chart helpers through `sections.chart_helpers`, never
  direct `utils.display` imports or package-level `utils` chart helper exports.
- `sections.chart_helpers` is the only native Streamlit chart fallback module;
  it may call `st.line_chart`, `st.area_chart`, or `st.bar_chart` only when
  Snowflake browser hot-reload leaves a stale `utils.display` module in memory.
- New loaded-data charts should use `render_time_series_chart`,
  `render_area_time_series_chart`, or `render_ranked_bar_chart`.
- Use source/freshness help where a metric depends on delayed Snowflake views.

## Snowflake Browser Smoke

Use `docs/OVERWATCH_SNOWFLAKE_BROWSER_SMOKE_CHECKLIST.md` after UI shell,
Command Deck, chart-helper, or browser-compatibility changes. The smoke is
read-only except local session state and explicit export/download actions.

## Accessibility And Snowflake Browser Safety

- Custom HTML fragments must escape generated labels and descriptions before
  rendering.
- Status surfaces must include text labels; color is supporting context only.
- Keyboard focus must remain visible on buttons, expanders, select controls,
  date inputs, text inputs, and other actionable controls.
- Command Deck route actions and workflow context cards must wrap labels at
  narrow widths instead of clipping or forcing horizontal scroll.

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
