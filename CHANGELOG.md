# Changelog

## 2026.06.14-95-hardening

- Reframed Executive Landing as a six-KPI boardroom glance page: spend vs budget, daily burn, critical/high alerts, pipeline SLA, platform health, and action queue.
- Removed unsafe HTML card rendering from shared shell helpers in favor of native Streamlit containers, columns, badges, and button help text.
- Added conservative sidebar filter sanitization and SQL-control token rejection.
- Added query runner hardening: standard cache tier, longer historical cache, statement timeout tiers, render query budget guardrail, and removal of process-wide cache lock stripes.
- Added explicit OVERWATCH_MONITOR and OVERWATCH_OPERATOR Snowflake role setup.
- Added deployable Snowflake contracts for pipeline SLA, freshness alerts, executive digest history, tag-based allocation, and OVERWATCH self-health.
- Added version metadata, SQL builder primitives, incident correlation SQL, and predictive SLA SQL contracts.
