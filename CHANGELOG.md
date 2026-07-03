# Changelog

## 2026.07.03-review-improvements

- Cache correctness: query cache keys now include schema scope, exceptions-only
  mode, and credit/AI/storage rates so rate or triage-mode changes never serve
  rows computed for another setting.
- Cache refresh: forced (non-cached) executions bump the scoped refresh salt so
  later cached reads for the same query namespace cannot serve pre-refresh rows
  within the tier TTL.
- Telemetry accuracy: query events now report real cache hits by observing the
  Snowflake execution counter instead of assuming every cached-tier call was a
  hit.
- Mart freshness: `load_mart_table` reads latest-snapshot marts on the 300s
  `command_summary` tier instead of pinning rows for an hour on `historical`.
- Dead code removal: deleted orphaned sections (`live_monitor`,
  `usage_overview`, `adoption_analytics`, `platform_topology`,
  `native_monitoring`, `ui_compat`) and the unused `render_local_section_menu`
  / inline scope-field helpers; synced session/direct-SQL allowlists, retained
  runtime module contracts, and tests.
- Accessibility: section transition loader honors `prefers-reduced-motion`;
  removed decorative `aria-hidden` scope chrome.
- Dependencies: pinned `jinja2>=3.1.5` (required by the warehouse heatmap
  pandas Styler gradient).

## 2026.06.14-95-hardening

- Reframed Executive Landing as a six-KPI boardroom glance page: spend vs budget, daily burn, critical/high alerts, pipeline SLA, platform health, and action queue.
- Removed unsafe HTML card rendering from shared shell helpers in favor of native Streamlit containers, columns, badges, and button help text.
- Added conservative sidebar filter sanitization and SQL-control token rejection.
- Added query runner hardening: standard cache tier, longer historical cache, statement timeout tiers, render query budget guardrail, and removal of process-wide cache lock stripes.
- Added explicit OVERWATCH_MONITOR and OVERWATCH_OPERATOR Snowflake role setup.
- Added deployable Snowflake contracts for pipeline SLA, freshness alerts, executive digest history, tag-based allocation, and OVERWATCH self-health.
- Added version metadata, SQL builder primitives, incident correlation SQL, and predictive SLA SQL contracts.
