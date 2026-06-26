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

Facts come first, evidence opens on demand, and section entry may read compact
mart command summaries. A section entry should show the active view, scope,
freshness, expected lanes, and the next safe load action before detailed rows,
exports, and specialist diagnostics appear. Heavy live proof and row-level
account-history reads stay behind explicit load buttons.

Executive Landing owns the Mission Control queue. That queue answers "what
needs attention now" from already-loaded session evidence only: active alerts,
loaded cost cockpit facts, and loaded security summary facts. It must never
query Snowflake. If no evidence is loaded, it should clearly direct the operator
to the explicit load boundaries instead of pretending a healthy state is known.

Visible section subtitles should explain the current operating surface in one
short line. Workflow selectors may collapse advanced choices when the selected
workflow remains visible and deep-link/session-state behavior is preserved.
High-traffic workflow hubs such as Executive Landing and DBA Control Room should
show the selected workflow detail inline, keep the primary/default workflow in
the first row, and move less common workflows into a clearly named expander.
Alert Center first paint should show the mart-backed command brief and cached
counts when they are already in session state; detailed alert rows stay behind
Load.
Use shared first-paint shell helpers for status strips, KPI rows, and snapshots
when a section can do so without moving data-load decisions out of the owning
section. Workload Operations uses this pattern for its session-only overview;
specialist workload evidence remains behind the selected workflow and explicit
load actions. Security Monitoring uses the same shell for active-view, scope,
expected evidence lanes, and next-action wayfinding while detailed security
evidence stays in the selected workflow or explicit load path. Security
Monitoring entry may read the compact command brief mart; Refresh Security
Summary remains the proof/detail boundary. Cost & Contract uses the same
contract for Cost Overview: scope, window, evidence state, expected cost lanes,
and Load Cost Evidence are visible before official spend, forecast, reconciliation,
or contract evidence loads.

Cortex AI is a first-class financial and operational risk lane, not a secondary
cost footnote. Executive Landing, Cost & Contract, Alert Center, and Cortex AI
surfaces must show Cortex spend, forecast/run-rate, predictive alerts, top
driver, and cost-risk state from already-loaded/session data where available.
When Cortex telemetry is unavailable, show an honest summary-unavailable state
and route the operator to the explicit Cortex cost-driver workflow instead of
hiding the signal under tables or expanders.

Primary sections should use the Command Brief layer for entry context. Use
`FirstPaintSummarySpec` only for specialized legacy loaded-context surfaces that
already have a narrower contract.

## Snowflake Browser Compatibility

Section modules should treat the Snowflake browser as a conservative runtime:
route shells must be small, mart-summary-first, and resilient to hot-reloaded
helper modules. Optional captions, info copy, buttons, and expanders can use
the lightweight wrappers in `sections.ui_compat` when a section needs
empty-value guards or stable keys. Loaded chart surfaces inside section modules
should import through `sections.chart_helpers`, not `utils.display`, so stale
browser sessions keep the native Streamlit fallback path.

## Primary Section Command Brief Contract

Every canonical section must render useful operator context on entry. The UI
reads at most one command brief packet query from compact command summary marts;
heavy detail, proof, and raw account-history rows remain behind explicit load
or refresh buttons. The central contract
registries in `sections.section_command_contracts` and
`sections.first_paint_contracts` own the primary view, expected lanes, safe load
boundary, mart/session sources, and forbidden detail loaders.

| Section | Primary view | Expected lanes | Explicit load CTA |
| --- | --- | --- | --- |
| Executive Landing | Executive Overview | Cost movement, Cortex AI cost risk, operational risk, security risk, change summary, executive actions | Load Full Executive Snapshot |
| DBA Control Room | Morning Cockpit | Failures, cost, queue, security, changes, action status | Load Investigation Detail |
| Alert Center | Active Alerts | Critical and high alerts, Cortex predictive alerts, overdue alerts, action queue, delivery status | Load Active Alerts |
| Workload Operations | Workload Overview | Slow or failed SQL, task and load failures, performance contention, recent changes, advanced DBA tools | Open the specialist workflow |
| Cost & Contract | Cost Overview | Spend movement, run rate, warehouse drivers, Cortex AI cost risk, savings | Load Cost Evidence |
| Security Monitoring | Security Overview | Logins, grants, sharing, access changes, security alerts | Load Security Evidence |

The Command Brief layout is status band, four primary metrics maximum, top
signal, one primary action, up to two secondary actions, a real detail/evidence
button, and source/freshness footer. Additional metrics belong in a collapsed
area. It must not render empty board walls with placeholder KPIs. If the mart
summary is unavailable, show one "Summary unavailable" diagnostics panel plus
setup/remediation copy and keep the detail boundary visible.

Decision Brief 3.2 is the operating loop for primary sections: section/state
headline, plain-English summary, four available metrics, movement sparkline
where available, "What needs attention" findings, the next action set, and a
data-trust footer. Metrics with missing source coverage must render as
unavailable in collapsed detail, not as zeros in the primary strip. Source
trust is reconciled from per-source watermarks in the app; if the parent brief
claims freshness that source rows do not support, the UI fails closed to Data
Gap or Stale and shows the resolved scope/confidence.

## Primary Section Command Deck

Legacy Command Deck contracts remain the static route catalog, but the Command
Brief is the authoritative entry summary and action surface. Command Brief route
actions resolve through allowlisted section/workflow targets; mart rows may
select action keys and labels, but they must not inject arbitrary Streamlit
session state.

The Decision Brief owns the entry route actions and the visible evidence
boundary. Primary CTAs are actionable only when a section passes an explicit
callback; route CTAs resolve through allowlisted `ROUTE_KEY` values. Legacy
Command Deck contracts may still seed static route catalogs, but primary
sections should not render a duplicate Command Deck beside the Decision Brief.
Benchmark load labels and keys must remain stable when a load action moves into
the brief.

| Section | Primary CTA | Route actions |
| --- | --- | --- |
| Executive Landing | Load Full Executive Snapshot | Cost movement, Cortex AI cost, operational risk, security risk, executive actions |
| DBA Control Room | Load Morning Cockpit | Failure triage, cost watch, performance watch, action queue |
| Alert Center | Load Active Alerts | Active, Cortex predictive, cost, reliability, and security alert lanes |
| Workload Operations | Open the right tool | SQL, task/load, performance, change, and comparison workflows |
| Cost & Contract | Load Cost Evidence | Warehouse cost, Cortex cost drivers, forecast, budget, and recommendation workflows |
| Security Monitoring | Load Security Evidence | Failed logins, risky grants, access changes, and sharing exposure |

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
- Chart helpers must drop invalid dates, nonnumeric values, and infinite values
  before a chart reaches Altair/Vega. Empty or invalid chart inputs get a
  text-first empty chart state, not a blank chart or browser warning.
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
