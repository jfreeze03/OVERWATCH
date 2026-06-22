-- -----------------------------------------------------------------------------
-- 3. Transient mart tables
-- -----------------------------------------------------------------------------

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_WAREHOUSE_HOURLY (
  HOUR_START                   TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  WAREHOUSE_NAME               VARCHAR(300),
  CREDITS_USED                 NUMBER(18,6),
  CREDITS_USED_COMPUTE         NUMBER(18,6),
  CREDITS_USED_CLOUD_SERVICES  NUMBER(18,6),
  EST_COST_USD                 NUMBER(18,2),
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_WAREHOUSE_OPERABILITY_DAILY (
  SNAPSHOT_DATE                DATE,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  WAREHOUSE_NAME               VARCHAR(300),
  CONTROL_SOURCE               VARCHAR(80),
  SEVERITY                     VARCHAR(40),
  SIGNAL                       VARCHAR(120),
  CONTROL_STATE                VARCHAR(120),
  CONTROL_RANK                 NUMBER,
  CAPACITY_SCORE               FLOAT,
  QUERY_ROWS                   NUMBER,
  QUEUE_PRESSURE_ROWS          NUMBER,
  SPILL_PRESSURE_ROWS          NUMBER,
  HIGH_LATENCY_ROWS            NUMBER,
  METERED_CREDITS              FLOAT,
  CREDIT_ALLOCATION_METHOD     VARCHAR(160),
  REVIEW_ROWS                  NUMBER,
  APPROVAL_REQUIRED_ROWS       NUMBER,
  ROLLBACK_REQUIRED_ROWS       NUMBER,
  IMPACT_TELEMETRY_ROWS    NUMBER,
  OPEN_ACTIONS                 NUMBER,
  OVERDUE_OPEN                 NUMBER,
  FIXED_WITHOUT_VERIFICATION   NUMBER,
  VERIFIED_CLOSURES            NUMBER,
  OWNER_APPROVAL_GAP_ROWS      NUMBER,
  NEXT_CONTROL_ACTION          VARCHAR(4000),
  LAST_ACTIVITY_TS             TIMESTAMP_NTZ,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

ALTER TABLE IF EXISTS FACT_WAREHOUSE_OPERABILITY_DAILY ADD COLUMN IF NOT EXISTS IMPACT_TELEMETRY_ROWS NUMBER;

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_SECURITY_OPERABILITY_DAILY (
  SNAPSHOT_DATE                DATE,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  CONTROL_SOURCE               VARCHAR(80),
  FINDING_TYPE                 VARCHAR(120),
  ENTITY                       VARCHAR(500),
  ENTITY_TYPE                  VARCHAR(120),
  SEVERITY                     VARCHAR(40),
  CONTROL_STATE                VARCHAR(120),
  CONTROL_RANK                 NUMBER,
  EVENT_ROWS                   NUMBER,
  REVIEW_ROWS                  NUMBER,
  REVIEW_BLOCKER_ROWS          NUMBER,
  TICKET_REQUIRED_ROWS         NUMBER,
  REVIEW_BY_REQUIRED_ROWS      NUMBER,
  CAPABILITY_PROOF_ROWS        NUMBER,
  NO_DATABASE_CONTEXT_ROWS     NUMBER,
  OPEN_ACTIONS                 NUMBER,
  OVERDUE_OPEN                 NUMBER,
  FIXED_WITHOUT_VERIFICATION   NUMBER,
  VERIFIED_CLOSURES            NUMBER,
  OWNER_APPROVAL_GAP_ROWS      NUMBER,
  NEXT_CONTROL_ACTION          VARCHAR(4000),
  LAST_ACTIVITY_TS             TIMESTAMP_NTZ,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_ACCOUNT_HEALTH_OPERABILITY_DAILY (
  SNAPSHOT_DATE                DATE,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  CONTROL_SOURCE               VARCHAR(80),
  CHECK_NAME                   VARCHAR(200),
  ROUTE                        VARCHAR(120),
  SEVERITY                     VARCHAR(40),
  CONTROL_STATE                VARCHAR(120),
  CONTROL_RANK                 NUMBER,
  HEALTH_SCORE                 FLOAT,
  ISSUE_ROWS                   NUMBER,
  ROUTE_BLOCKER_ROWS           NUMBER,
  QUEUE_REQUIRED_ROWS          NUMBER,
  ACCESS_HYGIENE_ROWS          NUMBER,
  FAILED_LOGIN_ROWS            NUMBER,
  PRIVILEGED_GRANT_ROWS        NUMBER,
  OPEN_ACTIONS                 NUMBER,
  OVERDUE_OPEN                 NUMBER,
  FIXED_WITHOUT_VERIFICATION   NUMBER,
  VERIFIED_CLOSURES            NUMBER,
  OWNER_APPROVAL_GAP_ROWS      NUMBER,
  RECOVERY_RISK_ROWS           NUMBER,
  NEXT_CONTROL_ACTION          VARCHAR(4000),
  LAST_ACTIVITY_TS             TIMESTAMP_NTZ,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_QUERY_HOURLY (
  HOUR_START                   TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  WAREHOUSE_NAME               VARCHAR(300),
  WAREHOUSE_SIZE               VARCHAR(100),
  USER_NAME                    VARCHAR(300),
  ROLE_NAME                    VARCHAR(300),
  DATABASE_NAME                VARCHAR(300),
  ENVIRONMENT                  VARCHAR(100),
  SCHEMA_NAME                  VARCHAR(300),
  QUERY_TYPE                   VARCHAR(100),
  QUERY_COUNT                  NUMBER,
  FAILED_COUNT                 NUMBER,
  AVG_EXECUTION_MS             NUMBER(18,2),
  P95_EXECUTION_MS             NUMBER(18,2),
  TOTAL_ELAPSED_MS             NUMBER,
  TOTAL_QUEUED_MS              NUMBER,
  TOTAL_SPILL_BYTES            NUMBER,
  TOTAL_BYTES_SCANNED          NUMBER,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_QUERY_DETAIL_RECENT (
  QUERY_ID                     VARCHAR(200),
  START_TIME                   TIMESTAMP_NTZ,
  END_TIME                     TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  WAREHOUSE_NAME               VARCHAR(300),
  USER_NAME                    VARCHAR(300),
  ROLE_NAME                    VARCHAR(300),
  DATABASE_NAME                VARCHAR(300),
  ENVIRONMENT                  VARCHAR(100),
  SCHEMA_NAME                  VARCHAR(300),
  QUERY_TYPE                   VARCHAR(100),
  EXECUTION_STATUS             VARCHAR(100),
  WAREHOUSE_SIZE               VARCHAR(100),
  ERROR_CODE                   VARCHAR(100),
  ERROR_MESSAGE                VARCHAR,
  TOTAL_ELAPSED_TIME           NUMBER,
  COMPILATION_TIME             NUMBER,
  EXECUTION_TIME               NUMBER,
  QUEUED_OVERLOAD_TIME         NUMBER,
  QUEUED_PROVISIONING_TIME     NUMBER,
  QUEUED_REPAIR_TIME           NUMBER,
  TRANSACTION_BLOCKED_TIME     NUMBER,
  BYTES_SCANNED                NUMBER,
  BYTES_SPILLED_TO_LOCAL_STORAGE NUMBER,
  BYTES_SPILLED_TO_REMOTE_STORAGE NUMBER,
  PARTITIONS_SCANNED           NUMBER,
  PARTITIONS_TOTAL             NUMBER,
  ROWS_PRODUCED                NUMBER,
  QUERY_HASH                   VARCHAR(300),
  QUERY_TEXT                   VARCHAR,
  QUERY_TAG                    VARCHAR,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_CHARGEBACK_DAILY (
  USAGE_DATE                   DATE,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  ENVIRONMENT_ROLLUP           VARCHAR(100),
  DATABASE_NAME                VARCHAR(300),
  USER_NAME                    VARCHAR(300),
  ROLE_NAME                    VARCHAR(300),
  WAREHOUSE_NAME               VARCHAR(300),
  WAREHOUSE_SIZE               VARCHAR(100),
  QUERY_COUNT                  NUMBER,
  ALLOCATED_CREDITS            NUMBER(18,6),
  EST_COST_USD                 NUMBER(18,2),
  ALLOCATION_CONFIDENCE        VARCHAR(100),
  ALLOCATION_BASIS             VARCHAR(1000),
  CHARGEBACK_READY             VARCHAR(100),
  SCOPE_REVIEW                 VARCHAR(1000),
  COST_OWNER                   VARCHAR(300),
  OWNER_SOURCE                 VARCHAR(100),
  OWNER_EVIDENCE               VARCHAR(1000),
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS DIM_COST_OWNER_TAG (
  SNAPSHOT_DATE                DATE,
  OWNER_SCOPE                  VARCHAR(100),
  OBJECT_DATABASE              VARCHAR(300),
  OBJECT_SCHEMA                VARCHAR(300),
  OBJECT_NAME                  VARCHAR(500),
  TAG_NAME                     VARCHAR(300),
  TAG_VALUE                    VARCHAR(1000),
  OWNER_TYPE                   VARCHAR(100),
  PRIORITY                     NUMBER,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_TASK_RUN (
  SCHEDULED_TIME               TIMESTAMP_NTZ,
  COMPLETED_TIME               TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  DATABASE_NAME                VARCHAR(300),
  ENVIRONMENT                  VARCHAR(100),
  SCHEMA_NAME                  VARCHAR(300),
  ROOT_TASK_NAME               VARCHAR(500),
  TASK_NAME                    VARCHAR(500),
  STATE                        VARCHAR(100),
  QUERY_ID                     VARCHAR(200),
  ERROR_CODE                   VARCHAR(100),
  ERROR_MESSAGE                VARCHAR,
  DURATION_MS                  NUMBER,
  WAREHOUSE_NAME               VARCHAR(300),
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_TASK_CRITICAL_PATH (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  DATABASE_NAME                VARCHAR(300),
  ENVIRONMENT                  VARCHAR(100),
  ROOT_TASK_NAME               VARCHAR(500),
  CRITICAL_PATH_STATE          VARCHAR(100),
  CRITICAL_PATH_SCORE          NUMBER(18,1),
  TASK_COUNT                   NUMBER,
  DOWNSTREAM_TASK_COUNT        NUMBER,
  SUSPENDED_TASKS              NUMBER,
  RUNS_7D                      NUMBER,
  FAILURES_7D                  NUMBER,
  SUCCESSES_7D                 NUMBER,
  MAX_DURATION_SEC             NUMBER(18,2),
  LAST_RUN_AT                  TIMESTAMP_NTZ,
  BLAST_RADIUS                 VARCHAR(100),
  WAREHOUSES                   VARCHAR,
  PROCEDURES                   VARCHAR,
  OWNER_ROLE                   VARCHAR(300),
  APPROVAL_PATH                VARCHAR(1000),
  SOURCE_FRESHNESS             VARCHAR(1000),
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS DIM_TASK_SNAPSHOT (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  DATABASE_NAME                VARCHAR(300),
  ENVIRONMENT                  VARCHAR(100),
  SCHEMA_NAME                  VARCHAR(300),
  TASK_NAME                    VARCHAR(500),
  ROOT_TASK_NAME               VARCHAR(500),
  STATE                        VARCHAR(100),
  SCHEDULE                     VARCHAR,
  WAREHOUSE_NAME               VARCHAR(300),
  PREDECESSORS                 VARIANT,
  DEFINITION                   VARCHAR,
  PROCEDURE_NAME               VARCHAR
);

CREATE TRANSIENT TABLE IF NOT EXISTS DIM_PROCEDURE_SNAPSHOT (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  DATABASE_NAME                VARCHAR(300),
  ENVIRONMENT                  VARCHAR(100),
  SCHEMA_NAME                  VARCHAR(300),
  PROCEDURE_NAME               VARCHAR(500),
  OWNER_ROLE                   VARCHAR(300),
  PROCEDURE_LANGUAGE           VARCHAR(100),
  ARGUMENT_SIGNATURE           VARCHAR,
  LAST_ALTERED                 TIMESTAMP_NTZ,
  IS_ORPHAN_CANDIDATE          BOOLEAN
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_PROCEDURE_RUN (
  START_TIME                   TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  DATABASE_NAME                VARCHAR(300),
  ENVIRONMENT                  VARCHAR(100),
  SCHEMA_NAME                  VARCHAR(300),
  PROCEDURE_NAME               VARCHAR(500),
  CALL_QUERY_ID                VARCHAR(200),
  ROOT_QUERY_ID                VARCHAR(200),
  CHILD_QUERY_COUNT            NUMBER,
  TOTAL_DURATION_MS            NUMBER,
  EST_CREDITS                  NUMBER(18,6),
  EST_COST_USD                 NUMBER(18,2),
  STATUS                       VARCHAR(100),
  ERROR_MESSAGE                VARCHAR,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_LOGIN_DAILY (
  LOGIN_DATE                   DATE,
  COMPANY                      VARCHAR(100),
  USER_NAME                    VARCHAR(300),
  CLIENT_IP                    VARCHAR(300),
  REPORTED_CLIENT_TYPE         VARCHAR(300),
  REPORTED_CLIENT_VERSION      VARCHAR(300),
  SUCCESS_COUNT                NUMBER,
  FAILURE_COUNT                NUMBER,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_OBJECT_CHANGE (
  START_TIME                   TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  QUERY_ID                     VARCHAR(200),
  USER_NAME                    VARCHAR(300),
  ROLE_NAME                    VARCHAR(300),
  DATABASE_NAME                VARCHAR(300),
  ENVIRONMENT                  VARCHAR(100),
  SCHEMA_NAME                  VARCHAR(300),
  CHANGE_CATEGORY              VARCHAR(100),
  QUERY_TYPE                   VARCHAR(100),
  QUERY_TAG                    VARCHAR,
  QUERY_TEXT                   VARCHAR,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_CHANGE_CONTROL_OPERABILITY_DAILY (
  SNAPSHOT_DATE                DATE,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  CONTROL_SOURCE               VARCHAR(80),
  CONTROL_KEY                  VARCHAR(500),
  FINDING_TYPE                 VARCHAR(120),
  ENTITY                       VARCHAR(500),
  OWNER                        VARCHAR(200),
  ESCALATION_TARGET            VARCHAR(200),
  SEVERITY                     VARCHAR(40),
  EVIDENCE_ROWS                NUMBER,
  HIGH_RISK_CHANGES            NUMBER,
  ROUTE_BLOCKED                NUMBER,
  CLOSURE_BLOCKED              NUMBER,
  REVIEW_READY                 NUMBER,
  MISSING_TICKET_ROWS          NUMBER,
  IAC_GAP_ROWS                 NUMBER,
  MISSING_QUERY_ID_ROWS        NUMBER,
  OPEN_ACTIONS                 NUMBER,
  OVERDUE_OPEN                 NUMBER,
  FIXED_WITHOUT_VERIFICATION   NUMBER,
  VERIFIED_CLOSURES            NUMBER,
  OWNER_APPROVAL_GAP_ROWS      NUMBER,
  CONTROL_STATE                VARCHAR(120),
  CONTROL_RANK                 NUMBER,
  NEXT_CONTROL_ACTION          VARCHAR(4000),
  LAST_ACTIVITY_TS             TIMESTAMP_NTZ,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_GRANT_DAILY (
  SNAPSHOT_DATE                DATE,
  COMPANY                      VARCHAR(100),
  ROLE_NAME                    VARCHAR(300),
  GRANTEE_NAME                 VARCHAR(300),
  GRANTED_TO                   VARCHAR(100),
  CREATED_ON                   TIMESTAMP_NTZ,
  DELETED_ON                   TIMESTAMP_NTZ,
  GRANT_COUNT                  NUMBER,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

ALTER TABLE IF EXISTS FACT_GRANT_DAILY ADD COLUMN IF NOT EXISTS CREATED_ON TIMESTAMP_NTZ;


CREATE TRANSIENT TABLE IF NOT EXISTS FACT_STORAGE_DAILY (
  SNAPSHOT_DATE                DATE,
  COMPANY                      VARCHAR(100),
  DATABASE_NAME                VARCHAR(300),
  ENVIRONMENT                  VARCHAR(100),
  ACTIVE_BYTES                 NUMBER,
  TIME_TRAVEL_BYTES            NUMBER,
  FAILSAFE_BYTES               NUMBER,
  RETAINED_FOR_CLONE_BYTES     NUMBER,
  STAGE_BYTES                  NUMBER DEFAULT 0,
  HYBRID_TABLE_STORAGE_BYTES   NUMBER DEFAULT 0,
  ARCHIVE_STORAGE_COOL_BYTES   NUMBER DEFAULT 0,
  ARCHIVE_STORAGE_COLD_BYTES   NUMBER DEFAULT 0,
  EST_STORAGE_TB               NUMBER(18,4),
  EST_COST_USD                 NUMBER(18,2),
  STANDARD_STORAGE_COST_USD    NUMBER(18,2) DEFAULT 0,
  HYBRID_STORAGE_COST_USD      NUMBER(18,2) DEFAULT 0,
  ARCHIVE_COOL_COST_USD        NUMBER(18,2) DEFAULT 0,
  ARCHIVE_COLD_COST_USD        NUMBER(18,2) DEFAULT 0,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS DIM_TABLE_SNAPSHOT (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  DATABASE_NAME                VARCHAR(300),
  ENVIRONMENT                  VARCHAR(100),
  SCHEMA_NAME                  VARCHAR(300),
  TABLE_NAME                   VARCHAR(500),
  TABLE_TYPE                   VARCHAR(100),
  ROW_COUNT                    NUMBER,
  BYTES                        NUMBER,
  LAST_ALTERED                 TIMESTAMP_LTZ,
  CREATED                      TIMESTAMP_LTZ,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_COPY_LOAD_DAILY (
  LOAD_DATE                    DATE,
  COMPANY                      VARCHAR(100),
  DATABASE_NAME                VARCHAR(300),
  ENVIRONMENT                  VARCHAR(100),
  SCHEMA_NAME                  VARCHAR(300),
  TABLE_NAME                   VARCHAR(500),
  STATUS                       VARCHAR(100),
  FILE_COUNT                   NUMBER,
  ROW_COUNT                    NUMBER,
  ROW_PARSED                   NUMBER,
  ERROR_COUNT                  NUMBER,
  FILE_SIZE_BYTES              NUMBER,
  BYTES_BILLED                 NUMBER,
  LAST_SEEN                    TIMESTAMP_LTZ,
  LATEST_ERROR                 VARCHAR,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);


CREATE TRANSIENT TABLE IF NOT EXISTS FACT_CORTEX_DAILY (
  USAGE_DATE                   DATE,
  COMPANY                      VARCHAR(100),
  USER_ID                      VARCHAR(300),
  SOURCE                       VARCHAR(100),
  CREDITS_USED                 NUMBER(18,6),
  EST_COST_USD                 NUMBER(18,2),
  REQUEST_COUNT                NUMBER,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_COST_DAILY (
  USAGE_DATE                         DATE,
  COMPANY                            VARCHAR(100),
  SERVICE_CATEGORY                   VARCHAR(120),
  SERVICE_TYPE                       VARCHAR(200),
  CREDITS_USED_COMPUTE               NUMBER(18,6),
  CREDITS_USED_CLOUD_SERVICES        NUMBER(18,6),
  CREDITS_ADJUSTMENT_CLOUD_SERVICES  NUMBER(18,6),
  CREDITS_BILLED                     NUMBER(18,6),
  RATE_USD                           NUMBER(18,4),
  EST_COST_USD                       NUMBER(18,2),
  SOURCE_VIEW                        VARCHAR(300),
  LOAD_TS                            TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

ALTER TABLE IF EXISTS FACT_COST_DAILY ADD COLUMN IF NOT EXISTS RATE_USD NUMBER(18,4);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_COST_SOURCE_HEALTH_DAILY (
  SNAPSHOT_DATE                 DATE,
  SOURCE_NAME                   VARCHAR(200),
  SOURCE_SCOPE                  VARCHAR(200),
  STATUS                        VARCHAR(80),
  EXPECTED_LATENCY_HOURS        NUMBER,
  OBSERVED_ROWS                 NUMBER,
  LAST_DATA_DATE                DATE,
  ERROR_MESSAGE                 VARCHAR(4000),
  LOAD_TS                       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_COST_MONITORING_SIGNAL (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  SIGNAL_TYPE                  VARCHAR(120),
  SEVERITY                     VARCHAR(40),
  ENTITY_TYPE                  VARCHAR(120),
  ENTITY_NAME                  VARCHAR(500),
  CONTROL_SURFACE              VARCHAR(200),
  CONTROL_SCOPE                VARCHAR(200),
  EVIDENCE                     VARCHAR(4000),
  NEXT_ACTION                  VARCHAR(4000),
  PROOF_QUERY                  VARCHAR(8000),
  VALUE_AT_RISK_USD            NUMBER(18,2),
  SOURCE                       VARCHAR(200),
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_COST_INCIDENT_TIMELINE (
  INCIDENT_ID                  VARCHAR(200),
  EVENT_TS                     TIMESTAMP_NTZ,
  EVENT_ORDER                  NUMBER,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  ENTITY_NAME                  VARCHAR(500),
  EVENT_TYPE                   VARCHAR(160),
  SEVERITY                     VARCHAR(40),
  EVIDENCE                     VARCHAR(4000),
  NEXT_ACTION                  VARCHAR(4000),
  PROOF_QUERY                  VARCHAR(8000),
  SOURCE                       VARCHAR(200),
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS MART_DBA_CONTROL_ROOM (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  HEALTH_SCORE                 NUMBER(5,2),
  FAILED_QUERIES_24H           NUMBER,
  FAILED_TASKS_24H             NUMBER,
  QUEUED_MS_24H                NUMBER,
  CREDITS_24H                  NUMBER(18,6),
  COST_24H_USD                 NUMBER(18,2),
  CORTEX_COST_7D_USD           NUMBER(18,2),
  SECURITY_EVENTS_24H          NUMBER,
  OBJECT_CHANGES_24H           NUMBER,
  TOP_RISK                     VARCHAR(1000),
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS MART_EXECUTIVE_OBSERVABILITY (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  WINDOW_DAYS                  NUMBER,
  PANEL                        VARCHAR(100),
  METRIC                       VARCHAR(200),
  DIMENSION                    VARCHAR(500),
  PERIOD_START                 TIMESTAMP_NTZ,
  VALUE                        FLOAT,
  VALUE_USD                    FLOAT,
  UNIT                         VARCHAR(100),
  SORT_ORDER                   NUMBER,
  SOURCE                       VARCHAR(500),
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- -----------------------------------------------------------------------------
-- Enterprise operating model: Finding -> Owner -> Trust -> Impact -> Action -> Value
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS OVERWATCH_DATA_TRUST_SOURCE (
  SOURCE_KEY                   VARCHAR(200) PRIMARY KEY,
  SOURCE_NAME                  VARCHAR(300),
  SOURCE_OBJECT                VARCHAR(500),
  SOURCE_CLASS                 VARCHAR(100),
  SURFACE                      VARCHAR(200),
  TARGET_FRESHNESS_MIN         NUMBER,
  DEFAULT_CONFIDENCE           VARCHAR(40),
  BUSINESS_IMPACT              VARCHAR(1000),
  OWNER_ROUTE                  VARCHAR(200),
  ENABLED                      BOOLEAN DEFAULT TRUE,
  CREATED_AT                   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  UPDATED_AT                   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

MERGE INTO OVERWATCH_DATA_TRUST_SOURCE tgt
USING (
  SELECT * FROM VALUES
    ('FACT_COST_DAILY', 'Cost facts', 'FACT_COST_DAILY', 'MART', 'Cost & Contract', 1440, 'allocated', 'Cost and contract metrics may be incomplete or stale.', 'DBA / Cost owner', TRUE),
    ('FACT_CORTEX_DAILY', 'Cortex facts', 'FACT_CORTEX_DAILY', 'MART', 'Cost & Contract', 1440, 'allocated', 'Cortex spend and anomaly alerts may understate AI cost exposure.', 'DBA / AI cost route', TRUE),
    ('FACT_QUERY_HOURLY', 'Query performance facts', 'FACT_QUERY_HOURLY', 'MART', 'Workload Operations', 120, 'allocated', 'Runtime, queue, spill, and warehouse pressure may be stale.', 'DBA / Workload owner', TRUE),
    ('FACT_QUERY_DETAIL_RECENT', 'Query detail facts', 'FACT_QUERY_DETAIL_RECENT', 'MART', 'Workload Operations', 120, 'exact', 'Failure/root-cause samples may be stale for drilldowns.', 'DBA / Workload owner', TRUE),
    ('FACT_TASK_RUN', 'Task run facts', 'FACT_TASK_RUN', 'MART', 'Workload Operations', 120, 'exact', 'Task failure and dependency views may miss current failures.', 'DBA / Pipeline owner', TRUE),
    ('ALERT_EVENTS', 'Alert events', 'ALERT_EVENTS', 'APP_TABLE', 'Alert Center', 60, 'exact', 'Alert Center may miss active incidents or routed ownership gaps.', 'DBA / Alert owner', TRUE),
    ('OVERWATCH_ACTION_QUEUE', 'Action queue', 'OVERWATCH_ACTION_QUEUE', 'APP_TABLE', 'DBA Control Room', 60, 'estimated', 'Owned action, closure, and savings proof may be incomplete.', 'DBA On-Call', TRUE),
    ('MART_DBA_CONTROL_ROOM', 'Control-room summary', 'MART_DBA_CONTROL_ROOM', 'MART', 'DBA Control Room', 120, 'allocated', 'Executive and DBA triage may not reflect the latest operational state.', 'DBA On-Call', TRUE),
    ('MART_EXECUTIVE_OBSERVABILITY', 'Executive observability', 'MART_EXECUTIVE_OBSERVABILITY', 'MART', 'Executive Landing', 120, 'allocated', 'Leadership first paint may be stale or incomplete.', 'DBA / Platform', TRUE),
    ('OVERWATCH_USAGE_LOG', 'App usage and query log', 'OVERWATCH_USAGE_LOG', 'APP_TABLE', 'DBA Control Room', 1440, 'fallback', 'App self-observability may have no query-tag/runtime evidence.', 'DBA / Platform', TRUE)
  AS t(SOURCE_KEY, SOURCE_NAME, SOURCE_OBJECT, SOURCE_CLASS, SURFACE, TARGET_FRESHNESS_MIN, DEFAULT_CONFIDENCE, BUSINESS_IMPACT, OWNER_ROUTE, ENABLED)
) src
ON tgt.SOURCE_KEY = src.SOURCE_KEY
WHEN MATCHED THEN UPDATE SET
  SOURCE_NAME = src.SOURCE_NAME,
  SOURCE_OBJECT = src.SOURCE_OBJECT,
  SOURCE_CLASS = src.SOURCE_CLASS,
  SURFACE = src.SURFACE,
  TARGET_FRESHNESS_MIN = src.TARGET_FRESHNESS_MIN,
  DEFAULT_CONFIDENCE = src.DEFAULT_CONFIDENCE,
  BUSINESS_IMPACT = src.BUSINESS_IMPACT,
  OWNER_ROUTE = src.OWNER_ROUTE,
  ENABLED = src.ENABLED,
  UPDATED_AT = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
  SOURCE_KEY, SOURCE_NAME, SOURCE_OBJECT, SOURCE_CLASS, SURFACE,
  TARGET_FRESHNESS_MIN, DEFAULT_CONFIDENCE, BUSINESS_IMPACT, OWNER_ROUTE, ENABLED
)
VALUES (
  src.SOURCE_KEY, src.SOURCE_NAME, src.SOURCE_OBJECT, src.SOURCE_CLASS, src.SURFACE,
  src.TARGET_FRESHNESS_MIN, src.DEFAULT_CONFIDENCE, src.BUSINESS_IMPACT, src.OWNER_ROUTE, src.ENABLED
);

CREATE TRANSIENT TABLE IF NOT EXISTS OVERWATCH_DATA_TRUST_STATUS (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  SOURCE_KEY                   VARCHAR(200),
  SOURCE_NAME                  VARCHAR(300),
  SOURCE_OBJECT                VARCHAR(500),
  SOURCE_CLASS                 VARCHAR(100),
  SURFACE                      VARCHAR(200),
  LATEST_SOURCE_TS             TIMESTAMP_NTZ,
  AGE_MINUTES                  NUMBER,
  TARGET_FRESHNESS_MIN         NUMBER,
  STATUS                       VARCHAR(40),
  CONFIDENCE                   VARCHAR(40),
  BUSINESS_IMPACT              VARCHAR(1000),
  OWNER_ROUTE                  VARCHAR(200),
  NEXT_ACTION                  VARCHAR(1000),
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS MART_DATA_TRUST_SUMMARY (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  TRUST_DOMAIN                 VARCHAR(100),
  METRIC                       VARCHAR(200),
  SOURCE_NAME                  VARCHAR(300),
  STATUS                       VARCHAR(40),
  CONFIDENCE                   VARCHAR(40),
  VALUE                        FLOAT,
  VALUE_USD                    FLOAT,
  FRESHNESS_MINUTES            NUMBER,
  SOURCE_OBJECT                VARCHAR(500),
  OWNER_ROUTE                  VARCHAR(200),
  BUSINESS_IMPACT              VARCHAR(1000),
  NEXT_ACTION                  VARCHAR(1000),
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS OVERWATCH_OPERATIONAL_OWNER_MAP (
  ENTITY_TYPE                  VARCHAR(100),
  ENTITY_PATTERN               VARCHAR(500),
  COMPANY                      VARCHAR(100) DEFAULT 'ALL',
  ENVIRONMENT                  VARCHAR(100) DEFAULT 'ALL',
  OWNER_ROUTE                  VARCHAR(200),
  OWNER_EMAIL                  VARCHAR(500),
  ONCALL_PRIMARY               VARCHAR(200),
  ESCALATION_TARGET            VARCHAR(200),
  SOURCE                       VARCHAR(200),
  ACTIVE                       BOOLEAN DEFAULT TRUE,
  CREATED_AT                   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  UPDATED_AT                   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

MERGE INTO OVERWATCH_OPERATIONAL_OWNER_MAP tgt
USING (
  SELECT * FROM VALUES
    ('WAREHOUSE', '*', 'ALL', 'ALL', 'DBA / Cost owner', NULL, NULL, 'DBA On-Call', 'default-route', TRUE),
    ('TASK', '*', 'ALL', 'ALL', 'DBA / Pipeline owner', NULL, NULL, 'DBA On-Call', 'default-route', TRUE),
    ('PROCEDURE', '*', 'ALL', 'ALL', 'DBA / Workload owner', NULL, NULL, 'DBA On-Call', 'default-route', TRUE),
    ('USER', '*', 'ALL', 'ALL', 'IAM / Security route', NULL, NULL, 'Security On-Call', 'default-route', TRUE),
    ('ROLE', '*', 'ALL', 'ALL', 'IAM / Security route', NULL, NULL, 'Security On-Call', 'default-route', TRUE),
    ('DATABASE', '*', 'ALL', 'ALL', 'Data owner route', NULL, NULL, 'DBA On-Call', 'default-route', TRUE),
    ('SCHEMA', '*', 'ALL', 'ALL', 'Data owner route', NULL, NULL, 'DBA On-Call', 'default-route', TRUE),
    ('ALERT', '*', 'ALL', 'ALL', 'DBA / Alert owner', NULL, NULL, 'DBA On-Call', 'default-route', TRUE),
    ('ACTION', '*', 'ALL', 'ALL', 'DBA On-Call', NULL, NULL, 'DBA On-Call', 'default-route', TRUE),
    ('CORTEX', '*', 'ALL', 'ALL', 'DBA / AI cost route', NULL, NULL, 'DBA On-Call', 'default-route', TRUE)
  AS t(ENTITY_TYPE, ENTITY_PATTERN, COMPANY, ENVIRONMENT, OWNER_ROUTE, OWNER_EMAIL, ONCALL_PRIMARY, ESCALATION_TARGET, SOURCE, ACTIVE)
) src
ON UPPER(tgt.ENTITY_TYPE) = UPPER(src.ENTITY_TYPE)
AND COALESCE(tgt.ENTITY_PATTERN, '*') = COALESCE(src.ENTITY_PATTERN, '*')
AND COALESCE(tgt.COMPANY, 'ALL') = COALESCE(src.COMPANY, 'ALL')
AND COALESCE(tgt.ENVIRONMENT, 'ALL') = COALESCE(src.ENVIRONMENT, 'ALL')
WHEN MATCHED THEN UPDATE SET
  OWNER_ROUTE = src.OWNER_ROUTE,
  OWNER_EMAIL = src.OWNER_EMAIL,
  ONCALL_PRIMARY = src.ONCALL_PRIMARY,
  ESCALATION_TARGET = src.ESCALATION_TARGET,
  SOURCE = src.SOURCE,
  ACTIVE = src.ACTIVE,
  UPDATED_AT = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
  ENTITY_TYPE, ENTITY_PATTERN, COMPANY, ENVIRONMENT, OWNER_ROUTE, OWNER_EMAIL,
  ONCALL_PRIMARY, ESCALATION_TARGET, SOURCE, ACTIVE
)
VALUES (
  src.ENTITY_TYPE, src.ENTITY_PATTERN, src.COMPANY, src.ENVIRONMENT, src.OWNER_ROUTE,
  src.OWNER_EMAIL, src.ONCALL_PRIMARY, src.ESCALATION_TARGET, src.SOURCE, src.ACTIVE
);

CREATE TRANSIENT TABLE IF NOT EXISTS MART_OPERATIONAL_OWNER_COVERAGE (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  SURFACE                      VARCHAR(200),
  ENTITY_TYPE                  VARCHAR(100),
  TOTAL_ITEMS                  NUMBER,
  ROUTED_ITEMS                 NUMBER,
  GAP_ITEMS                    NUMBER,
  COVERAGE_PCT                 NUMBER(8,2),
  TRUST_LEVEL                  VARCHAR(100),
  CONFIDENCE                   VARCHAR(40),
  TOP_GAP_ENTITY               VARCHAR(500),
  OWNER_ROUTE                  VARCHAR(200),
  NEXT_ACTION                  VARCHAR(1000),
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS OVERWATCH_VALUE_LEDGER (
  LEDGER_ID                    VARCHAR(64) PRIMARY KEY,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  FINDING                      VARCHAR(4000),
  ENTITY_TYPE                  VARCHAR(100),
  ENTITY_NAME                  VARCHAR(500),
  OWNER_ROUTE                  VARCHAR(200),
  STATUS                       VARCHAR(100) DEFAULT 'Proposed',
  EXPECTED_SAVINGS_USD         NUMBER(18,2) DEFAULT 0,
  ACTUAL_VERIFIED_SAVINGS_USD  NUMBER(18,2) DEFAULT 0,
  CONFIDENCE                   VARCHAR(40) DEFAULT 'estimated',
  TRUST_LEVEL                  VARCHAR(100) DEFAULT 'Verification Pending',
  BUSINESS_IMPACT              VARCHAR(4000),
  ACTION_TAKEN                 VARCHAR(4000),
  EVIDENCE                     VARCHAR(8000),
  VERIFICATION_WINDOW_START    TIMESTAMP_NTZ,
  VERIFICATION_WINDOW_END      TIMESTAMP_NTZ,
  VERIFIED_BY                  VARCHAR(200),
  VERIFIED_AT                  TIMESTAMP_NTZ,
  ROLLBACK_NOTES               VARCHAR(4000),
  CREATED_AT                   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  UPDATED_AT                   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS MART_EXECUTIVE_VALUE_LEDGER (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  WINDOW_DAYS                  NUMBER,
  METRIC                       VARCHAR(200),
  STATUS                       VARCHAR(100),
  OWNER_ROUTE                  VARCHAR(200),
  EXPECTED_SAVINGS_USD         NUMBER(18,2),
  VERIFIED_SAVINGS_USD         NUMBER(18,2),
  UNVERIFIED_ESTIMATE_USD      NUMBER(18,2),
  CONFIDENCE                   VARCHAR(40),
  VALUE_STATE                  VARCHAR(100),
  OPEN_ITEMS                   NUMBER,
  VERIFIED_ITEMS               NUMBER,
  EVIDENCE                     VARCHAR(4000),
  NEXT_ACTION                  VARCHAR(1000),
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS OVERWATCH_APP_OBSERVABILITY (
  EVENT_TS                     TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  APP_VERSION                  VARCHAR(40),
  SECTION_NAME                 VARCHAR(200),
  EVENT_TYPE                   VARCHAR(100),
  RENDER_MS                    NUMBER,
  QUERY_COUNT                  NUMBER,
  QUERY_FAILURE_COUNT          NUMBER,
  OVERWATCH_COST_USD           NUMBER(18,4),
  VALIDATION_STATUS            VARCHAR(100),
  DEPLOYMENT_VERSION           VARCHAR(100),
  LAST_DEPLOYMENT_TS           TIMESTAMP_NTZ,
  DETAIL                       VARCHAR(2000),
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS MART_APP_OBSERVABILITY_SUMMARY (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  APP_VERSION                  VARCHAR(40),
  HEALTH_STATE                 VARCHAR(100),
  SECTION_NAME                 VARCHAR(200),
  P95_RENDER_MS                NUMBER,
  SLOW_SECTION_COUNT           NUMBER,
  QUERY_FAILURE_COUNT          NUMBER,
  OVERWATCH_COST_USD           NUMBER(18,4),
  VALIDATION_STATUS            VARCHAR(100),
  LAST_DEPLOYMENT_TS           TIMESTAMP_NTZ,
  CONFIDENCE                   VARCHAR(40),
  SOURCE                       VARCHAR(500),
  NEXT_ACTION                  VARCHAR(1000),
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- -----------------------------------------------------------------------------
-- Phase 2A: live production validation and readiness contracts
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS OVERWATCH_PRODUCTION_CHECKLIST (
  CHECK_KEY                    VARCHAR(200) PRIMARY KEY,
  CHECK_DOMAIN                 VARCHAR(100),
  CHECK_NAME                   VARCHAR(300),
  SURFACE                      VARCHAR(200),
  SEVERITY                     VARCHAR(40),
  REQUIRED_OBJECT              VARCHAR(500),
  FIRST_PAINT_SAFE             BOOLEAN DEFAULT TRUE,
  EXPLICIT_LOAD_REQUIRED       BOOLEAN DEFAULT FALSE,
  EXPECTED_STATE               VARCHAR(100),
  OWNER_ROUTE                  VARCHAR(200),
  RUNBOOK_STEP                 VARCHAR(2000),
  ENABLED                      BOOLEAN DEFAULT TRUE,
  CREATED_AT                   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  UPDATED_AT                   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

MERGE INTO OVERWATCH_PRODUCTION_CHECKLIST tgt
USING (
  SELECT * FROM VALUES
    ('DEPLOYMENT_VERSION', 'Deployment', 'Deployment version recorded', 'Executive Landing', 'High', 'OVERWATCH_SCHEMA_MIGRATION', TRUE, FALSE, 'Ready', 'DBA / Platform', 'Confirm the latest setup migration row matches the deployed app bundle.', TRUE),
    ('VALIDATION_RUN', 'Validation', 'Production validation run recorded', 'Executive Landing', 'High', 'MART_PRODUCTION_READINESS_SUMMARY', TRUE, FALSE, 'Ready', 'DBA / Platform', 'Run OVERWATCH_MART_VALIDATION.sql after setup and after material refresh changes.', TRUE),
    ('ROLE_READINESS', 'Role Readiness', 'OVERWATCH role model reviewed', 'DBA Control Room', 'Medium', 'OVERWATCH_ROLE_READINESS_REQUIREMENT', FALSE, TRUE, 'Ready', 'Security / DBA', 'Confirm OVERWATCH_VIEWER, OVERWATCH_OPERATOR, OVERWATCH_ADMIN, and OVERWATCH_BREAKGLASS are either deployed or explicitly mapped to legacy admin roles.', TRUE),
    ('PRIVILEGE_READINESS', 'Privilege Readiness', 'Required Snowflake privileges reviewed', 'DBA Control Room', 'High', 'OVERWATCH_PRIVILEGE_READINESS_REQUIREMENT', FALSE, TRUE, 'Ready', 'Security / DBA', 'Confirm imported SNOWFLAKE privileges, warehouse usage, schema usage, table DML, view select, procedure usage, and task ownership are granted to the runtime roles.', TRUE),
    ('REFRESH_HEALTH', 'Refresh Health', 'Mart refresh jobs healthy', 'DBA Control Room', 'High', 'OVERWATCH_LOAD_AUDIT', TRUE, TRUE, 'Ready', 'DBA On-Call', 'Review failed OVERWATCH_LOAD_AUDIT rows before trusting first-paint summaries.', TRUE),
    ('SUMMARY_MART_DATA', 'Refresh Health', 'Summary mart rows available', 'Executive Landing', 'High', 'MART_*', TRUE, FALSE, 'Ready', 'DBA / Platform', 'Run the mart refresh procedures and confirm each first-paint mart has recent rows.', TRUE),
    ('DATA_FRESHNESS', 'Data Freshness', 'Data trust sources fresh', 'Executive Landing', 'High', 'MART_DATA_TRUST_SUMMARY', TRUE, FALSE, 'Ready', 'DBA / Platform', 'Refresh stale sources or disclose telemetry lag before operational action.', TRUE),
    ('CONFIG_DRIFT', 'Configuration Drift', 'Required settings customized and present', 'DBA Control Room', 'Medium', 'OVERWATCH_SETTINGS', TRUE, TRUE, 'Ready', 'DBA / Platform', 'Review placeholder alert settings and required pricing/retention settings after deployment.', TRUE),
    ('ENVIRONMENT_READINESS', 'Environment Readiness', 'Runtime context has database/schema/warehouse/role', 'Executive Landing', 'High', 'CURRENT_CONTEXT', TRUE, FALSE, 'Ready', 'DBA / Platform', 'Confirm the app runs in the intended database, schema, warehouse, and role context.', TRUE)
  AS t(CHECK_KEY, CHECK_DOMAIN, CHECK_NAME, SURFACE, SEVERITY, REQUIRED_OBJECT, FIRST_PAINT_SAFE, EXPLICIT_LOAD_REQUIRED, EXPECTED_STATE, OWNER_ROUTE, RUNBOOK_STEP, ENABLED)
) src
ON tgt.CHECK_KEY = src.CHECK_KEY
WHEN MATCHED THEN UPDATE SET
  CHECK_DOMAIN = src.CHECK_DOMAIN,
  CHECK_NAME = src.CHECK_NAME,
  SURFACE = src.SURFACE,
  SEVERITY = src.SEVERITY,
  REQUIRED_OBJECT = src.REQUIRED_OBJECT,
  FIRST_PAINT_SAFE = src.FIRST_PAINT_SAFE,
  EXPLICIT_LOAD_REQUIRED = src.EXPLICIT_LOAD_REQUIRED,
  EXPECTED_STATE = src.EXPECTED_STATE,
  OWNER_ROUTE = src.OWNER_ROUTE,
  RUNBOOK_STEP = src.RUNBOOK_STEP,
  ENABLED = src.ENABLED,
  UPDATED_AT = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
  CHECK_KEY, CHECK_DOMAIN, CHECK_NAME, SURFACE, SEVERITY, REQUIRED_OBJECT,
  FIRST_PAINT_SAFE, EXPLICIT_LOAD_REQUIRED, EXPECTED_STATE, OWNER_ROUTE, RUNBOOK_STEP, ENABLED
)
VALUES (
  src.CHECK_KEY, src.CHECK_DOMAIN, src.CHECK_NAME, src.SURFACE, src.SEVERITY,
  src.REQUIRED_OBJECT, src.FIRST_PAINT_SAFE, src.EXPLICIT_LOAD_REQUIRED,
  src.EXPECTED_STATE, src.OWNER_ROUTE, src.RUNBOOK_STEP, src.ENABLED
);

CREATE TABLE IF NOT EXISTS OVERWATCH_ROLE_READINESS_REQUIREMENT (
  ROLE_NAME                    VARCHAR(200) PRIMARY KEY,
  ROLE_CLASS                   VARCHAR(100),
  REQUIRED_FOR                 VARCHAR(500),
  REQUIRED                     BOOLEAN DEFAULT TRUE,
  LEGACY_COMPAT                BOOLEAN DEFAULT FALSE,
  CHECK_METHOD                 VARCHAR(1000),
  OWNER_ROUTE                  VARCHAR(200),
  ENABLED                      BOOLEAN DEFAULT TRUE,
  CREATED_AT                   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  UPDATED_AT                   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

MERGE INTO OVERWATCH_ROLE_READINESS_REQUIREMENT tgt
USING (
  SELECT * FROM VALUES
    ('OVERWATCH_VIEWER', 'Target', 'Read-only monitoring and executive scorecards', TRUE, FALSE, 'SHOW ROLES LIKE ''OVERWATCH_VIEWER''; verify USAGE on app database/schema and SELECT on marts.', 'Security / DBA', TRUE),
    ('OVERWATCH_OPERATOR', 'Target', 'Operational triage, alert acknowledgement, and action queue updates', TRUE, FALSE, 'SHOW ROLES LIKE ''OVERWATCH_OPERATOR''; verify action queue DML and procedure usage.', 'Security / DBA', TRUE),
    ('OVERWATCH_ADMIN', 'Target', 'Settings, refresh controls, and guarded DBA administration', TRUE, FALSE, 'SHOW ROLES LIKE ''OVERWATCH_ADMIN''; verify warehouse/task/procedure control grants.', 'Security / DBA', TRUE),
    ('OVERWATCH_BREAKGLASS', 'Target', 'Emergency DBA intervention with explicit audit trail', FALSE, FALSE, 'SHOW ROLES LIKE ''OVERWATCH_BREAKGLASS''; verify it is disabled or tightly controlled until approved.', 'Security / DBA', TRUE),
    ('SNOW_SYSADMINS', 'Legacy Compatibility', 'Legacy admin compatibility during transition', FALSE, TRUE, 'Confirm SNOW_SYSADMINS remains intentionally mapped while OVERWATCH roles are adopted.', 'Security / DBA', TRUE),
    ('SNOW_ACCOUNTADMINS', 'Legacy Compatibility', 'Legacy account-admin compatibility during transition', FALSE, TRUE, 'Confirm SNOW_ACCOUNTADMINS remains intentionally mapped while OVERWATCH roles are adopted.', 'Security / DBA', TRUE)
  AS t(ROLE_NAME, ROLE_CLASS, REQUIRED_FOR, REQUIRED, LEGACY_COMPAT, CHECK_METHOD, OWNER_ROUTE, ENABLED)
) src
ON UPPER(tgt.ROLE_NAME) = UPPER(src.ROLE_NAME)
WHEN MATCHED THEN UPDATE SET
  ROLE_CLASS = src.ROLE_CLASS,
  REQUIRED_FOR = src.REQUIRED_FOR,
  REQUIRED = src.REQUIRED,
  LEGACY_COMPAT = src.LEGACY_COMPAT,
  CHECK_METHOD = src.CHECK_METHOD,
  OWNER_ROUTE = src.OWNER_ROUTE,
  ENABLED = src.ENABLED,
  UPDATED_AT = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
  ROLE_NAME, ROLE_CLASS, REQUIRED_FOR, REQUIRED, LEGACY_COMPAT, CHECK_METHOD, OWNER_ROUTE, ENABLED
)
VALUES (
  src.ROLE_NAME, src.ROLE_CLASS, src.REQUIRED_FOR, src.REQUIRED, src.LEGACY_COMPAT,
  src.CHECK_METHOD, src.OWNER_ROUTE, src.ENABLED
);

CREATE TABLE IF NOT EXISTS OVERWATCH_PRIVILEGE_READINESS_REQUIREMENT (
  PRIVILEGE_KEY                VARCHAR(200) PRIMARY KEY,
  OBJECT_NAME                  VARCHAR(500),
  OBJECT_TYPE                  VARCHAR(100),
  REQUIRED_PRIVILEGE           VARCHAR(200),
  REQUIRED_FOR                 VARCHAR(1000),
  REQUIRED                     BOOLEAN DEFAULT TRUE,
  CHECK_METHOD                 VARCHAR(1000),
  OWNER_ROUTE                  VARCHAR(200),
  REMEDIATION_HINT             VARCHAR(2000),
  ENABLED                      BOOLEAN DEFAULT TRUE,
  CREATED_AT                   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  UPDATED_AT                   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

MERGE INTO OVERWATCH_PRIVILEGE_READINESS_REQUIREMENT tgt
USING (
  SELECT * FROM VALUES
    ('SNOWFLAKE_IMPORTED_PRIVILEGES', 'SNOWFLAKE', 'DATABASE', 'IMPORTED PRIVILEGES', 'ACCOUNT_USAGE-backed mart refreshes', TRUE, 'SHOW GRANTS ON DATABASE SNOWFLAKE;', 'Security / DBA', 'Grant imported privileges to the approved OVERWATCH runtime/admin roles after security review.', TRUE),
    ('COMPUTE_WH_USAGE', 'COMPUTE_WH', 'WAREHOUSE', 'USAGE', 'Scheduled mart refresh and Streamlit runtime queries', TRUE, 'SHOW GRANTS ON WAREHOUSE COMPUTE_WH;', 'Security / DBA', 'Grant USAGE on COMPUTE_WH to the runtime roles and keep AUTO_SUSPEND controlled.', TRUE),
    ('APP_DB_USAGE', 'DBA_MAINT_DB', 'DATABASE', 'USAGE', 'Read OVERWATCH mart objects', TRUE, 'SHOW GRANTS ON DATABASE DBA_MAINT_DB;', 'Security / DBA', 'Grant USAGE on the app database to runtime roles.', TRUE),
    ('APP_SCHEMA_USAGE', 'DBA_MAINT_DB.OVERWATCH', 'SCHEMA', 'USAGE', 'Read OVERWATCH mart schema', TRUE, 'SHOW GRANTS ON SCHEMA DBA_MAINT_DB.OVERWATCH;', 'Security / DBA', 'Grant USAGE on the app schema to runtime roles.', TRUE),
    ('APP_TABLE_SELECT', 'DBA_MAINT_DB.OVERWATCH.*', 'TABLE', 'SELECT', 'First-paint dashboards and explicit-load detail panels', TRUE, 'SHOW GRANTS TO ROLE <role_name>;', 'Security / DBA', 'Grant SELECT on all/future OVERWATCH tables to viewer/operator/admin roles.', TRUE),
    ('APP_ACTION_DML', 'OVERWATCH_ACTION_QUEUE', 'TABLE', 'INSERT, UPDATE', 'Review-gated action, value, and alert workflow updates', TRUE, 'SHOW GRANTS ON TABLE OVERWATCH_ACTION_QUEUE;', 'Security / DBA', 'Grant DML only to operator/admin roles that own review workflows.', TRUE),
    ('APP_PROCEDURE_USAGE', 'SP_OVERWATCH_*', 'PROCEDURE', 'USAGE', 'Manual and scheduled mart refresh procedures', TRUE, 'SHOW PROCEDURES LIKE ''SP_OVERWATCH_%''; SHOW GRANTS TO ROLE <role_name>;', 'Security / DBA', 'Grant procedure usage to approved refresh/admin roles only.', TRUE),
    ('APP_TASK_OPERATE', 'OVERWATCH_*', 'TASK', 'OPERATE/OWNERSHIP', 'Scheduled mart health and recovery', TRUE, 'SHOW TASKS IN SCHEMA; SHOW GRANTS TO ROLE <role_name>;', 'Security / DBA', 'Keep task ownership with the DBA/admin role; do not grant broad task control to viewers.', TRUE)
  AS t(PRIVILEGE_KEY, OBJECT_NAME, OBJECT_TYPE, REQUIRED_PRIVILEGE, REQUIRED_FOR, REQUIRED, CHECK_METHOD, OWNER_ROUTE, REMEDIATION_HINT, ENABLED)
) src
ON tgt.PRIVILEGE_KEY = src.PRIVILEGE_KEY
WHEN MATCHED THEN UPDATE SET
  OBJECT_NAME = src.OBJECT_NAME,
  OBJECT_TYPE = src.OBJECT_TYPE,
  REQUIRED_PRIVILEGE = src.REQUIRED_PRIVILEGE,
  REQUIRED_FOR = src.REQUIRED_FOR,
  REQUIRED = src.REQUIRED,
  CHECK_METHOD = src.CHECK_METHOD,
  OWNER_ROUTE = src.OWNER_ROUTE,
  REMEDIATION_HINT = src.REMEDIATION_HINT,
  ENABLED = src.ENABLED,
  UPDATED_AT = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
  PRIVILEGE_KEY, OBJECT_NAME, OBJECT_TYPE, REQUIRED_PRIVILEGE, REQUIRED_FOR,
  REQUIRED, CHECK_METHOD, OWNER_ROUTE, REMEDIATION_HINT, ENABLED
)
VALUES (
  src.PRIVILEGE_KEY, src.OBJECT_NAME, src.OBJECT_TYPE, src.REQUIRED_PRIVILEGE,
  src.REQUIRED_FOR, src.REQUIRED, src.CHECK_METHOD, src.OWNER_ROUTE,
  src.REMEDIATION_HINT, src.ENABLED
);

CREATE TRANSIENT TABLE IF NOT EXISTS OVERWATCH_PRODUCTION_VALIDATION_STATUS (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  CHECK_DOMAIN                 VARCHAR(100),
  CHECK_KEY                    VARCHAR(200),
  CHECK_NAME                   VARCHAR(300),
  VALIDATION_STATUS            VARCHAR(40),
  RISK_LEVEL                   VARCHAR(40),
  VALUE                        FLOAT,
  VALUE_DETAIL                 VARCHAR(4000),
  SOURCE_OBJECT                VARCHAR(500),
  FRESHNESS_MINUTES            NUMBER,
  OWNER_ROUTE                  VARCHAR(200),
  RUNBOOK_STEP                 VARCHAR(2000),
  CONFIDENCE                   VARCHAR(40),
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS MART_PRODUCTION_READINESS_SUMMARY (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  DEPLOYMENT_VERSION           VARCHAR(100),
  LAST_DEPLOYMENT_TS           TIMESTAMP_NTZ,
  LAST_VALIDATION_TS           TIMESTAMP_NTZ,
  VALIDATION_STATUS            VARCHAR(40),
  MISSING_PRIVILEGES           NUMBER,
  FAILED_MART_REFRESHES        NUMBER,
  MISSING_SUMMARY_MARTS        NUMBER,
  STALE_SOURCE_COUNT           NUMBER,
  CONFIG_DRIFT_COUNT           NUMBER,
  ENVIRONMENT_READINESS        VARCHAR(100),
  READINESS_SCORE              NUMBER,
  TOP_RISK                     VARCHAR(1000),
  CONFIDENCE                   VARCHAR(40),
  NEXT_ACTION                  VARCHAR(1000),
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- -----------------------------------------------------------------------------
-- Phase 2B: leadership Executive Scorecard
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS OVERWATCH_EXECUTIVE_SCORECARD_CONFIG (
  SCORE_KEY                    VARCHAR(100) PRIMARY KEY,
  SCORE_NAME                   VARCHAR(200),
  DISPLAY_ORDER                NUMBER,
  SCORE_DOMAIN                 VARCHAR(100),
  RED_BELOW                    NUMBER DEFAULT 70,
  YELLOW_BELOW                 NUMBER DEFAULT 85,
  OWNER_ROUTE                  VARCHAR(200),
  DRIVER_SOURCE                VARCHAR(1000),
  RECOMMENDED_ACTION           VARCHAR(1000),
  ENABLED                      BOOLEAN DEFAULT TRUE,
  CREATED_AT                   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  UPDATED_AT                   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

MERGE INTO OVERWATCH_EXECUTIVE_SCORECARD_CONFIG tgt
USING (
  SELECT * FROM VALUES
    ('SNOWFLAKE_HEALTH', 'Snowflake Health Score', 10, 'Platform Health', 70, 85, 'DBA / Platform', 'MART_DBA_CONTROL_ROOM; MART_APP_OBSERVABILITY_SUMMARY; MART_PRODUCTION_READINESS_SUMMARY', 'Open DBA Control Room and resolve failed refresh, app health, or control-room blocker rows.', TRUE),
    ('COST_EFFICIENCY', 'Cost Efficiency Score', 20, 'Cost', 70, 85, 'DBA / Cost owner', 'FACT_COST_MONITORING_SIGNAL; ALERT_EVENTS; MART_EXECUTIVE_VALUE_LEDGER', 'Open Cost & Contract, explain top cost drivers, and route verified savings work.', TRUE),
    ('SECURITY', 'Security Score', 30, 'Security', 75, 88, 'Security / DBA', 'ALERT_EVENTS; MART_OPERATIONAL_OWNER_COVERAGE', 'Open Security Monitoring and review privileged, access, ownership, and route-gap drivers.', TRUE),
    ('OPERATIONAL_RISK', 'Operational Risk Score', 40, 'Operations', 70, 85, 'DBA On-Call', 'ALERT_EVENTS; MART_OPERATIONAL_OWNER_COVERAGE; OVERWATCH_ACTION_QUEUE', 'Open Alert Center and DBA Control Room to assign owner, SLA, and next action.', TRUE),
    ('DATA_TRUST', 'Data Trust Score', 50, 'Data Trust', 75, 90, 'DBA / Platform', 'MART_DATA_TRUST_SUMMARY', 'Open DBA Control Room data trust diagnostics and refresh stale source marts.', TRUE),
    ('PRODUCTION_READINESS', 'Production Readiness Score', 60, 'Production Readiness', 75, 90, 'DBA / Platform', 'MART_PRODUCTION_READINESS_SUMMARY; OVERWATCH_PRODUCTION_VALIDATION_STATUS', 'Open DBA Control Room production readiness validation before expanding usage.', TRUE)
  AS t(SCORE_KEY, SCORE_NAME, DISPLAY_ORDER, SCORE_DOMAIN, RED_BELOW, YELLOW_BELOW, OWNER_ROUTE, DRIVER_SOURCE, RECOMMENDED_ACTION, ENABLED)
) src
ON tgt.SCORE_KEY = src.SCORE_KEY
WHEN MATCHED THEN UPDATE SET
  SCORE_NAME = src.SCORE_NAME,
  DISPLAY_ORDER = src.DISPLAY_ORDER,
  SCORE_DOMAIN = src.SCORE_DOMAIN,
  RED_BELOW = src.RED_BELOW,
  YELLOW_BELOW = src.YELLOW_BELOW,
  OWNER_ROUTE = src.OWNER_ROUTE,
  DRIVER_SOURCE = src.DRIVER_SOURCE,
  RECOMMENDED_ACTION = src.RECOMMENDED_ACTION,
  ENABLED = src.ENABLED,
  UPDATED_AT = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
  SCORE_KEY, SCORE_NAME, DISPLAY_ORDER, SCORE_DOMAIN, RED_BELOW, YELLOW_BELOW,
  OWNER_ROUTE, DRIVER_SOURCE, RECOMMENDED_ACTION, ENABLED
)
VALUES (
  src.SCORE_KEY, src.SCORE_NAME, src.DISPLAY_ORDER, src.SCORE_DOMAIN,
  src.RED_BELOW, src.YELLOW_BELOW, src.OWNER_ROUTE, src.DRIVER_SOURCE,
  src.RECOMMENDED_ACTION, src.ENABLED
);

CREATE TRANSIENT TABLE IF NOT EXISTS OVERWATCH_EXECUTIVE_SCORECARD_HISTORY (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  SCORE_KEY                    VARCHAR(100),
  SCORE_NAME                   VARCHAR(200),
  CURRENT_SCORE                NUMBER(6,2),
  STATUS                       VARCHAR(40),
  TREND                        VARCHAR(40),
  TREND_DELTA                  NUMBER(8,2),
  RISK_LEVEL                   VARCHAR(40),
  TOP_DRIVER                   VARCHAR(2000),
  RECOMMENDED_ACTION           VARCHAR(2000),
  OWNER_ROUTE                  VARCHAR(200),
  OWNER_GAP                    BOOLEAN DEFAULT FALSE,
  VALUE_AT_RISK_USD            NUMBER(18,2) DEFAULT 0,
  CONFIDENCE                   VARCHAR(40),
  SOURCE_OBJECTS               VARCHAR(1000),
  LAST_REFRESHED_TS            TIMESTAMP_NTZ,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS MART_EXECUTIVE_SCORECARD_SUMMARY (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  SCORE_KEY                    VARCHAR(100),
  SCORE_NAME                   VARCHAR(200),
  DISPLAY_ORDER                NUMBER,
  CURRENT_SCORE                NUMBER(6,2),
  STATUS                       VARCHAR(40),
  TREND                        VARCHAR(40),
  TREND_DELTA                  NUMBER(8,2),
  RISK_LEVEL                   VARCHAR(40),
  TOP_DRIVER                   VARCHAR(2000),
  RECOMMENDED_ACTION           VARCHAR(2000),
  OWNER_ROUTE                  VARCHAR(200),
  OWNER_GAP                    BOOLEAN DEFAULT FALSE,
  VALUE_AT_RISK_USD            NUMBER(18,2) DEFAULT 0,
  CONFIDENCE                   VARCHAR(40),
  SOURCE_OBJECTS               VARCHAR(1000),
  LAST_REFRESHED_TS            TIMESTAMP_NTZ,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- -----------------------------------------------------------------------------
-- Phase 2C: leadership forecasting
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS OVERWATCH_FORECAST_CONFIG (
  FORECAST_KEY                 VARCHAR(100) PRIMARY KEY,
  FORECAST_NAME                VARCHAR(200),
  DISPLAY_ORDER                NUMBER,
  FORECAST_DOMAIN              VARCHAR(100),
  VALUE_UNIT                   VARCHAR(40),
  OWNER_ROUTE                  VARCHAR(200),
  SOURCE_OBJECTS               VARCHAR(1000),
  METHODOLOGY                  VARCHAR(4000),
  RECOMMENDED_ACTION           VARCHAR(2000),
  CONFIDENCE_RULE              VARCHAR(1000),
  ENABLED                      BOOLEAN DEFAULT TRUE,
  CREATED_AT                   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  UPDATED_AT                   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

MERGE INTO OVERWATCH_FORECAST_CONFIG tgt
USING (
  SELECT * FROM VALUES
    ('EOM_SPEND', 'End-of-month Snowflake spend forecast', 10, 'Cost', 'USD', 'DBA / Cost owner', 'FACT_COST_DAILY; FACT_CORTEX_DAILY', 'Month-to-date observed spend plus average observed daily spend projected through month end.', 'Open Cost & Contract, explain the top spend drivers, and route owner-backed cost actions.', 'High >= 14 observed days, Medium >= 7 observed days, otherwise Low.', TRUE),
    ('EOQ_SPEND', 'End-of-quarter spend forecast', 20, 'Cost', 'USD', 'DBA / Cost owner', 'FACT_COST_DAILY; FACT_CORTEX_DAILY', 'Quarter-to-date observed spend plus average observed daily spend projected through quarter end.', 'Review quarter run-rate, contract exposure, and cost action queue before the next operating review.', 'High >= 30 observed quarter days, Medium >= 14 observed quarter days, otherwise Low.', TRUE),
    ('CONTRACT_BURN', 'Contract burn projection', 30, 'Cost', 'percent', 'DBA / Contract owner', 'FACT_COST_DAILY; FACT_CORTEX_DAILY; OVERWATCH_SETTINGS', 'Projected quarter spend divided by configured contract or budget target.', 'Set or validate contract targets, then route spend above target to Cost & Contract ownership.', 'Low when no contract target is configured; otherwise follows quarter spend confidence.', TRUE),
    ('CREDIT_ANOMALY', 'Credit anomaly projection', 40, 'Cost', 'percent', 'DBA / Cost owner', 'FACT_COST_DAILY; FACT_CORTEX_DAILY', 'Recent seven-day credit burn compared with the 30-day daily credit baseline.', 'Investigate warehouses, users, or Cortex demand causing recent credit burn to diverge from baseline.', 'High >= 21 observed baseline days, Medium >= 10 baseline days, otherwise Low.', TRUE),
    ('STORAGE_GROWTH', 'Storage growth forecast', 50, 'Storage', 'TB', 'DBA / Data owner', 'FACT_STORAGE_DAILY', 'Latest storage footprint plus recent daily storage growth projected 30 days forward.', 'Review database/storage owners, retention, stage cleanup, and archive policy for rising storage.', 'High >= 21 days of storage trend, Medium >= 7 days, otherwise Low.', TRUE),
    ('WAREHOUSE_PRESSURE', 'Warehouse saturation / queue pressure forecast', 60, 'Workload', 'seconds', 'DBA / Workload owner', 'FACT_QUERY_HOURLY', 'Last seven days of queue pressure adjusted by movement versus the prior seven days.', 'Open Workload Operations and review warehouse sizing, queue, spill, and concurrency drivers.', 'High >= 500 recent queries, Medium >= 100 recent queries, otherwise Low.', TRUE),
    ('SLA_RISK', 'SLA risk forecast', 70, 'Operations', 'count', 'DBA On-Call', 'FACT_TASK_RUN; FACT_PROCEDURE_RUN', 'Recent task and procedure failures projected into the next seven-day operating window.', 'Open Workload Operations and assign owners for late, failed, or retrying task/procedure chains.', 'High >= 10 recent incidents, Medium >= 3 recent incidents, otherwise Low.', TRUE)
  AS t(
    FORECAST_KEY, FORECAST_NAME, DISPLAY_ORDER, FORECAST_DOMAIN, VALUE_UNIT,
    OWNER_ROUTE, SOURCE_OBJECTS, METHODOLOGY, RECOMMENDED_ACTION,
    CONFIDENCE_RULE, ENABLED
  )
) src
ON tgt.FORECAST_KEY = src.FORECAST_KEY
WHEN MATCHED THEN UPDATE SET
  FORECAST_NAME = src.FORECAST_NAME,
  DISPLAY_ORDER = src.DISPLAY_ORDER,
  FORECAST_DOMAIN = src.FORECAST_DOMAIN,
  VALUE_UNIT = src.VALUE_UNIT,
  OWNER_ROUTE = src.OWNER_ROUTE,
  SOURCE_OBJECTS = src.SOURCE_OBJECTS,
  METHODOLOGY = src.METHODOLOGY,
  RECOMMENDED_ACTION = src.RECOMMENDED_ACTION,
  CONFIDENCE_RULE = src.CONFIDENCE_RULE,
  ENABLED = src.ENABLED,
  UPDATED_AT = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
  FORECAST_KEY, FORECAST_NAME, DISPLAY_ORDER, FORECAST_DOMAIN, VALUE_UNIT,
  OWNER_ROUTE, SOURCE_OBJECTS, METHODOLOGY, RECOMMENDED_ACTION,
  CONFIDENCE_RULE, ENABLED
)
VALUES (
  src.FORECAST_KEY, src.FORECAST_NAME, src.DISPLAY_ORDER, src.FORECAST_DOMAIN,
  src.VALUE_UNIT, src.OWNER_ROUTE, src.SOURCE_OBJECTS, src.METHODOLOGY,
  src.RECOMMENDED_ACTION, src.CONFIDENCE_RULE, src.ENABLED
);

CREATE TRANSIENT TABLE IF NOT EXISTS OVERWATCH_FORECAST_HISTORY (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  FORECAST_KEY                 VARCHAR(100),
  FORECAST_NAME                VARCHAR(200),
  FORECAST_DOMAIN              VARCHAR(100),
  FORECAST_VALUE               NUMBER(18,4),
  CURRENT_ACTUAL               NUMBER(18,4),
  PRIOR_PERIOD_VALUE           NUMBER(18,4),
  TREND_DIRECTION              VARCHAR(40),
  CONFIDENCE                   VARCHAR(40),
  METHODOLOGY                  VARCHAR(4000),
  MAIN_DRIVER                  VARCHAR(2000),
  RECOMMENDED_ACTION           VARCHAR(2000),
  OWNER_ROUTE                  VARCHAR(200),
  OWNER_GAP                    BOOLEAN DEFAULT FALSE,
  VALUE_UNIT                   VARCHAR(40),
  VALUE_AT_RISK_USD            NUMBER(18,2) DEFAULT 0,
  SOURCE_OBJECTS               VARCHAR(1000),
  LAST_REFRESHED_TS            TIMESTAMP_NTZ,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS MART_EXECUTIVE_FORECAST_SUMMARY (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  FORECAST_KEY                 VARCHAR(100),
  FORECAST_NAME                VARCHAR(200),
  DISPLAY_ORDER                NUMBER,
  FORECAST_DOMAIN              VARCHAR(100),
  FORECAST_VALUE               NUMBER(18,4),
  CURRENT_ACTUAL               NUMBER(18,4),
  PRIOR_PERIOD_VALUE           NUMBER(18,4),
  TREND_DIRECTION              VARCHAR(40),
  CONFIDENCE                   VARCHAR(40),
  METHODOLOGY                  VARCHAR(4000),
  MAIN_DRIVER                  VARCHAR(2000),
  RECOMMENDED_ACTION           VARCHAR(2000),
  OWNER_ROUTE                  VARCHAR(200),
  OWNER_GAP                    BOOLEAN DEFAULT FALSE,
  VALUE_UNIT                   VARCHAR(40),
  VALUE_AT_RISK_USD            NUMBER(18,2) DEFAULT 0,
  SOURCE_OBJECTS               VARCHAR(1000),
  LAST_REFRESHED_TS            TIMESTAMP_NTZ,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- -----------------------------------------------------------------------------
-- Phase 2D: Change Intelligence
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS OVERWATCH_CHANGE_RULE (
  CHANGE_TYPE                  VARCHAR(100) PRIMARY KEY,
  CHANGE_CATEGORY              VARCHAR(100),
  OBJECT_TYPE                  VARCHAR(100),
  RISK_LEVEL                   VARCHAR(40),
  BUSINESS_IMPACT              VARCHAR(2000),
  OWNER_ROUTE                  VARCHAR(200),
  CONFIDENCE                   VARCHAR(40),
  SOURCE_OBJECTS               VARCHAR(1000),
  MATCH_HINT                   VARCHAR(1000),
  ENABLED                      BOOLEAN DEFAULT TRUE,
  CREATED_AT                   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  UPDATED_AT                   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

MERGE INTO OVERWATCH_CHANGE_RULE tgt
USING (
  SELECT * FROM VALUES
    ('WAREHOUSE_CHANGE', 'Warehouse changes', 'WAREHOUSE', 'Medium', 'Warehouse setting changes can alter cost, queueing, auto-suspend, timeout, and workload behavior.', 'DBA / Cost owner', 'allocated', 'FACT_OBJECT_CHANGE; FACT_COST_MONITORING_SIGNAL; ALERT_EVENTS', 'WAREHOUSE keywords in object-change telemetry', TRUE),
    ('ROLE_CHANGE', 'Role changes', 'ROLE', 'High', 'Role changes can alter access boundaries and incident blast radius.', 'IAM / Security route', 'allocated', 'FACT_OBJECT_CHANGE; FACT_GRANT_DAILY; ALERT_EVENTS', 'ROLE keywords or role grants', TRUE),
    ('GRANT_CHANGE', 'Grant changes', 'GRANT', 'High', 'Grant changes can introduce privilege drift, access exceptions, or audit findings.', 'IAM / Security route', 'allocated', 'FACT_GRANT_DAILY; FACT_OBJECT_CHANGE; ALERT_EVENTS', 'GRANT or REVOKE telemetry', TRUE),
    ('TASK_CHANGE', 'Task changes', 'TASK', 'Medium', 'Task changes can affect pipeline freshness, downstream SLA, and orchestration reliability.', 'DBA / Pipeline owner', 'estimated', 'FACT_OBJECT_CHANGE; DIM_TASK_SNAPSHOT; FACT_TASK_RUN; ALERT_EVENTS', 'TASK keywords or task snapshots', TRUE),
    ('PROCEDURE_CHANGE', 'Procedure changes', 'PROCEDURE', 'Medium', 'Procedure changes can alter workload behavior, stored procedure cost, and downstream task outcomes.', 'DBA / Workload owner', 'estimated', 'FACT_OBJECT_CHANGE; DIM_PROCEDURE_SNAPSHOT; FACT_PROCEDURE_RUN; ALERT_EVENTS', 'PROCEDURE keywords or procedure snapshots', TRUE),
    ('NETWORK_POLICY_CHANGE', 'Network policy changes', 'NETWORK POLICY', 'High', 'Network policy changes can affect access controls and connectivity posture.', 'Security / DBA', 'allocated', 'FACT_OBJECT_CHANGE; ALERT_EVENTS', 'NETWORK POLICY keywords', TRUE),
    ('INTEGRATION_CHANGE', 'Integration changes', 'INTEGRATION', 'High', 'Integration changes can affect external access, storage integration, notification, or data movement paths.', 'Security / Platform', 'allocated', 'FACT_OBJECT_CHANGE; ALERT_EVENTS', 'INTEGRATION keywords', TRUE),
    ('OBJECT_CHANGE', 'Database/schema/object changes', 'OBJECT', 'Medium', 'Object changes can break dependent workloads, alter data contracts, or explain incident timing.', 'Data owner route', 'allocated', 'FACT_OBJECT_CHANGE; ALERT_EVENTS', 'DATABASE, SCHEMA, TABLE, VIEW, or object DDL keywords', TRUE),
    ('SECURITY_SENSITIVE_CHANGE', 'Security-sensitive changes', 'SECURITY', 'Critical', 'Security-sensitive changes require audit review because they may alter privileged access or exposure.', 'Security / DBA', 'allocated', 'FACT_OBJECT_CHANGE; FACT_GRANT_DAILY; ALERT_EVENTS', 'SECURITY, POLICY, INTEGRATION, OWNERSHIP, ADMIN, or privileged grant keywords', TRUE)
  AS t(CHANGE_TYPE, CHANGE_CATEGORY, OBJECT_TYPE, RISK_LEVEL, BUSINESS_IMPACT, OWNER_ROUTE, CONFIDENCE, SOURCE_OBJECTS, MATCH_HINT, ENABLED)
) src
ON tgt.CHANGE_TYPE = src.CHANGE_TYPE
WHEN MATCHED THEN UPDATE SET
  CHANGE_CATEGORY = src.CHANGE_CATEGORY,
  OBJECT_TYPE = src.OBJECT_TYPE,
  RISK_LEVEL = src.RISK_LEVEL,
  BUSINESS_IMPACT = src.BUSINESS_IMPACT,
  OWNER_ROUTE = src.OWNER_ROUTE,
  CONFIDENCE = src.CONFIDENCE,
  SOURCE_OBJECTS = src.SOURCE_OBJECTS,
  MATCH_HINT = src.MATCH_HINT,
  ENABLED = src.ENABLED,
  UPDATED_AT = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
  CHANGE_TYPE, CHANGE_CATEGORY, OBJECT_TYPE, RISK_LEVEL, BUSINESS_IMPACT,
  OWNER_ROUTE, CONFIDENCE, SOURCE_OBJECTS, MATCH_HINT, ENABLED
)
VALUES (
  src.CHANGE_TYPE, src.CHANGE_CATEGORY, src.OBJECT_TYPE, src.RISK_LEVEL,
  src.BUSINESS_IMPACT, src.OWNER_ROUTE, src.CONFIDENCE, src.SOURCE_OBJECTS,
  src.MATCH_HINT, src.ENABLED
);

CREATE TRANSIENT TABLE IF NOT EXISTS OVERWATCH_CHANGE_EVENT (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  CHANGE_ID                    VARCHAR(200),
  CHANGE_TYPE                  VARCHAR(100),
  CHANGE_CATEGORY              VARCHAR(100),
  OBJECT_TYPE                  VARCHAR(100),
  OBJECT_NAME                  VARCHAR(500),
  CHANGED_BY                   VARCHAR(300),
  CHANGE_TS                    TIMESTAMP_NTZ,
  BEFORE_VALUE                 VARCHAR(4000),
  AFTER_VALUE                  VARCHAR(4000),
  RISK_LEVEL                   VARCHAR(40),
  BUSINESS_IMPACT              VARCHAR(2000),
  OWNER_ROUTE                  VARCHAR(200),
  OWNER_GAP                    BOOLEAN DEFAULT FALSE,
  RELATED_ALERT_COUNT          NUMBER DEFAULT 0,
  RELATED_INCIDENTS            VARCHAR(4000),
  CONFIDENCE                   VARCHAR(40),
  SOURCE_OBJECTS               VARCHAR(1000),
  LAST_REFRESHED_TS            TIMESTAMP_NTZ,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS OVERWATCH_CHANGE_CORRELATION (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  CHANGE_ID                    VARCHAR(200),
  CHANGE_TYPE                  VARCHAR(100),
  OBJECT_TYPE                  VARCHAR(100),
  OBJECT_NAME                  VARCHAR(500),
  CHANGE_TS                    TIMESTAMP_NTZ,
  CHANGED_BY                   VARCHAR(300),
  CORRELATION_TYPE             VARCHAR(100),
  RELATED_SIGNAL               VARCHAR(500),
  RELATED_ENTITY               VARCHAR(500),
  RELATED_TS                   TIMESTAMP_NTZ,
  RELATED_ALERT_COUNT          NUMBER DEFAULT 0,
  CORRELATION_WINDOW_HOURS     NUMBER,
  CORRELATION_STRENGTH         VARCHAR(40),
  CORRELATION_LABEL            VARCHAR(100),
  RISK_LEVEL                   VARCHAR(40),
  BUSINESS_IMPACT              VARCHAR(2000),
  OWNER_ROUTE                  VARCHAR(200),
  CONFIDENCE                   VARCHAR(40),
  EVIDENCE                     VARCHAR(4000),
  LAST_REFRESHED_TS            TIMESTAMP_NTZ,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS MART_CHANGE_INTELLIGENCE_SUMMARY (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  CHANGE_TYPE                  VARCHAR(100),
  CHANGE_CATEGORY              VARCHAR(100),
  OBJECT_TYPE                  VARCHAR(100),
  CHANGE_COUNT                 NUMBER DEFAULT 0,
  HIGH_RISK_COUNT              NUMBER DEFAULT 0,
  OWNER_GAP_COUNT              NUMBER DEFAULT 0,
  RELATED_ALERT_COUNT          NUMBER DEFAULT 0,
  CORRELATION_CANDIDATE_COUNT  NUMBER DEFAULT 0,
  LATEST_CHANGE_TS             TIMESTAMP_NTZ,
  TOP_OBJECT_NAME              VARCHAR(500),
  TOP_CHANGED_BY               VARCHAR(300),
  RISK_LEVEL                   VARCHAR(40),
  BUSINESS_IMPACT              VARCHAR(2000),
  OWNER_ROUTE                  VARCHAR(200),
  CONFIDENCE                   VARCHAR(40),
  LAST_REFRESHED_TS            TIMESTAMP_NTZ,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- -----------------------------------------------------------------------------
-- Phase 2E: Closed Loop Operations
-- -----------------------------------------------------------------------------

CREATE TRANSIENT TABLE IF NOT EXISTS OVERWATCH_ACTION_WORKFLOW (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  WORKFLOW_ID                  VARCHAR(200),
  ACTION_SOURCE                VARCHAR(100),
  SOURCE_ID                    VARCHAR(200),
  ACTION_DOMAIN                VARCHAR(100),
  FINDING                      VARCHAR(4000),
  SOURCE_TELEMETRY             VARCHAR(8000),
  ENTITY_TYPE                  VARCHAR(100),
  ENTITY_NAME                  VARCHAR(500),
  OWNER_ROUTE                  VARCHAR(200),
  OWNER_GAP                    BOOLEAN DEFAULT FALSE,
  BUSINESS_IMPACT              VARCHAR(4000),
  RISK_LEVEL                   VARCHAR(40),
  RECOMMENDED_ACTION           VARCHAR(4000),
  ACTION_STATUS                VARCHAR(100),
  APPROVAL_STATUS              VARCHAR(100),
  APPROVED_BY                  VARCHAR(200),
  APPROVAL_TS                  TIMESTAMP_NTZ,
  EXECUTION_MODE               VARCHAR(100),
  REVIEW_SQL_TEXT              VARCHAR(16000),
  REVIEW_ACTION_TEXT           VARCHAR(8000),
  ROLLBACK_GUIDANCE            VARCHAR(4000),
  VERIFICATION_STEPS           VARCHAR(8000),
  VERIFICATION_STATUS          VARCHAR(100),
  EXPECTED_SAVINGS_USD         NUMBER(18,2) DEFAULT 0,
  ACTUAL_VERIFIED_SAVINGS_USD  NUMBER(18,2) DEFAULT 0,
  EVIDENCE                     VARCHAR(8000),
  CLOSED_TS                    TIMESTAMP_NTZ,
  LAST_REFRESHED_TS            TIMESTAMP_NTZ,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS OVERWATCH_ACTION_APPROVAL (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  WORKFLOW_ID                  VARCHAR(200),
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  ACTION_DOMAIN                VARCHAR(100),
  APPROVAL_STATUS              VARCHAR(100),
  APPROVED_BY                  VARCHAR(200),
  APPROVAL_TS                  TIMESTAMP_NTZ,
  APPROVAL_ROUTE               VARCHAR(200),
  APPROVAL_REQUIRED            BOOLEAN DEFAULT TRUE,
  APPROVAL_EVIDENCE            VARCHAR(4000),
  RISK_LEVEL                   VARCHAR(40),
  OWNER_ROUTE                  VARCHAR(200),
  LAST_REFRESHED_TS            TIMESTAMP_NTZ,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS OVERWATCH_ACTION_EXECUTION_PLAN (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  WORKFLOW_ID                  VARCHAR(200),
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  ACTION_DOMAIN                VARCHAR(100),
  EXECUTION_MODE               VARCHAR(100),
  EXECUTION_STATUS             VARCHAR(100),
  REVIEW_SQL_TEXT              VARCHAR(16000),
  REVIEW_ACTION_TEXT           VARCHAR(8000),
  DANGEROUS_ACTION_FLAG        BOOLEAN DEFAULT FALSE,
  EXECUTION_ALLOWED_IN_APP     BOOLEAN DEFAULT FALSE,
  ROLLBACK_GUIDANCE            VARCHAR(4000),
  VERIFICATION_STEPS           VARCHAR(8000),
  LAST_REFRESHED_TS            TIMESTAMP_NTZ,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS OVERWATCH_ACTION_VERIFICATION (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  WORKFLOW_ID                  VARCHAR(200),
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  ACTION_DOMAIN                VARCHAR(100),
  VERIFICATION_STATUS          VARCHAR(100),
  VERIFICATION_STEPS           VARCHAR(8000),
  EXPECTED_SAVINGS_USD         NUMBER(18,2) DEFAULT 0,
  ACTUAL_VERIFIED_SAVINGS_USD  NUMBER(18,2) DEFAULT 0,
  VERIFICATION_WINDOW_START    TIMESTAMP_NTZ,
  VERIFICATION_WINDOW_END      TIMESTAMP_NTZ,
  VERIFIED_BY                  VARCHAR(200),
  VERIFIED_AT                  TIMESTAMP_NTZ,
  EVIDENCE                     VARCHAR(8000),
  LAST_REFRESHED_TS            TIMESTAMP_NTZ,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS OVERWATCH_ACTION_EVIDENCE (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  WORKFLOW_ID                  VARCHAR(200),
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  ACTION_DOMAIN                VARCHAR(100),
  EVIDENCE_TYPE                VARCHAR(100),
  SOURCE_OBJECT                VARCHAR(500),
  SOURCE_TELEMETRY             VARCHAR(8000),
  EVIDENCE                     VARCHAR(8000),
  CONFIDENCE                   VARCHAR(40),
  LAST_REFRESHED_TS            TIMESTAMP_NTZ,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS MART_CLOSED_LOOP_OPERATIONS_SUMMARY (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  ACTION_DOMAIN                VARCHAR(100),
  OPEN_ACTION_COUNT            NUMBER DEFAULT 0,
  APPROVAL_REQUIRED_COUNT      NUMBER DEFAULT 0,
  APPROVED_COUNT               NUMBER DEFAULT 0,
  EXECUTION_PLAN_COUNT         NUMBER DEFAULT 0,
  VERIFICATION_PENDING_COUNT   NUMBER DEFAULT 0,
  VERIFIED_COUNT               NUMBER DEFAULT 0,
  CLOSED_COUNT                 NUMBER DEFAULT 0,
  HIGH_RISK_COUNT              NUMBER DEFAULT 0,
  OWNER_GAP_COUNT              NUMBER DEFAULT 0,
  EVIDENCE_COUNT               NUMBER DEFAULT 0,
  EXPECTED_SAVINGS_USD         NUMBER(18,2) DEFAULT 0,
  ACTUAL_VERIFIED_SAVINGS_USD  NUMBER(18,2) DEFAULT 0,
  UNVERIFIED_EXPECTED_USD      NUMBER(18,2) DEFAULT 0,
  TOP_FINDING                  VARCHAR(4000),
  NEXT_ACTION                  VARCHAR(1000),
  CONFIDENCE                   VARCHAR(40),
  LAST_REFRESHED_TS            TIMESTAMP_NTZ,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- -----------------------------------------------------------------------------
-- Phase 2F: Command Center
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS OVERWATCH_COMMAND_CENTER_QUESTION (
  QUESTION_KEY                 VARCHAR(100) PRIMARY KEY,
  INVESTIGATION_TYPE           VARCHAR(100),
  QUESTION_TEXT                VARCHAR(500),
  DISPLAY_ORDER                NUMBER,
  SOURCE_OBJECTS               VARCHAR(1000),
  DEFAULT_OWNER_ROUTE          VARCHAR(200),
  DEFAULT_RISK_LEVEL           VARCHAR(40),
  DEFAULT_CONFIDENCE           VARCHAR(40),
  DEFAULT_ACTION               VARCHAR(2000),
  ENABLED                      BOOLEAN DEFAULT TRUE,
  CREATED_AT                   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  UPDATED_AT                   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

MERGE INTO OVERWATCH_COMMAND_CENTER_QUESTION tgt
USING (
  SELECT * FROM VALUES
    ('COST_SPIKE', 'Cost Spike', 'Why did costs spike?', 10, 'MART_EXECUTIVE_OBSERVABILITY; MART_EXECUTIVE_FORECAST_SUMMARY; MART_EXECUTIVE_VALUE_LEDGER; OVERWATCH_ACTION_WORKFLOW', 'DBA / Cost owner', 'High', 'allocated', 'Open Cost & Contract, confirm the spend driver, route an owner-backed savings action, and verify value after the change.', TRUE),
    ('WAREHOUSE_SLOW', 'Warehouse Slow', 'Why is this warehouse slow?', 20, 'MART_EXECUTIVE_OBSERVABILITY; MART_EXECUTIVE_FORECAST_SUMMARY; OVERWATCH_ACTION_WORKFLOW', 'DBA / Workload owner', 'High', 'allocated', 'Open Workload Operations, review queue/spill/pressure evidence, and create a review-gated action plan.', TRUE),
    ('RECENT_CHANGE', 'Recent Change', 'What changed recently?', 30, 'MART_CHANGE_INTELLIGENCE_SUMMARY; OVERWATCH_CHANGE_CORRELATION', 'DBA / Platform', 'Medium', 'estimated', 'Review recent high-risk changes and treat timing/entity matches as possible correlation until proven.', TRUE),
    ('FAILURE_SLA', 'Failure / SLA', 'Why did this fail?', 40, 'ALERT_EVENTS; MART_EXECUTIVE_OBSERVABILITY; OVERWATCH_ACTION_WORKFLOW', 'DBA On-Call', 'High', 'allocated', 'Open Alert Center and Workload Operations, assign the owner, capture evidence, and verify recovery.', TRUE),
    ('SECURITY_RISK', 'Security Risk', 'What security risk needs action?', 50, 'ALERT_EVENTS; MART_OPERATIONAL_OWNER_COVERAGE; MART_EXECUTIVE_SCORECARD_SUMMARY; MART_CHANGE_INTELLIGENCE_SUMMARY', 'Security / DBA', 'High', 'allocated', 'Open Security Monitoring, validate ownership gaps, and route approval-gated access actions.', TRUE),
    ('EXECUTIVE_RISK', 'Executive Risk', 'What should leadership worry about?', 60, 'MART_EXECUTIVE_SCORECARD_SUMMARY; MART_PRODUCTION_READINESS_SUMMARY; MART_DATA_TRUST_SUMMARY; MART_CLOSED_LOOP_OPERATIONS_SUMMARY', 'DBA / Platform', 'Medium', 'estimated', 'Use the scorecard, readiness, trust, and action lifecycle evidence to decide the next operating move.', TRUE)
  AS t(QUESTION_KEY, INVESTIGATION_TYPE, QUESTION_TEXT, DISPLAY_ORDER, SOURCE_OBJECTS, DEFAULT_OWNER_ROUTE, DEFAULT_RISK_LEVEL, DEFAULT_CONFIDENCE, DEFAULT_ACTION, ENABLED)
) src
ON tgt.QUESTION_KEY = src.QUESTION_KEY
WHEN MATCHED THEN UPDATE SET
  INVESTIGATION_TYPE = src.INVESTIGATION_TYPE,
  QUESTION_TEXT = src.QUESTION_TEXT,
  DISPLAY_ORDER = src.DISPLAY_ORDER,
  SOURCE_OBJECTS = src.SOURCE_OBJECTS,
  DEFAULT_OWNER_ROUTE = src.DEFAULT_OWNER_ROUTE,
  DEFAULT_RISK_LEVEL = src.DEFAULT_RISK_LEVEL,
  DEFAULT_CONFIDENCE = src.DEFAULT_CONFIDENCE,
  DEFAULT_ACTION = src.DEFAULT_ACTION,
  ENABLED = src.ENABLED,
  UPDATED_AT = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
  QUESTION_KEY, INVESTIGATION_TYPE, QUESTION_TEXT, DISPLAY_ORDER, SOURCE_OBJECTS,
  DEFAULT_OWNER_ROUTE, DEFAULT_RISK_LEVEL, DEFAULT_CONFIDENCE, DEFAULT_ACTION, ENABLED
)
VALUES (
  src.QUESTION_KEY, src.INVESTIGATION_TYPE, src.QUESTION_TEXT, src.DISPLAY_ORDER,
  src.SOURCE_OBJECTS, src.DEFAULT_OWNER_ROUTE, src.DEFAULT_RISK_LEVEL,
  src.DEFAULT_CONFIDENCE, src.DEFAULT_ACTION, src.ENABLED
);

CREATE TRANSIENT TABLE IF NOT EXISTS OVERWATCH_COMMAND_CENTER_FINDING (
  SNAPSHOT_TS                         TIMESTAMP_NTZ,
  COMPANY                             VARCHAR(100),
  ENVIRONMENT                         VARCHAR(100),
  FINDING_ID                          VARCHAR(200),
  QUESTION_KEY                        VARCHAR(100),
  INVESTIGATION_TYPE                  VARCHAR(100),
  QUESTION_TEXT                       VARCHAR(500),
  ROOT_CAUSE_CANDIDATE                VARCHAR(4000),
  EVIDENCE_SUMMARY                    VARCHAR(8000),
  CONFIDENCE                          VARCHAR(40),
  BUSINESS_IMPACT                     VARCHAR(4000),
  TECHNICAL_IMPACT                    VARCHAR(4000),
  OWNER_ROUTE                         VARCHAR(200),
  OWNER_GAP                           BOOLEAN DEFAULT FALSE,
  RELATED_CHANGES                     VARCHAR(4000),
  RELATED_ALERTS                      VARCHAR(4000),
  RELATED_SCORECARD_DRIVERS           VARCHAR(4000),
  RELATED_FORECASTS                   VARCHAR(4000),
  RECOMMENDED_ACTION                  VARCHAR(4000),
  RISK_LEVEL                          VARCHAR(40),
  EXECUTION_PLAN_REF                  VARCHAR(200),
  EXPECTED_SAVINGS_OR_RISK_AVOIDED_USD NUMBER(18,2) DEFAULT 0,
  VERIFICATION_PATH                   VARCHAR(4000),
  CAUSALITY_LABEL                     VARCHAR(100),
  LAST_REFRESHED_TS                   TIMESTAMP_NTZ,
  LOAD_TS                             TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS OVERWATCH_COMMAND_CENTER_EVIDENCE (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  FINDING_ID                   VARCHAR(200),
  EVIDENCE_ID                  VARCHAR(200),
  EVIDENCE_TYPE                VARCHAR(100),
  SOURCE_OBJECT                VARCHAR(500),
  RELATED_OBJECT               VARCHAR(500),
  EVIDENCE_SUMMARY             VARCHAR(8000),
  CONFIDENCE                   VARCHAR(40),
  CAUSALITY_LABEL              VARCHAR(100),
  LAST_REFRESHED_TS            TIMESTAMP_NTZ,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS OVERWATCH_COMMAND_CENTER_RECOMMENDATION (
  SNAPSHOT_TS                         TIMESTAMP_NTZ,
  COMPANY                             VARCHAR(100),
  ENVIRONMENT                         VARCHAR(100),
  FINDING_ID                          VARCHAR(200),
  RECOMMENDATION_ID                   VARCHAR(200),
  RECOMMENDED_ACTION                  VARCHAR(4000),
  RISK_LEVEL                          VARCHAR(40),
  OWNER_ROUTE                         VARCHAR(200),
  EXECUTION_PLAN_REF                  VARCHAR(200),
  REVIEW_REQUIRED                     BOOLEAN DEFAULT TRUE,
  EXPECTED_SAVINGS_OR_RISK_AVOIDED_USD NUMBER(18,2) DEFAULT 0,
  VERIFICATION_PATH                   VARCHAR(4000),
  SAFETY_NOTE                         VARCHAR(2000),
  LAST_REFRESHED_TS                   TIMESTAMP_NTZ,
  LOAD_TS                             TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS MART_COMMAND_CENTER_SUMMARY (
  SNAPSHOT_TS                         TIMESTAMP_NTZ,
  COMPANY                             VARCHAR(100),
  ENVIRONMENT                         VARCHAR(100),
  INVESTIGATION_TYPE                  VARCHAR(100),
  QUESTION_TEXT                       VARCHAR(500),
  FINDING_COUNT                       NUMBER DEFAULT 0,
  HIGH_RISK_COUNT                     NUMBER DEFAULT 0,
  OWNER_GAP_COUNT                     NUMBER DEFAULT 0,
  RELATED_CHANGE_COUNT                NUMBER DEFAULT 0,
  RELATED_ALERT_COUNT                 NUMBER DEFAULT 0,
  RELATED_SCORECARD_COUNT             NUMBER DEFAULT 0,
  RELATED_FORECAST_COUNT              NUMBER DEFAULT 0,
  REVIEW_PLAN_COUNT                   NUMBER DEFAULT 0,
  EXPECTED_VALUE_USD                  NUMBER(18,2) DEFAULT 0,
  TOP_ROOT_CAUSE_CANDIDATE            VARCHAR(4000),
  TOP_EVIDENCE_SUMMARY                VARCHAR(8000),
  TOP_RECOMMENDED_ACTION              VARCHAR(4000),
  CONFIDENCE                          VARCHAR(40),
  RISK_LEVEL                          VARCHAR(40),
  LAST_REFRESHED_TS                   TIMESTAMP_NTZ,
  LOAD_TS                             TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- Existing installs may have been created before environment dimensions and
-- detailed query telemetry were added. CREATE TABLE IF NOT EXISTS will not
-- evolve those tables, so keep this upgrade block idempotent.
ALTER TABLE IF EXISTS FACT_QUERY_HOURLY ADD COLUMN IF NOT EXISTS WAREHOUSE_SIZE VARCHAR(100);
ALTER TABLE IF EXISTS FACT_QUERY_HOURLY ADD COLUMN IF NOT EXISTS ENVIRONMENT VARCHAR(100);

ALTER TABLE IF EXISTS FACT_QUERY_DETAIL_RECENT ADD COLUMN IF NOT EXISTS ENVIRONMENT VARCHAR(100);
ALTER TABLE IF EXISTS FACT_QUERY_DETAIL_RECENT ADD COLUMN IF NOT EXISTS WAREHOUSE_SIZE VARCHAR(100);
ALTER TABLE IF EXISTS FACT_QUERY_DETAIL_RECENT ADD COLUMN IF NOT EXISTS COMPILATION_TIME NUMBER;
ALTER TABLE IF EXISTS FACT_QUERY_DETAIL_RECENT ADD COLUMN IF NOT EXISTS EXECUTION_TIME NUMBER;
ALTER TABLE IF EXISTS FACT_QUERY_DETAIL_RECENT ADD COLUMN IF NOT EXISTS TRANSACTION_BLOCKED_TIME NUMBER;
ALTER TABLE IF EXISTS FACT_QUERY_DETAIL_RECENT ADD COLUMN IF NOT EXISTS BYTES_SPILLED_TO_LOCAL_STORAGE NUMBER;
ALTER TABLE IF EXISTS FACT_QUERY_DETAIL_RECENT ADD COLUMN IF NOT EXISTS PARTITIONS_SCANNED NUMBER;
ALTER TABLE IF EXISTS FACT_QUERY_DETAIL_RECENT ADD COLUMN IF NOT EXISTS PARTITIONS_TOTAL NUMBER;
ALTER TABLE IF EXISTS FACT_QUERY_DETAIL_RECENT ADD COLUMN IF NOT EXISTS ROWS_PRODUCED NUMBER;
ALTER TABLE IF EXISTS FACT_QUERY_DETAIL_RECENT ADD COLUMN IF NOT EXISTS QUERY_HASH VARCHAR(300);

ALTER TABLE IF EXISTS FACT_TASK_RUN ADD COLUMN IF NOT EXISTS ENVIRONMENT VARCHAR(100);
ALTER TABLE IF EXISTS DIM_TASK_SNAPSHOT ADD COLUMN IF NOT EXISTS ENVIRONMENT VARCHAR(100);
ALTER TABLE IF EXISTS DIM_PROCEDURE_SNAPSHOT ADD COLUMN IF NOT EXISTS ENVIRONMENT VARCHAR(100);
ALTER TABLE IF EXISTS FACT_PROCEDURE_RUN ADD COLUMN IF NOT EXISTS DATABASE_NAME VARCHAR(300);
ALTER TABLE IF EXISTS FACT_PROCEDURE_RUN ADD COLUMN IF NOT EXISTS ENVIRONMENT VARCHAR(100);
ALTER TABLE IF EXISTS FACT_PROCEDURE_RUN ADD COLUMN IF NOT EXISTS SCHEMA_NAME VARCHAR(300);
ALTER TABLE IF EXISTS FACT_OBJECT_CHANGE ADD COLUMN IF NOT EXISTS ENVIRONMENT VARCHAR(100);
ALTER TABLE IF EXISTS FACT_OBJECT_CHANGE ADD COLUMN IF NOT EXISTS QUERY_TAG VARCHAR;
ALTER TABLE IF EXISTS FACT_STORAGE_DAILY ADD COLUMN IF NOT EXISTS ENVIRONMENT VARCHAR(100);
ALTER TABLE IF EXISTS FACT_STORAGE_DAILY ADD COLUMN IF NOT EXISTS STAGE_BYTES NUMBER;
ALTER TABLE IF EXISTS FACT_STORAGE_DAILY ADD COLUMN IF NOT EXISTS HYBRID_TABLE_STORAGE_BYTES NUMBER;
ALTER TABLE IF EXISTS FACT_STORAGE_DAILY ADD COLUMN IF NOT EXISTS ARCHIVE_STORAGE_COOL_BYTES NUMBER;
ALTER TABLE IF EXISTS FACT_STORAGE_DAILY ADD COLUMN IF NOT EXISTS ARCHIVE_STORAGE_COLD_BYTES NUMBER;
ALTER TABLE IF EXISTS FACT_STORAGE_DAILY ADD COLUMN IF NOT EXISTS STANDARD_STORAGE_COST_USD NUMBER(18,2);
ALTER TABLE IF EXISTS FACT_STORAGE_DAILY ADD COLUMN IF NOT EXISTS HYBRID_STORAGE_COST_USD NUMBER(18,2);
ALTER TABLE IF EXISTS FACT_STORAGE_DAILY ADD COLUMN IF NOT EXISTS ARCHIVE_COOL_COST_USD NUMBER(18,2);
ALTER TABLE IF EXISTS FACT_STORAGE_DAILY ADD COLUMN IF NOT EXISTS ARCHIVE_COLD_COST_USD NUMBER(18,2);
ALTER TABLE IF EXISTS DIM_TABLE_SNAPSHOT ADD COLUMN IF NOT EXISTS ENVIRONMENT VARCHAR(100);
ALTER TABLE IF EXISTS FACT_COPY_LOAD_DAILY ADD COLUMN IF NOT EXISTS ENVIRONMENT VARCHAR(100);
ALTER TABLE IF EXISTS FACT_CHARGEBACK_DAILY ADD COLUMN IF NOT EXISTS ENVIRONMENT VARCHAR(100);
ALTER TABLE IF EXISTS FACT_CHARGEBACK_DAILY ADD COLUMN IF NOT EXISTS ENVIRONMENT_ROLLUP VARCHAR(100);
ALTER TABLE IF EXISTS MART_EXECUTIVE_OBSERVABILITY ADD COLUMN IF NOT EXISTS SOURCE VARCHAR(500);

