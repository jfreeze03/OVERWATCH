# OVERWATCH Refresh Design

OVERWATCH should feel instant to a DBA without turning the monitoring app into a
new Snowflake cost problem. The production rule is mart-first, live-second.

## Default Decision

Use scheduled Snowflake tasks and transient mart/fact tables for the monitoring
app. Use permanent tables only for configuration, acknowledgements,
suppression windows, remediation logs, action queue history, and routing.

Do not make Dynamic Tables the base architecture. The production setup has one
deployable DDL source: `snowflake/OVERWATCH_MART_SETUP.sql`.

This is now a hard deployment boundary for secure-view compatibility. If an
OVERWATCH mart source can resolve through a secure view, the target must be a
physical table populated by a scheduled task/procedure. Do not rewrite those
facts as Dynamic Tables; Snowflake Dynamic Tables can fail when secure views sit
in the dependency path.

When a proposed mart starts as a Dynamic Table, convert it before deployment:

1. Create a transient table with the final columns.
2. Load it from a `SP_OVERWATCH_*` refresh procedure.
3. Schedule that procedure from an `OVERWATCH_*` task.
4. Add the table, procedure, and task to the setup/drop contract.
5. Run `snowflake/OVERWATCH_MART_VALIDATION.sql` and confirm no
   `DYNAMIC_TABLE_COLLISIONS` or `SECURE_VIEW_COLLISIONS` remain.

Before importing DDL from another build or doing a mass mart reset, also run
`snowflake/OVERWATCH_DYNAMIC_TABLE_SECURE_VIEW_AUDIT.sql`. It scans the current
schema for OVERWATCH-named Dynamic Tables and Secure Views and includes an
optional account-level dependency check for Dynamic Tables that reference secure
views.

The audit emits generated drop SQL plus table/procedure/task rewrite stubs for
flagged Dynamic Tables. Treat those as conversion scaffolding only; the source
query still needs DBA review before the rewritten table/procedure/task enters
`OVERWATCH_MART_SETUP.sql`.

Do not use materialized views for the primary monitoring app. The app needs
multi-source, windowed exception logic with explicit refresh and
audit behavior.

## Entry Command Brief Sources

Primary section entry uses mart-backed Decision Briefs. The UI reads one compact
packet from `MART_SECTION_DECISION_CURRENT` on entry, parses the embedded parent,
metric, finding, source, and action payload, and renders an operational story
immediately. The normalized BRIEF_ID-linked history tables remain available for
audit, validation, and diagnostics. Heavy detail/live proof remains explicit
behind the section's Load, Refresh, investigation, or evidence controls.

| Surface | Entry command brief source | Target freshness | Live fallback |
|---|---|---:|---|
| Executive Landing | `MART_SECTION_COMMAND_BRIEF` packet from executive, cost, Cortex, alert, action, readiness, and scorecard marts | 60 min | No |
| DBA Control Room | `MART_SECTION_COMMAND_BRIEF` packet from `MART_DBA_CONTROL_ROOM`, alert/action/change summaries, and workload facts | 30 min | Explicit only |
| Alert Center | `MART_SECTION_COMMAND_BRIEF` packet from alert, action, and notification summaries | 15 min | No |
| Cost & Contract | `MART_SECTION_COMMAND_BRIEF` packet from cost, Cortex, forecast, value, and monitoring facts | 60 min | Explicit proof refresh |
| Workload Operations | `MART_SECTION_COMMAND_BRIEF` packet from query, task, procedure, copy/load, change, and reliability summaries | 30 min | Explicit live triage |
| Security Monitoring | `MART_SECTION_COMMAND_BRIEF` packet from security, alert, owner coverage, and change summaries | 60 min | Explicit drilldown only |

`SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS()` is the shared packet builder
called by `SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FAST()`,
`SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FULL()`, and
`SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS()`. It runs six explicit decision
builders (`executive_decision`, `dba_decision`, `alert_decision`,
`cost_decision`, `workload_decision`, and `security_decision`) before packaging
the current packet. Each builder owns the section state, headline, top signal,
impact, owner route, evidence source, primary route key, and action label.
Cost movement cannot change Security state, workload failures cannot become Cost
state without cost evidence, and Cortex predictive alerts route to Cortex/Cost
unless the source signal is genuinely security-related.

The procedure populates the parent brief, typed metrics, source-level trust
rows, priority findings, and allowlisted action references for canonical 1, 7,
14, 30, 60, and 90 day windows. The task
`OVERWATCH_SECTION_COMMAND_BRIEF_REFRESH` runs every 15 minutes against compact
summary marts; it does not perform raw app-entry `ACCOUNT_USAGE` proof scans.
Validation calls the procedure and checks all six sections, BRIEF_ID
relationships, child-row orphans, typed metrics, route keys, current packet
coverage, source rows, source coverage, freshness targets, and canonical window
coverage.

Decision Brief 3.2 makes the packet contract stricter. Source configuration is
seeded during setup and then treated as operator-owned configuration; the
scheduled refresh reads it but does not delete or reinsert it. Contract metadata
comes from `config/decision_brief_contracts.json`, which generates the
import-safe Python contract module and Snowflake seed/validation snippets.
Current packets
are published append-first per section/scope/window, then older packets for the
same logical key are removed, so readers do not see an intentionally emptied
`MART_SECTION_DECISION_CURRENT` table during refresh. The packet includes the
embedded source-health array and byte size, and the app displays both the packet
source and upstream source rows in Data Trust.

Source trust is measured per source through
`OVERWATCH_SECTION_COMMAND_SOURCE_CONFIG` and `MART_SECTION_COMMAND_SOURCE`.
Missing sources remain missing, stale sources remain stale, and
`SOURCE_COVERAGE_PCT` is the share of required sources that were available for
the selected scope/window. `TMP_DECISION_SOURCE_WATERMARK` resolves each
configured source independently before parent trust is calculated, so one fresh
source cannot make a missing source look healthy. The app also reconciles parent
trust fields against embedded source rows and fails closed to `Data Gap` or
`Stale` when the packet contradicts its source evidence. The UI displays
requested versus resolved scope when the current packet falls back to an
ALL/GLOBAL row.

Metric availability is explicit. Unavailable metrics carry
`IS_AVAILABLE = FALSE`, `AVAILABILITY_STATE`, `UNAVAILABLE_REASON`,
`SOURCE_KEY`, and `CONFIDENCE`; they are omitted from the primary metric ribbon
and shown only in the additional/trust detail area. The renderer presents one
operating loop rather than a card wall: status, headline, four available metrics,
top findings with impact/owner/SLA, a deduplicated primary route, up to two
secondary routes, the real detail-load button, and a compact source footer.

The refresh contract stays in this document and in the read-only validation SQL
instead of a static mart table. Run `snowflake/OVERWATCH_MART_VALIDATION.sql`
after setup to verify the first-paint mart, required panels, alert lifecycle
tables, compare/recon tables, refresh contract, and caller context. Role-level proof belongs in
`docs/LIVE_ROLE_PROOF_CHECKLIST.md`.

The UI should render a populated Command Brief immediately when the packet mart
is available. If a Snowflake session or mart lookup is unavailable, show one
concise "summary unavailable" brief with setup guidance and keep detail evidence
behind explicit load buttons. Do not render eight setup cards and do not fall
back to live account-history scans from the executive landing page.

Executive Landing is not allowed to start raw `SNOWFLAKE.ACCOUNT_USAGE` scans on
navigation. It may reuse already-loaded session values and may hydrate compact
summary marts. If the command brief mart is unavailable, the page still shows a
summary-unavailable command brief, data freshness status, and the next setup or
detail action.

The same entry rule applies to DBA Control Room, Workload Operations, Cost &
Contract, Alert Center, and Security Monitoring: show the command brief
immediately, reuse already-loaded session state when present, and allow only
compact precomputed mart reads during navigation. Raw `ACCOUNT_USAGE`,
`INFORMATION_SCHEMA`, schema compare, data hash, remediation, and proof queries
stay behind explicit refresh/load actions or scheduled Snowflake tasks.

Native Snowflake alert deployment follows the same explicit-action pattern.
`snowflake/OVERWATCH_NATIVE_ALERT_DEPLOYMENT.sql` creates a deployment review
view and dry-run staging procedure, but generated `CREATE ALERT` SQL remains a
manual DBA deployment decision.

Primary sidebar navigation must land on the section summary, not the heavy proof
workspace. Drill-through buttons inside a summary may open the detailed workspace
because that is an explicit operator action. Every summary should show its refresh
contract: source, freshness state, target SLA, and whether a live fallback is
allowed.

## When To Query Live Snowflake Metadata

Use live or near-real-time metadata only for active incidents:

- running, blocked, or queued work
- in-flight task graph failures
- current warehouse saturation
- urgent access/security triage
- explicitly requested schema/data comparison proof

Every live path should be bounded by time window, row limit, scope filters, and
operator intent.

## Native Snowflake Signals

The production hardening strategy expects the monitoring app to label native
Snowflake signal availability clearly. Where the role has privileges, the app
can summarize:

- Data Metric Functions via `DATA_METRIC_FUNCTION_REFERENCES`
- Snowflake ALERT object inventory and `ALERT_HISTORY`
- owner/cost/criticality tags via `TAG_REFERENCES`
- OVERWATCH app activity via `OVERWATCH_USAGE_LOG`; legacy app `QUERY_TAG` cost is optional when present
- daily executive digest history
- optional organization usage cost rollups

These checks are not first-paint live scans. They are either setup contracts,
scheduled facts, or explicit drill-through checks. If the active role lacks a
view, the UI should label the source as unavailable rather than silently
pretending the control exists.

## Compare Workflows

Schema Compare is an operator-triggered metadata workflow. It uses `SHOW OBJECTS`
for the selected schema so every visible schema object is inventoried, then
joins `INFORMATION_SCHEMA.COLUMNS` to catch column-level drift. Missing schema
objects generate review SQL through `GET_DDL`; missing columns generate explicit
`ALTER TABLE ... ADD COLUMN` statements. Privilege gaps must degrade to manual
`GET_DDL` review, not silent success.

Data Compare is an operator-triggered bounded scan. The first pass compares
matching tables by metadata, row count, and explicit-column `HASH_AGG`. A hash
mismatch is not the final answer; it produces bucket-isolation SQL and keyed or
set-style forensic SQL so the DBA can prove the rows that differ. Large schemas
must start with table filters and maximum table caps.

Both compare workflows generate reviewable persistence SQL. Schema differences
insert into `OVERWATCH_SCHEMA_DIFF_RESULT`; data compare runs insert into
`OVERWATCH_RECON_RUN`. The app does not auto-write those records during a
compare because the scan may be part of a release gate, an investigation, or a
one-off DBA check.

## What Not To Load On First Paint

- full `QUERY_HISTORY` row dumps
- all object metadata across the account
- schema/data hash comparisons
- proof SQL previews
- remediation forms
- presentation-export preparation
- exhaustive alert history

First paint should answer: what is wrong, what is expensive, what is late, what
changed, who owns it, and where to drill next.
