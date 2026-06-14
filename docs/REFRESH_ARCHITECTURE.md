# OVERWATCH Refresh Architecture

OVERWATCH should feel instant to a DBA without turning the monitoring app into a
new Snowflake cost problem. The production rule is mart-first, live-second.

## Default Decision

Use scheduled Snowflake tasks and transient mart/fact tables for the command
center. Use permanent tables only for configuration, acknowledgements,
suppression windows, remediation logs, action queue history, owner routing, and
value evidence.

Do not make Dynamic Tables the base architecture. They remain optional
accelerators in `snowflake/PRECOMPUTE.sql` after DBA approval of warehouse,
target lag, ownership, and refresh budget.

Do not use materialized views for the primary command center. The app needs
multi-source, windowed, owner-routed exception logic with explicit refresh and
audit behavior.

## First-Paint Sources

| Surface | First-paint source | Target freshness | Live fallback |
|---|---|---:|---|
| Executive Landing | `MART_EXECUTIVE_OBSERVABILITY` | 60 min | No |
| DBA Control Room | `MART_DBA_CONTROL_ROOM` | 60 min | Explicit only |
| Alert Center | `ALERT_EVENTS`, notification/action tables | 15 min | No |
| Cost & Contract | Cost/Cortex facts plus bounded official cost lens | 60 min | Explicit proof refresh |
| Workload Operations | Query/task facts and task history summaries | 30 min | Explicit live triage |
| Governance & Security | Access posture and change-control facts | 60 min | Explicit governance lane |
| Snowflake Value | `OVERWATCH_VALUE_CANDIDATE_V`, `OVERWATCH_ROI_LOG` | 60 min | Explicit load only |

The setup SQL seeds the same contract into `OVERWATCH_REFRESH_POLICY`.
The UI should still render the metric frame immediately. If a Snowflake session
or mart lookup would block the first paint, show the precomputed-board frame and
let `Refresh Board` read the compact mart. Do not fall back to live account
history scans from the executive landing page.

Executive Landing is the only exception to the single-query ideal when the
compact mart is unavailable. It may fall back to bounded OVERWATCH fact marts
(`FACT_COST_DAILY`, `FACT_CORTEX_DAILY`, `FACT_QUERY_HOURLY`,
`FACT_QUERY_DETAIL_RECENT`, task, storage, alert, and action tables) so the boss
page can still show cost drivers, query/database/status mix, warehouse pressure,
and run-rate facts without scanning raw `SNOWFLAKE.ACCOUNT_USAGE`.

The same first-paint rule applies to Cost & Contract, Alert Center, and
Snowflake Value: show the board frame immediately, reuse already-loaded session
state when present, and keep Snowflake reads behind explicit refresh/load
actions or scheduled mart tasks. Silent UI autoloads are not allowed for these
surfaces.

Primary sidebar navigation must land on the section board, not the heavy proof
workspace. Drill-through buttons inside a board may open the detailed workspace
because that is an explicit operator action. Every board should show its refresh
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
- PowerPoint support data
- exhaustive alert history

First paint should answer: what is wrong, what is expensive, what is late, what
changed, who owns it, and where to drill next.
