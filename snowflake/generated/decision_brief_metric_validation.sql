-- Generated from config/decision_brief_contracts.json. Do not edit by hand.
WITH expected_metrics AS (
  SELECT * FROM VALUES
    ('Executive Landing', 'platform_health', TRUE, 'executive_observability', 'required'),
    ('Executive Landing', 'spend_movement_pct', TRUE, 'cost_daily', 'required'),
    ('Executive Landing', 'critical_high_issues', TRUE, 'alert_events', 'required'),
    ('Executive Landing', 'open_actions', TRUE, 'action_queue', 'required'),
    ('Executive Landing', 'cortex_spend', FALSE, 'cortex_daily', 'optional'),
    ('Executive Landing', 'cortex_risk', FALSE, 'cortex_daily', 'optional'),
    ('Executive Landing', 'operational_risk', FALSE, 'query_hourly', 'optional'),
    ('Executive Landing', 'security_risk', FALSE, 'security_operability', 'optional'),
    ('Executive Landing', 'production_readiness', FALSE, 'production_readiness', 'optional'),
    ('Executive Landing', 'data_trust', FALSE, 'data_trust', 'optional'),
    ('Executive Landing', 'verified_value', FALSE, 'value_ledger', 'optional'),
    ('Executive Landing', 'monitoring_overhead', FALSE, 'app_observability', 'optional'),
    ('DBA Control Room', 'failed_queries', TRUE, 'query_hourly', 'required'),
    ('DBA Control Room', 'pipeline_failures', TRUE, 'task_runs', 'required'),
    ('DBA Control Room', 'queue_pressure', TRUE, 'query_hourly', 'required'),
    ('DBA Control Room', 'cost_24h', TRUE, 'dba_control_room', 'required'),
    ('DBA Control Room', 'cortex_cost', FALSE, 'dba_control_room', 'optional'),
    ('DBA Control Room', 'security_warnings', FALSE, 'security_operability', 'optional'),
    ('DBA Control Room', 'recent_changes', FALSE, 'change_summary', 'optional'),
    ('DBA Control Room', 'overdue_actions', FALSE, 'action_queue', 'optional'),
    ('DBA Control Room', 'hottest_warehouse', FALSE, 'dba_control_room', 'optional'),
    ('DBA Control Room', 'top_dba_risk', FALSE, 'dba_control_room', 'optional'),
    ('Alert Center', 'active_alerts', TRUE, 'alert_events', 'required'),
    ('Alert Center', 'critical_high', TRUE, 'alert_events', 'required'),
    ('Alert Center', 'overdue_alerts', TRUE, 'alert_events', 'required'),
    ('Alert Center', 'cortex_predictive', TRUE, 'alert_events', 'required'),
    ('Alert Center', 'cost_alerts', FALSE, 'alert_events', 'optional'),
    ('Alert Center', 'reliability_alerts', FALSE, 'alert_events', 'optional'),
    ('Alert Center', 'security_alerts', FALSE, 'alert_events', 'optional'),
    ('Alert Center', 'notification_failures', FALSE, 'notification_log', 'optional'),
    ('Alert Center', 'open_action_queue', FALSE, 'action_queue', 'optional'),
    ('Cost & Contract', 'total_spend', TRUE, 'cost_daily', 'required'),
    ('Cost & Contract', 'spend_movement_pct', TRUE, 'cost_daily', 'required'),
    ('Cost & Contract', 'forecast_run_rate', TRUE, 'forecast', 'required'),
    ('Cost & Contract', 'cortex_spend_share', TRUE, 'cortex_daily', 'required'),
    ('Cost & Contract', 'cortex_spend', FALSE, 'cortex_daily', 'optional'),
    ('Cost & Contract', 'cortex_predictive_alerts', FALSE, 'cortex_daily', 'optional'),
    ('Cost & Contract', 'budget_contract_risk', FALSE, 'forecast', 'optional'),
    ('Cost & Contract', 'top_cost_driver', FALSE, 'cost_daily', 'optional'),
    ('Cost & Contract', 'verified_savings', FALSE, 'value_ledger', 'optional'),
    ('Cost & Contract', 'unverified_savings', FALSE, 'value_ledger', 'optional'),
    ('Cost & Contract', 'open_cost_actions', FALSE, 'action_queue', 'optional'),
    ('Workload Operations', 'failed_queries', TRUE, 'query_hourly', 'required'),
    ('Workload Operations', 'pipeline_failures', TRUE, 'task_runs', 'required'),
    ('Workload Operations', 'queries_waiting', TRUE, 'query_hourly', 'required'),
    ('Workload Operations', 'blocked_time', FALSE, 'query_hourly', 'optional'),
    ('Workload Operations', 'sla_risk', TRUE, 'task_runs', 'required'),
    ('Workload Operations', 'spill_bytes', FALSE, 'query_hourly', 'optional'),
    ('Workload Operations', 'long_running_queries', FALSE, 'query_hourly', 'optional'),
    ('Workload Operations', 'hottest_warehouse', FALSE, 'query_hourly', 'optional'),
    ('Workload Operations', 'recent_workload_changes', FALSE, 'change_summary', 'optional'),
    ('Workload Operations', 'suspended_tasks', FALSE, 'task_runs', 'optional'),
    ('Workload Operations', 'copy_load_failures', FALSE, 'copy_load', 'optional'),
    ('Security Monitoring', 'failed_logins', TRUE, 'login_daily', 'required'),
    ('Security Monitoring', 'mfa_gaps', TRUE, 'security_operability', 'required'),
    ('Security Monitoring', 'credential_expirations', TRUE, 'credential_expiration', 'required'),
    ('Security Monitoring', 'risky_grants', TRUE, 'grant_daily', 'required'),
    ('Security Monitoring', 'sharing_exposure', FALSE, 'security_operability', 'required'),
    ('Security Monitoring', 'privilege_changes', FALSE, 'security_operability', 'optional'),
    ('Security Monitoring', 'security_alerts', FALSE, 'security_alerts', 'optional'),
    ('Security Monitoring', 'access_changes', FALSE, 'change_summary', 'optional'),
    ('Security Monitoring', 'overdue_security_actions', FALSE, 'security_operability', 'optional')
  AS v(SECTION_NAME, METRIC_KEY, IS_PRIMARY, SOURCE_KEY, AVAILABILITY_POLICY)
)
SELECT 'SECTION_DECISION_CONTRACT_METRICS' AS CHECK_NAME, COUNT(*) AS OBSERVED_VALUE, 'PASS' AS STATUS
FROM expected_metrics
UNION ALL
SELECT
  'SECTION_DECISION_CONTRACT_METRIC_SOURCE_KEYS' AS CHECK_NAME,
  COUNT(*) AS OBSERVED_VALUE,
  IFF(COUNT(*) = 0, 'PASS', 'FAIL') AS STATUS
FROM expected_metrics e
LEFT JOIN OVERWATCH_SECTION_COMMAND_SOURCE_CONFIG cfg
  ON cfg.SECTION_NAME = e.SECTION_NAME
 AND cfg.SOURCE_KEY = e.SOURCE_KEY
WHERE COALESCE(e.SOURCE_KEY, '') <> ''
  AND cfg.SOURCE_KEY IS NULL
UNION ALL
SELECT
  'SECTION_COMMAND_SOURCE_CONFIG_UNIQUE_SOURCE_KEYS' AS CHECK_NAME,
  COUNT(*) AS OBSERVED_VALUE,
  IFF(COUNT(*) = 0, 'PASS', 'FAIL') AS STATUS
FROM (
  SELECT SECTION_NAME, SOURCE_KEY
  FROM OVERWATCH_SECTION_COMMAND_SOURCE_CONFIG
  GROUP BY SECTION_NAME, SOURCE_KEY
  HAVING COUNT(*) > 1
);
