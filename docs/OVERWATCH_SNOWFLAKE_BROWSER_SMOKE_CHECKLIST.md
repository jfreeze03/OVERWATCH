# OVERWATCH Snowflake Browser Smoke Checklist

Use this checklist after UI shell, chart, Decision Workspace route-action, or Snowflake browser compatibility changes. The checklist is read-only except for local session state and explicit export/download actions.

## Preconditions

- Start OVERWATCH in the Snowflake browser or local staged browser.
- Use the intended theme, including `?overwatch_theme=carbon` when validating dark mode.
- Do not run live Snowflake evidence loads unless credentials and release policy allow them.
- Keep the ramp-24 browser release policy unchanged.

## Cold Navigation

Cold navigate all six canonical sections and confirm first paint renders without visible exceptions:

- Executive Landing
- DBA Control Room
- Alert Center
- Workload Operations
- Cost & Contract
- Security Monitoring

For each section, confirm the first-paint shell shows text-first status, the visible subtitle remains readable, and no automatic Snowflake evidence load starts.

## Route Actions

- Open each primary section route-action area.
- Confirm route-action labels wrap without horizontal overflow.
- Click one route action per section and verify it only changes workflow/session routing.
- Confirm explicit evidence buttons retain stable labels and keys:
  - Decision Workspace
  - Load Morning Cockpit
  - Load Active Alerts
  - Load Cost Evidence
  - Load Security Evidence

## Advanced Scope

- Open Advanced Scope in the sidebar.
- Type in User contains.
- Use Role, Database, and Schema controls if available.
- Confirm controls stay keyboard-focusable and usable at narrow browser widths.

## Chart Surfaces

Render representative loaded chart surfaces after explicit user action only:

- Cost & Contract cost chart
- Cortex Monitor chart path
- Security access chart path
- Storage or SPCS chart path

Confirm charts render through shared OVERWATCH chart helpers and no native chart fallback error is shown.

## Explicit Load Buttons

When credentials and context are available, test explicit load actions:

- Decision Workspace
- Load Morning Cockpit
- Load Active Alerts
- Load Cost Evidence
- Load Security Evidence

Confirm no duplicate widget-key error appears.

## Operator Case File

- Load Active Alerts, then Add to Case.
- Load Cost Evidence, then Add to Case.
- Load Security Evidence, then Add to Case.
- Open the Case Drawer.
- Export Operator Case Markdown.

Confirm drawer/export does not query Snowflake and no files are written into the repository or `perf_tests/results`.
