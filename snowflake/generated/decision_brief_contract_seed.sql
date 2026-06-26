-- Generated from config/decision_brief_contracts.json. Do not edit by hand.
INSERT INTO OVERWATCH_SECTION_COMMAND_SOURCE_CONFIG (
  SECTION_NAME, SOURCE_KEY, SOURCE_OBJECT, REQUIRED,
  TARGET_FRESHNESS_MINUTES, DEFAULT_CONFIDENCE, ENABLED
)
SELECT * FROM VALUES
    ('Executive Landing', 'executive_observability', 'MART_EXECUTIVE_OBSERVABILITY', TRUE, 60, 'allocated', TRUE),
    ('Executive Landing', 'executive_scorecard', 'MART_EXECUTIVE_SCORECARD_SUMMARY', TRUE, 60, 'allocated', TRUE),
    ('Executive Landing', 'executive_forecast', 'MART_EXECUTIVE_FORECAST_SUMMARY', TRUE, 60, 'estimated', TRUE),
    ('Executive Landing', 'closed_loop', 'MART_CLOSED_LOOP_OPERATIONS_SUMMARY', TRUE, 60, 'allocated', TRUE),
    ('Executive Landing', 'production_readiness', 'MART_PRODUCTION_READINESS_SUMMARY', TRUE, 60, 'allocated', TRUE),
    ('Executive Landing', 'data_trust', 'MART_DATA_TRUST_SUMMARY', FALSE, 60, 'allocated', TRUE),
    ('Executive Landing', 'app_observability', 'MART_APP_OBSERVABILITY_SUMMARY', FALSE, 60, 'allocated', TRUE),
    ('DBA Control Room', 'query_hourly', 'MART_DBA_CONTROL_ROOM', TRUE, 30, 'allocated', TRUE),
    ('DBA Control Room', 'query_hourly', 'FACT_QUERY_HOURLY', TRUE, 30, 'allocated', TRUE),
    ('DBA Control Room', 'task_runs', 'FACT_TASK_RUN', TRUE, 30, 'allocated', TRUE),
    ('DBA Control Room', 'action_queue', 'OVERWATCH_ACTION_QUEUE', TRUE, 30, 'allocated', TRUE),
    ('DBA Control Room', 'change_summary', 'MART_CHANGE_INTELLIGENCE_SUMMARY', FALSE, 30, 'allocated', TRUE),
    ('DBA Control Room', 'security_operability', 'FACT_SECURITY_OPERABILITY_DAILY', FALSE, 30, 'allocated', TRUE),
    ('DBA Control Room', 'cost_daily', 'FACT_COST_DAILY', FALSE, 30, 'allocated', TRUE),
    ('Alert Center', 'alert_events', 'ALERT_EVENTS', TRUE, 15, 'exact', TRUE),
    ('Alert Center', 'action_queue', 'OVERWATCH_ACTION_QUEUE', TRUE, 15, 'allocated', TRUE),
    ('Alert Center', 'notification_log', 'ALERT_NOTIFICATION_LOG', TRUE, 15, 'exact', TRUE),
    ('Alert Center', 'acknowledgements', 'ALERT_ACKNOWLEDGEMENTS', FALSE, 15, 'exact', TRUE),
    ('Cost & Contract', 'cost_daily', 'FACT_COST_DAILY', TRUE, 60, 'allocated', TRUE),
    ('Cost & Contract', 'cortex_daily', 'FACT_CORTEX_DAILY', TRUE, 60, 'estimated', TRUE),
    ('Cost & Contract', 'cost_signals', 'FACT_COST_MONITORING_SIGNAL', TRUE, 60, 'allocated', TRUE),
    ('Cost & Contract', 'forecast', 'MART_EXECUTIVE_FORECAST_SUMMARY', FALSE, 60, 'estimated', TRUE),
    ('Cost & Contract', 'value_ledger', 'MART_EXECUTIVE_VALUE_LEDGER', FALSE, 60, 'allocated', TRUE),
    ('Cost & Contract', 'settings', 'OVERWATCH_SETTINGS', TRUE, 60, 'exact', TRUE),
    ('Workload Operations', 'query_hourly', 'FACT_QUERY_HOURLY', TRUE, 30, 'allocated', TRUE),
    ('Workload Operations', 'query_recent', 'FACT_QUERY_DETAIL_RECENT', FALSE, 30, 'allocated', TRUE),
    ('Workload Operations', 'task_runs', 'FACT_TASK_RUN', TRUE, 30, 'allocated', TRUE),
    ('Workload Operations', 'procedure_runs', 'FACT_PROCEDURE_RUN', TRUE, 30, 'allocated', TRUE),
    ('Workload Operations', 'copy_load', 'FACT_COPY_LOAD_DAILY', TRUE, 30, 'allocated', TRUE),
    ('Workload Operations', 'change_summary', 'MART_CHANGE_INTELLIGENCE_SUMMARY', FALSE, 30, 'allocated', TRUE),
    ('Security Monitoring', 'security_operability', 'FACT_SECURITY_OPERABILITY_DAILY', TRUE, 60, 'allocated', TRUE),
    ('Security Monitoring', 'login_daily', 'FACT_LOGIN_DAILY', TRUE, 60, 'allocated', TRUE),
    ('Security Monitoring', 'grant_daily', 'FACT_GRANT_DAILY', TRUE, 60, 'allocated', TRUE),
    ('Security Monitoring', 'security_alerts', 'ALERT_EVENTS', TRUE, 60, 'allocated', TRUE),
    ('Security Monitoring', 'owner_coverage', 'MART_OPERATIONAL_OWNER_COVERAGE', TRUE, 60, 'allocated', TRUE),
    ('Security Monitoring', 'change_summary', 'MART_CHANGE_INTELLIGENCE_SUMMARY', FALSE, 60, 'allocated', TRUE)
  AS v(SECTION_NAME, SOURCE_KEY, SOURCE_OBJECT, REQUIRED, TARGET_FRESHNESS_MINUTES, DEFAULT_CONFIDENCE, ENABLED)
WHERE NOT EXISTS (
  SELECT 1
  FROM OVERWATCH_SECTION_COMMAND_SOURCE_CONFIG cfg
  WHERE cfg.SECTION_NAME = v.SECTION_NAME
    AND cfg.SOURCE_KEY = v.SOURCE_KEY
);
