# OVERWATCH Recovery Runbook

Use this when the dashboard is blank, stale, slow, or showing conflicting evidence.

## First Five Checks

1. Confirm the running version in the sidebar footer.
2. Confirm the active role is `SNOW_ACCOUNTADMINS` or `SNOW_SYSADMINS`.
3. Run `snowflake/OVERWATCH_MART_VALIDATION.sql`.
4. Check `DBA_MAINT_DB.OVERWATCH.OVERWATCH_SELF_HEALTH_V` for stale surfaces.
5. Check Streamlit query warnings for result guard, timeout, or role privilege messages.

## If Executive Landing Is Empty

1. Query `DBA_MAINT_DB.OVERWATCH.MART_EXECUTIVE_OBSERVABILITY`.
2. Query `DBA_MAINT_DB.OVERWATCH.OVERWATCH_SOURCE_FRESHNESS`.
3. Confirm the refresh task that loads the executive mart completed after the latest account telemetry load.
4. If the mart is empty, use Cost & Contract and Alert Center fallback views, then rerun the mart setup task.

## If Pipeline SLA Looks Wrong

1. Query `DBA_MAINT_DB.OVERWATCH.PIPELINE_SLA_CONFIG`.
2. Query `DBA_MAINT_DB.OVERWATCH.PIPELINE_SLA_STATUS_V`.
3. Remember `SNOWFLAKE.ACCOUNT_USAGE.TABLES` is delayed; use task history or event tables for near-real-time proof.
4. Update thresholds in `PIPELINE_SLA_CONFIG`; do not hard-code SLA assumptions in Streamlit.

## If Alert Counts Look Wrong

1. Query `ALERT_EVENTS` for open, acknowledged, suppressed, and resolved rows.
2. Check `ALERT_RUN_HISTORY` for the latest alert task run.
3. Check `ALERT_SUPPRESSION_WINDOWS` or equivalent suppression policy before reopening alerts.
4. Validate that native Snowflake alerts are notification-only until owner routing and dedupe are approved.

## If The App Is Slow

1. Narrow company, environment, date, warehouse, and user filters.
2. Check the in-session query budget summary in DBA Control Room if exposed.
3. Review query tags beginning with `OVERWATCH` in `SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY`.
4. Move repeated live views into transient fact tables or the optional precompute layer.

## If Cost Numbers Are Challenged

1. Prefer `WAREHOUSE_METERING_HISTORY`, `METERING_DAILY_HISTORY`, and `QUERY_ATTRIBUTION_HISTORY`.
2. Treat live credit estimates as fallback only.
3. Label allocated grain clearly when Snowflake does not provide direct database/user/role billing.
4. Reconcile the UI against Snowsight and Snowflake metering for the same closed time window.

## Rollback

The setup scripts are additive. To roll back a new contract, disable the related task or alert first, then drop the new view/table only after exporting audit/history rows that must be retained.
