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


CREATE TRANSIENT TABLE IF NOT EXISTS MART_USER_DIM_CURRENT (
  USER_ID                      VARCHAR(300),
  USER_NAME                    VARCHAR(300),
  LOGIN_NAME                   VARCHAR(300),
  DISPLAY_NAME                 VARCHAR(500),
  FIRST_NAME                   VARCHAR(300),
  LAST_NAME                    VARCHAR(300),
  USER_DISPLAY_NAME            VARCHAR(500),
  USER_CHART_LABEL             VARCHAR(500),
  USER_ADMIN_LABEL             VARCHAR(800),
  EMAIL                        VARCHAR(500),
  USER_TYPE                    VARCHAR(120),
  DELETED_ON                   TIMESTAMP_LTZ,
  DISABLED                     BOOLEAN,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_CORTEX_DAILY (
  USAGE_DATE                   DATE,
  COMPANY                      VARCHAR(100),
  USER_ID                      VARCHAR(300),
  USER_NAME                    VARCHAR(300),
  USER_DISPLAY_NAME            VARCHAR(500),
  USER_CHART_LABEL             VARCHAR(500),
  USER_EMAIL                   VARCHAR(500),
  SOURCE                       VARCHAR(100),
  CREDITS_USED                 NUMBER(18,6),
  EST_COST_USD                 NUMBER(18,2),
  REQUEST_COUNT                NUMBER,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

ALTER TABLE IF EXISTS FACT_CORTEX_DAILY ADD COLUMN IF NOT EXISTS USER_NAME VARCHAR(300);
ALTER TABLE IF EXISTS FACT_CORTEX_DAILY ADD COLUMN IF NOT EXISTS USER_DISPLAY_NAME VARCHAR(500);
ALTER TABLE IF EXISTS FACT_CORTEX_DAILY ADD COLUMN IF NOT EXISTS USER_CHART_LABEL VARCHAR(500);
ALTER TABLE IF EXISTS FACT_CORTEX_DAILY ADD COLUMN IF NOT EXISTS USER_EMAIL VARCHAR(500);

CREATE TRANSIENT TABLE IF NOT EXISTS FACT_COST_DAILY (
  USAGE_DATE                         DATE,
  COMPANY                            VARCHAR(100),
  SERVICE_CATEGORY                   VARCHAR(120),
  SERVICE_TYPE                       VARCHAR(200),
  CREDITS_USED                       NUMBER(18,6),
  CREDITS_USED_COMPUTE               NUMBER(18,6),
  CREDITS_USED_CLOUD_SERVICES        NUMBER(18,6),
  CREDITS_ADJUSTMENT_CLOUD_SERVICES  NUMBER(18,6),
  CREDITS_BILLED                     NUMBER(18,6),
  RATE_USD                           NUMBER(18,4),
  EST_COST_USD                       NUMBER(18,2),
  SOURCE_VIEW                        VARCHAR(300),
  LOAD_TS                            TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

ALTER TABLE IF EXISTS FACT_COST_DAILY ADD COLUMN IF NOT EXISTS CREDITS_USED NUMBER(18,6);
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

CREATE TRANSIENT TABLE IF NOT EXISTS MART_SECTION_COMMAND_BRIEF (
  BRIEF_ID                     VARCHAR(64),
  SECTION_NAME                 VARCHAR(200),
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  WINDOW_DAYS                  NUMBER,
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  STATE                        VARCHAR(100),
  HEADLINE                     VARCHAR(1000),
  SUMMARY                      VARCHAR(4000),
  TOP_SIGNAL                   VARCHAR(1000),
  TOP_ENTITY                   VARCHAR(500),
  TOP_ACTION                   VARCHAR(2000),
  SOURCE_STATUS                VARCHAR(200),
  SOURCE_FRESHNESS             VARCHAR(500),
  SOURCE_OBJECTS               VARCHAR(2000),
  SOURCE_SNAPSHOT_TS           TIMESTAMP_NTZ,
  FRESHNESS_MINUTES            NUMBER,
  TARGET_FRESHNESS_MINUTES     NUMBER,
  IS_STALE                     BOOLEAN,
  RESOLVED_COMPANY             VARCHAR(100),
  RESOLVED_ENVIRONMENT         VARCHAR(100),
  RESOLVED_WINDOW_DAYS         NUMBER,
  CONFIDENCE                   VARCHAR(40),
  REQUIRED_SOURCE_COUNT        NUMBER,
  AVAILABLE_SOURCE_COUNT       NUMBER,
  MISSING_SOURCE_COUNT         NUMBER,
  AVAILABLE_REQUIRED_SOURCE_COUNT NUMBER,
  REQUIRED_MISSING_SOURCE_COUNT NUMBER,
  REQUIRED_STALE_SOURCE_COUNT  NUMBER,
  OPTIONAL_SOURCE_COUNT        NUMBER,
  AVAILABLE_OPTIONAL_SOURCE_COUNT NUMBER,
  OPTIONAL_MISSING_SOURCE_COUNT NUMBER,
  OPTIONAL_STALE_SOURCE_COUNT  NUMBER,
  SOURCE_COVERAGE_PCT          NUMBER(8,2),
  DATA_AVAILABILITY_STATE      VARCHAR(80),
  STALE_SOURCE_COUNT           NUMBER,
  SOURCE_GAP_DETAIL            VARCHAR(4000),
  ACCOUNT_BILLED_CREDITS       NUMBER(38,6),
  ACCOUNT_BILLED_COST_USD      NUMBER(38,6),
  ACCOUNT_USED_CREDITS         NUMBER(38,6),
  COMPUTE_CREDITS              NUMBER(38,6),
  CLOUD_SERVICES_CREDITS       NUMBER(38,6),
  CLOUD_SERVICES_ADJUSTMENT    NUMBER(38,6),
  ACCOUNT_CLOUD_SERVICES_ADJUSTMENT NUMBER(38,6),
  WAREHOUSE_CREDITS            NUMBER(38,6),
  WAREHOUSE_COST_ESTIMATE_USD  NUMBER(38,6),
  WAREHOUSE_COST_USD           NUMBER(38,6),
  SERVICE_OTHER_CREDITS        NUMBER(38,6),
  SERVICE_OTHER_COST_USD       NUMBER(38,6),
  BILLING_BRIDGE_DELTA_CREDITS NUMBER(38,6),
  BILLING_BRIDGE_DELTA_USD     NUMBER(38,6),
  BILLING_BRIDGE_STATUS        VARCHAR(80),
  CORTEX_AI_CREDITS            NUMBER(38,6),
  CORTEX_AI_COST_USD           NUMBER(38,6),
  BILLING_RECONCILIATION_STATUS VARCHAR(80),
  BILLING_WINDOW_START         DATE,
  BILLING_WINDOW_END           DATE,
  BILLING_WINDOW_COMPLETE      BOOLEAN,
  BILLING_SOURCE_FRESHNESS_TS  TIMESTAMP_NTZ,
  BILLING_LATENCY_NOTE         VARCHAR(1000),
  BILLING_RECONCILIATION_WINDOW_START DATE,
  BILLING_RECONCILIATION_WINDOW_END DATE,
  BILLING_RECONCILIATION_FRESHNESS VARCHAR(200),
  SPEND_MOVEMENT_PCT           NUMBER(18,4),
  FORECAST_RUN_RATE_USD        NUMBER(38,6),
  SECURITY_CREDENTIAL_EXPIRATION_RISK_COUNT NUMBER,
  SECURITY_CREDENTIALS_EXPIRING_30D_COUNT NUMBER,
  SECURITY_CREDENTIALS_EXPIRING_7D_COUNT NUMBER,
  SECURITY_CREDENTIALS_EXPIRED_COUNT NUMBER,
  SECURITY_CREDENTIAL_NEXT_EXPIRATION_TS TIMESTAMP_NTZ,
  SECURITY_CREDENTIAL_NEXT_EXPIRATION_USER VARCHAR(500),
  SECURITY_CREDENTIAL_NEXT_EXPIRATION_TYPE VARCHAR(120),
  SECURITY_CREDENTIAL_EXPIRATION_STATUS VARCHAR(80),
  SECURITY_CREDENTIAL_EXPIRATION_FINDINGS VARIANT,
  SECURITY_CREDENTIAL_SOURCE_CONFIRMED_ZERO BOOLEAN,
  SECURITY_CREDENTIAL_SOURCE_STATUS VARCHAR(80),
  SECURITY_CREDENTIAL_SOURCE_FRESHNESS_TS TIMESTAMP_NTZ,
  SECURITY_CREDENTIAL_SOURCE_LATENCY_NOTE VARCHAR(1000),
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS MART_SECTION_COMMAND_METRIC (
  BRIEF_ID                     VARCHAR(64),
  SECTION_NAME                 VARCHAR(200),
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  WINDOW_DAYS                  NUMBER,
  METRIC_KEY                   VARCHAR(200),
  METRIC_LABEL                 VARCHAR(300),
  METRIC_VALUE                 VARCHAR(500),
  METRIC_NUMERIC_VALUE         NUMBER(38,6),
  METRIC_TEXT_VALUE            VARCHAR(500),
  METRIC_FORMAT                VARCHAR(80),
  METRIC_UNIT                  VARCHAR(100),
  METRIC_DETAIL                VARCHAR(1000),
  METRIC_TONE                  VARCHAR(80),
  TREND_NUMERIC_VALUE          NUMBER(38,6),
  TREND_LABEL                  VARCHAR(500),
  TREND_POINTS                 VARIANT,
  TREND_PERIOD                 VARCHAR(80),
  TREND_POINT_COUNT            NUMBER,
  TREND_QUALITY                VARCHAR(80),
  ZERO_FILL_POLICY             VARCHAR(80),
  PRIOR_VALUE                  NUMBER(38,6),
  DELTA_NUMERIC_VALUE          NUMBER(38,6),
  DELTA_PERCENT                NUMBER(18,4),
  TREND_DIRECTION              VARCHAR(40),
  IS_AVAILABLE                 BOOLEAN,
  AVAILABILITY_STATE           VARCHAR(80),
  UNAVAILABLE_REASON           VARCHAR(1000),
  SOURCE_KEY                   VARCHAR(200),
  CONFIDENCE                   VARCHAR(40),
  SORT_ORDER                   NUMBER,
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS MART_SECTION_COMMAND_EXCEPTION (
  BRIEF_ID                     VARCHAR(64),
  SECTION_NAME                 VARCHAR(200),
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  WINDOW_DAYS                  NUMBER,
  FINDING_KEY                  VARCHAR(200),
  DEDUPE_KEY                   VARCHAR(500),
  SEVERITY                     VARCHAR(80),
  SIGNAL                       VARCHAR(1000),
  ENTITY_TYPE                  VARCHAR(200),
  ENTITY_ID                    VARCHAR(500),
  ENTITY_NAME                  VARCHAR(500),
  EVIDENCE_ID                  VARCHAR(500),
  EVIDENCE_QUERY               VARCHAR(16000),
  DETAIL                       VARCHAR(4000),
  ROUTE_SECTION                VARCHAR(200),
  ROUTE_WORKFLOW               VARCHAR(200),
  PRIORITY_SCORE               NUMBER,
  IMPACT_VALUE                 NUMBER(18,2),
  IMPACT_UNIT                  VARCHAR(80),
  OWNER_ROUTE                  VARCHAR(200),
  OWNER_GAP                    BOOLEAN,
  FIRST_SEEN_TS                TIMESTAMP_NTZ,
  DUE_TS                       TIMESTAMP_NTZ,
  OWNER_ID                     VARCHAR(300),
  OWNER_NAME                   VARCHAR(300),
  AGE_MINUTES                  NUMBER,
  SLA_STATE                    VARCHAR(80),
  SORT_ORDER                   NUMBER,
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS MART_SECTION_COMMAND_ACTION (
  BRIEF_ID                     VARCHAR(64),
  SECTION_NAME                 VARCHAR(200),
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  WINDOW_DAYS                  NUMBER,
  ACTION_KEY                   VARCHAR(200),
  ROUTE_KEY                    VARCHAR(200),
  ACTION_LABEL                 VARCHAR(300),
  ACTION_DETAIL                VARCHAR(1200),
  CTA_LABEL                    VARCHAR(300),
  TARGET_SECTION               VARCHAR(200),
  TARGET_WORKFLOW              VARCHAR(200),
  SESSION_STATE_UPDATES_JSON   VARCHAR(4000),
  SORT_ORDER                   NUMBER,
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS OVERWATCH_SECTION_COMMAND_SOURCE_CONFIG (
  SECTION_NAME                 VARCHAR(200),
  SOURCE_KEY                   VARCHAR(200),
  SOURCE_OBJECT                VARCHAR(500),
  REQUIRED                     BOOLEAN DEFAULT TRUE,
  TARGET_FRESHNESS_MINUTES     NUMBER,
  DEFAULT_CONFIDENCE           VARCHAR(40),
  ENVIRONMENT_MODE             VARCHAR(40) DEFAULT 'not_applicable',
  SUPPORTS_ENVIRONMENT         BOOLEAN DEFAULT FALSE,
  ENABLED                      BOOLEAN DEFAULT TRUE,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

--ALTER TABLE IF EXISTS OVERWATCH_SECTION_COMMAND_SOURCE_CONFIG ADD COLUMN IF NOT EXISTS ENVIRONMENT_MODE VARCHAR(40) DEFAULT 'not_applicable';
--ALTER TABLE IF EXISTS OVERWATCH_SECTION_COMMAND_SOURCE_CONFIG ADD COLUMN IF NOT EXISTS SUPPORTS_ENVIRONMENT BOOLEAN DEFAULT FALSE;

INSERT INTO OVERWATCH_SECTION_COMMAND_SOURCE_CONFIG (
  SECTION_NAME,
  SOURCE_KEY,
  SOURCE_OBJECT,
  REQUIRED,
  TARGET_FRESHNESS_MINUTES,
  DEFAULT_CONFIDENCE,
  ENVIRONMENT_MODE,
  SUPPORTS_ENVIRONMENT,
  ENABLED
)
SELECT
  SECTION_NAME,
  SOURCE_KEY,
  SOURCE_OBJECT,
  REQUIRED,
  TARGET_FRESHNESS_MINUTES,
  DEFAULT_CONFIDENCE,
  CASE
    WHEN SOURCE_KEY IN (
      'alert_events', 'security_alerts', 'query_hourly', 'query_recent', 'task_runs',
      'procedure_runs', 'copy_load', 'security_operability', 'change_summary'
    ) THEN 'exact'
    WHEN SOURCE_KEY IN (
      'cost_daily', 'cortex_daily', 'cost_signals', 'forecast', 'value_ledger',
      'settings', 'action_queue', 'executive_observability', 'executive_scorecard',
      'executive_forecast', 'closed_loop', 'production_readiness', 'data_trust',
      'app_observability', 'dba_control_room', 'notification_log',
      'acknowledgements', 'owner_coverage', 'login_daily', 'grant_daily',
      'credential_expiration'
    ) THEN 'all_fallback'
    ELSE 'not_applicable'
  END AS ENVIRONMENT_MODE,
  SOURCE_KEY IN (
    'alert_events', 'security_alerts', 'query_hourly', 'query_recent', 'task_runs',
    'procedure_runs', 'copy_load', 'security_operability', 'change_summary'
  ) AS SUPPORTS_ENVIRONMENT,
  ENABLED
FROM VALUES
    ('Executive Landing','executive_observability','MART_EXECUTIVE_OBSERVABILITY',TRUE,60,'allocated',TRUE),
    ('Executive Landing','executive_scorecard','MART_EXECUTIVE_SCORECARD_SUMMARY',TRUE,60,'allocated',TRUE),
    ('Executive Landing','executive_forecast','MART_EXECUTIVE_FORECAST_SUMMARY',TRUE,60,'estimated',TRUE),
    ('Executive Landing','closed_loop','MART_CLOSED_LOOP_OPERATIONS_SUMMARY',TRUE,60,'allocated',TRUE),
    ('Executive Landing','production_readiness','MART_PRODUCTION_READINESS_SUMMARY',TRUE,60,'allocated',TRUE),
    ('Executive Landing','data_trust','MART_DATA_TRUST_SUMMARY',FALSE,60,'allocated',TRUE),
    ('Executive Landing','app_observability','MART_APP_OBSERVABILITY_SUMMARY',FALSE,60,'allocated',TRUE),
    ('Executive Landing','value_ledger','MART_EXECUTIVE_VALUE_LEDGER',FALSE,60,'allocated',TRUE),
    ('Executive Landing','cost_daily','FACT_COST_DAILY',TRUE,60,'allocated',TRUE),
    ('Executive Landing','cortex_daily','FACT_CORTEX_DAILY',FALSE,60,'estimated',TRUE),
    ('Executive Landing','alert_events','ALERT_EVENTS',TRUE,15,'exact',TRUE),
    ('Executive Landing','action_queue','OVERWATCH_ACTION_QUEUE',TRUE,60,'allocated',TRUE),
    ('Executive Landing','query_hourly','FACT_QUERY_HOURLY',FALSE,30,'allocated',TRUE),
    ('Executive Landing','task_runs','FACT_TASK_RUN',FALSE,30,'allocated',TRUE),
    ('Executive Landing','security_operability','FACT_SECURITY_OPERABILITY_DAILY',FALSE,60,'allocated',TRUE),
    ('DBA Control Room','dba_control_room','MART_DBA_CONTROL_ROOM',TRUE,30,'allocated',TRUE),
    ('DBA Control Room','query_hourly','FACT_QUERY_HOURLY',TRUE,30,'allocated',TRUE),
    ('DBA Control Room','task_runs','FACT_TASK_RUN',TRUE,30,'allocated',TRUE),
    ('DBA Control Room','action_queue','OVERWATCH_ACTION_QUEUE',TRUE,30,'allocated',TRUE),
    ('DBA Control Room','change_summary','MART_CHANGE_INTELLIGENCE_SUMMARY',FALSE,30,'allocated',TRUE),
    ('DBA Control Room','security_operability','FACT_SECURITY_OPERABILITY_DAILY',FALSE,30,'allocated',TRUE),
    ('DBA Control Room','cost_daily','FACT_COST_DAILY',FALSE,30,'allocated',TRUE),
    ('Alert Center','alert_events','ALERT_EVENTS',TRUE,15,'exact',TRUE),
    ('Alert Center','action_queue','OVERWATCH_ACTION_QUEUE',TRUE,15,'allocated',TRUE),
    ('Alert Center','notification_log','ALERT_NOTIFICATION_LOG',TRUE,15,'exact',TRUE),
    ('Alert Center','acknowledgements','ALERT_ACKNOWLEDGEMENTS',FALSE,15,'exact',TRUE),
    ('Cost & Contract','cost_daily','FACT_COST_DAILY',TRUE,60,'allocated',TRUE),
    ('Cost & Contract','cortex_daily','FACT_CORTEX_DAILY',TRUE,60,'estimated',TRUE),
    ('Cost & Contract','cost_signals','FACT_COST_MONITORING_SIGNAL',TRUE,60,'allocated',TRUE),
    ('Cost & Contract','forecast','MART_EXECUTIVE_FORECAST_SUMMARY',FALSE,60,'estimated',TRUE),
    ('Cost & Contract','value_ledger','MART_EXECUTIVE_VALUE_LEDGER',FALSE,60,'allocated',TRUE),
    ('Cost & Contract','action_queue','OVERWATCH_ACTION_QUEUE',FALSE,60,'allocated',TRUE),
    ('Cost & Contract','settings','OVERWATCH_SETTINGS',TRUE,60,'exact',TRUE),
    ('Workload Operations','query_hourly','FACT_QUERY_HOURLY',TRUE,30,'allocated',TRUE),
    ('Workload Operations','query_recent','FACT_QUERY_DETAIL_RECENT',FALSE,30,'allocated',TRUE),
    ('Workload Operations','task_runs','FACT_TASK_RUN',TRUE,30,'allocated',TRUE),
    ('Workload Operations','procedure_runs','FACT_PROCEDURE_RUN',TRUE,30,'allocated',TRUE),
    ('Workload Operations','copy_load','FACT_COPY_LOAD_DAILY',TRUE,30,'allocated',TRUE),
    ('Workload Operations','change_summary','MART_CHANGE_INTELLIGENCE_SUMMARY',FALSE,30,'allocated',TRUE),
    ('Security Monitoring','security_operability','FACT_SECURITY_OPERABILITY_DAILY',TRUE,60,'allocated',TRUE),
    ('Security Monitoring','login_daily','FACT_LOGIN_DAILY',TRUE,60,'allocated',TRUE),
    ('Security Monitoring','grant_daily','FACT_GRANT_DAILY',TRUE,60,'allocated',TRUE),
    ('Security Monitoring','credential_expiration','MART_SECURITY_CREDENTIAL_EXPIRATIONS_CURRENT',TRUE,60,'allocated',TRUE),
    ('Security Monitoring','security_alerts','ALERT_EVENTS',TRUE,60,'allocated',TRUE),
    ('Security Monitoring','owner_coverage','MART_OPERATIONAL_OWNER_COVERAGE',TRUE,60,'allocated',TRUE),
    ('Security Monitoring','change_summary','MART_CHANGE_INTELLIGENCE_SUMMARY',FALSE,60,'allocated',TRUE)
  AS v(SECTION_NAME, SOURCE_KEY, SOURCE_OBJECT, REQUIRED, TARGET_FRESHNESS_MINUTES, DEFAULT_CONFIDENCE, ENABLED)
WHERE NOT EXISTS (
  SELECT 1
  FROM OVERWATCH_SECTION_COMMAND_SOURCE_CONFIG cfg
  WHERE cfg.SECTION_NAME = v.SECTION_NAME
    AND cfg.SOURCE_KEY = v.SOURCE_KEY
);

MERGE INTO OVERWATCH_SECTION_COMMAND_SOURCE_CONFIG cfg
USING (
  SELECT
    SECTION_NAME,
    SOURCE_KEY,
    CASE
      WHEN SOURCE_KEY IN (
        'alert_events', 'security_alerts', 'query_hourly', 'query_recent', 'task_runs',
        'procedure_runs', 'copy_load', 'security_operability', 'change_summary'
      ) THEN 'exact'
      WHEN SOURCE_KEY IN (
        'cost_daily', 'cortex_daily', 'cost_signals', 'forecast', 'value_ledger',
        'settings', 'action_queue', 'executive_observability', 'executive_scorecard',
        'executive_forecast', 'closed_loop', 'production_readiness', 'data_trust',
        'app_observability', 'dba_control_room', 'notification_log',
        'acknowledgements', 'owner_coverage', 'login_daily', 'grant_daily',
        'credential_expiration'
      ) THEN 'all_fallback'
      ELSE 'not_applicable'
    END AS ENVIRONMENT_MODE,
    SOURCE_KEY IN (
      'alert_events', 'security_alerts', 'query_hourly', 'query_recent', 'task_runs',
      'procedure_runs', 'copy_load', 'security_operability', 'change_summary'
    ) AS SUPPORTS_ENVIRONMENT
  FROM VALUES
    ('Executive Landing','executive_observability'),
    ('Executive Landing','executive_scorecard'),
    ('Executive Landing','executive_forecast'),
    ('Executive Landing','closed_loop'),
    ('Executive Landing','production_readiness'),
    ('Executive Landing','data_trust'),
    ('Executive Landing','app_observability'),
    ('Executive Landing','value_ledger'),
    ('Executive Landing','cost_daily'),
    ('Executive Landing','cortex_daily'),
    ('Executive Landing','alert_events'),
    ('Executive Landing','action_queue'),
    ('Executive Landing','query_hourly'),
    ('Executive Landing','task_runs'),
    ('Executive Landing','security_operability'),
    ('DBA Control Room','dba_control_room'),
    ('DBA Control Room','query_hourly'),
    ('DBA Control Room','task_runs'),
    ('DBA Control Room','action_queue'),
    ('DBA Control Room','change_summary'),
    ('DBA Control Room','security_operability'),
    ('DBA Control Room','cost_daily'),
    ('Alert Center','alert_events'),
    ('Alert Center','action_queue'),
    ('Alert Center','notification_log'),
    ('Alert Center','acknowledgements'),
    ('Cost & Contract','cost_daily'),
    ('Cost & Contract','cortex_daily'),
    ('Cost & Contract','cost_signals'),
    ('Cost & Contract','forecast'),
    ('Cost & Contract','value_ledger'),
    ('Cost & Contract','action_queue'),
    ('Cost & Contract','settings'),
    ('Workload Operations','query_hourly'),
    ('Workload Operations','query_recent'),
    ('Workload Operations','task_runs'),
    ('Workload Operations','procedure_runs'),
    ('Workload Operations','copy_load'),
    ('Workload Operations','change_summary'),
    ('Security Monitoring','security_operability'),
    ('Security Monitoring','login_daily'),
    ('Security Monitoring','grant_daily'),
    ('Security Monitoring','security_alerts'),
    ('Security Monitoring','owner_coverage'),
    ('Security Monitoring','change_summary')
  AS v(SECTION_NAME, SOURCE_KEY)
) src
ON cfg.SECTION_NAME = src.SECTION_NAME
AND cfg.SOURCE_KEY = src.SOURCE_KEY
WHEN MATCHED THEN UPDATE SET
  cfg.ENVIRONMENT_MODE = src.ENVIRONMENT_MODE,
  cfg.SUPPORTS_ENVIRONMENT = src.SUPPORTS_ENVIRONMENT;

CREATE TRANSIENT TABLE IF NOT EXISTS MART_SECTION_COMMAND_SOURCE (
  BRIEF_ID                     VARCHAR(64),
  SECTION_NAME                 VARCHAR(200),
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  WINDOW_DAYS                  NUMBER,
  SOURCE_KEY                   VARCHAR(200),
  SOURCE_OBJECT                VARCHAR(500),
  REQUIRED                     BOOLEAN,
  AVAILABLE                    BOOLEAN,
  SOURCE_SNAPSHOT_TS           TIMESTAMP_NTZ,
  AGE_MINUTES                  NUMBER,
  TARGET_FRESHNESS_MINUTES     NUMBER,
  IS_STALE                     BOOLEAN,
  CONFIDENCE                   VARCHAR(40),
  SUPPORTS_ENVIRONMENT         BOOLEAN,
  ENVIRONMENT_SCOPE_MODE       VARCHAR(80),
  GAP_REASON                   VARCHAR(1000),
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

ALTER TABLE IF EXISTS MART_SECTION_COMMAND_SOURCE ADD COLUMN IF NOT EXISTS ENVIRONMENT_SCOPE_MODE VARCHAR(80);
--ALTER TABLE IF EXISTS MART_SECTION_COMMAND_SOURCE ADD COLUMN IF NOT EXISTS SUPPORTS_ENVIRONMENT BOOLEAN DEFAULT FALSE;

CREATE TRANSIENT TABLE IF NOT EXISTS MART_SECTION_DECISION_CURRENT (
  SECTION_NAME                 VARCHAR(200),
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  WINDOW_DAYS                  NUMBER,
  SECTION_NAME_NORM            VARCHAR(200),
  COMPANY_NORM                 VARCHAR(100),
  ENVIRONMENT_NORM             VARCHAR(100),
  WINDOW_DAYS_NORM             NUMBER,
  SCOPE_PRIORITY               NUMBER DEFAULT 0,
  IS_EXACT_SCOPE               BOOLEAN DEFAULT FALSE,
  BRIEF_ID                     VARCHAR(64),
  DECISION_PACKET              VARIANT,
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  SOURCE_SNAPSHOT_TS           TIMESTAMP_NTZ,
  FRESHNESS_MINUTES            NUMBER,
  PACKET_BYTES                 NUMBER,
  IS_ACTIVE                    BOOLEAN DEFAULT TRUE,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

--ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT ADD COLUMN IF NOT EXISTS IS_ACTIVE BOOLEAN DEFAULT TRUE;
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT ADD COLUMN IF NOT EXISTS SECTION_NAME_NORM VARCHAR(200);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT ADD COLUMN IF NOT EXISTS COMPANY_NORM VARCHAR(100);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT ADD COLUMN IF NOT EXISTS ENVIRONMENT_NORM VARCHAR(100);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT ADD COLUMN IF NOT EXISTS WINDOW_DAYS_NORM NUMBER;
--ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT ADD COLUMN IF NOT EXISTS SCOPE_PRIORITY NUMBER DEFAULT 0;
--ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT ADD COLUMN IF NOT EXISTS IS_EXACT_SCOPE BOOLEAN DEFAULT FALSE;

UPDATE MART_SECTION_DECISION_CURRENT
   SET SECTION_NAME_NORM = COALESCE(SECTION_NAME_NORM, UPPER(SECTION_NAME)),
       COMPANY_NORM = COALESCE(COMPANY_NORM, UPPER(COMPANY)),
       ENVIRONMENT_NORM = COALESCE(ENVIRONMENT_NORM, UPPER(ENVIRONMENT)),
       WINDOW_DAYS_NORM = COALESCE(WINDOW_DAYS_NORM, WINDOW_DAYS),
       SCOPE_PRIORITY = COALESCE(
         SCOPE_PRIORITY,
         IFF(UPPER(COMPANY) NOT IN ('ALL', 'GLOBAL'), 4, 0)
           + IFF(UPPER(ENVIRONMENT) NOT IN ('ALL', 'ALL ENVIRONMENTS', 'GLOBAL'), 2, 0)
           + IFF(WINDOW_DAYS IS NOT NULL, 1, 0)
       ),
       IS_EXACT_SCOPE = COALESCE(
         IS_EXACT_SCOPE,
         IFF(
           UPPER(COMPANY) NOT IN ('ALL', 'GLOBAL')
           AND UPPER(ENVIRONMENT) NOT IN ('ALL', 'ALL ENVIRONMENTS', 'GLOBAL')
           AND WINDOW_DAYS IS NOT NULL,
           TRUE,
           FALSE
         )
       );

CREATE TRANSIENT TABLE IF NOT EXISTS MART_SECTION_DECISION_LAST_GOOD (
  SECTION_NAME                 VARCHAR(200),
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  WINDOW_DAYS                  NUMBER,
  SECTION_NAME_NORM            VARCHAR(200),
  COMPANY_NORM                 VARCHAR(100),
  ENVIRONMENT_NORM             VARCHAR(100),
  WINDOW_DAYS_NORM             NUMBER,
  SCOPE_PRIORITY               NUMBER DEFAULT 0,
  IS_EXACT_SCOPE               BOOLEAN DEFAULT FALSE,
  BRIEF_ID                     VARCHAR(64),
  DECISION_PACKET              VARIANT,
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  SOURCE_SNAPSHOT_TS           TIMESTAMP_NTZ,
  FRESHNESS_MINUTES            NUMBER,
  PACKET_BYTES                 NUMBER,
  VALIDATED_AT                 TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

ALTER TABLE IF EXISTS MART_SECTION_DECISION_LAST_GOOD ADD COLUMN IF NOT EXISTS SECTION_NAME_NORM VARCHAR(200);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_LAST_GOOD ADD COLUMN IF NOT EXISTS COMPANY_NORM VARCHAR(100);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_LAST_GOOD ADD COLUMN IF NOT EXISTS ENVIRONMENT_NORM VARCHAR(100);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_LAST_GOOD ADD COLUMN IF NOT EXISTS WINDOW_DAYS_NORM NUMBER;
--ALTER TABLE IF EXISTS MART_SECTION_DECISION_LAST_GOOD ADD COLUMN IF NOT EXISTS SCOPE_PRIORITY NUMBER DEFAULT 0;
--ALTER TABLE IF EXISTS MART_SECTION_DECISION_LAST_GOOD ADD COLUMN IF NOT EXISTS IS_EXACT_SCOPE BOOLEAN DEFAULT FALSE;

UPDATE MART_SECTION_DECISION_LAST_GOOD
   SET SECTION_NAME_NORM = COALESCE(SECTION_NAME_NORM, UPPER(SECTION_NAME)),
       COMPANY_NORM = COALESCE(COMPANY_NORM, UPPER(COMPANY)),
       ENVIRONMENT_NORM = COALESCE(ENVIRONMENT_NORM, UPPER(ENVIRONMENT)),
       WINDOW_DAYS_NORM = COALESCE(WINDOW_DAYS_NORM, WINDOW_DAYS),
       SCOPE_PRIORITY = COALESCE(
         SCOPE_PRIORITY,
         IFF(UPPER(COMPANY) NOT IN ('ALL', 'GLOBAL'), 4, 0)
           + IFF(UPPER(ENVIRONMENT) NOT IN ('ALL', 'ALL ENVIRONMENTS', 'GLOBAL'), 2, 0)
           + IFF(WINDOW_DAYS IS NOT NULL, 1, 0)
       ),
       IS_EXACT_SCOPE = COALESCE(
         IS_EXACT_SCOPE,
         IFF(
           UPPER(COMPANY) NOT IN ('ALL', 'GLOBAL')
           AND UPPER(ENVIRONMENT) NOT IN ('ALL', 'ALL ENVIRONMENTS', 'GLOBAL')
           AND WINDOW_DAYS IS NOT NULL,
           TRUE,
           FALSE
         )
       );

EXECUTE IMMEDIATE $$
DECLARE
  existing_flat_view_count NUMBER DEFAULT 0;
BEGIN
  SELECT COUNT(*)
    INTO :existing_flat_view_count
  FROM INFORMATION_SCHEMA.VIEWS
  WHERE TABLE_SCHEMA = CURRENT_SCHEMA()
    AND TABLE_NAME = 'MART_SECTION_DECISION_CURRENT_FLAT';

  IF (:existing_flat_view_count > 0) THEN
    DROP VIEW IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT;
  END IF;
END;
$$;

CREATE TRANSIENT TABLE IF NOT EXISTS MART_SECTION_DECISION_CURRENT_FLAT (
  SECTION_NAME_NORM            VARCHAR(200),
  COMPANY_NORM                 VARCHAR(100),
  ENVIRONMENT_NORM             VARCHAR(100),
  WINDOW_DAYS_NORM             NUMBER,
  SCOPE_PRIORITY               NUMBER DEFAULT 0,
  IS_EXACT_SCOPE               BOOLEAN DEFAULT FALSE,
  BRIEF_ID                     VARCHAR(64),
  SECTION_NAME                 VARCHAR(200),
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  WINDOW_DAYS                  NUMBER,
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  STATE                        VARCHAR(80),
  HEADLINE                     VARCHAR(1000),
  SUMMARY                      VARCHAR(4000),
  TOP_SIGNAL                   VARCHAR(1000),
  TOP_ENTITY                   VARCHAR(500),
  TOP_ACTION                   VARCHAR(2000),
  SOURCE_STATUS                VARCHAR(200),
  SOURCE_FRESHNESS             VARCHAR(200),
  SOURCE_OBJECTS               VARCHAR(4000),
  SOURCE_SNAPSHOT_TS           TIMESTAMP_NTZ,
  FRESHNESS_MINUTES            NUMBER,
  TARGET_FRESHNESS_MINUTES     NUMBER,
  IS_STALE                     BOOLEAN,
  RESOLVED_COMPANY             VARCHAR(100),
  RESOLVED_ENVIRONMENT         VARCHAR(100),
  RESOLVED_WINDOW_DAYS         NUMBER,
  CONFIDENCE                   VARCHAR(40),
  REQUIRED_SOURCE_COUNT        NUMBER,
  AVAILABLE_SOURCE_COUNT       NUMBER,
  MISSING_SOURCE_COUNT         NUMBER,
  AVAILABLE_REQUIRED_SOURCE_COUNT NUMBER,
  REQUIRED_MISSING_SOURCE_COUNT NUMBER,
  REQUIRED_STALE_SOURCE_COUNT  NUMBER,
  OPTIONAL_SOURCE_COUNT        NUMBER,
  AVAILABLE_OPTIONAL_SOURCE_COUNT NUMBER,
  OPTIONAL_MISSING_SOURCE_COUNT NUMBER,
  OPTIONAL_STALE_SOURCE_COUNT  NUMBER,
  SOURCE_COVERAGE_PCT          NUMBER,
  DATA_AVAILABILITY_STATE      VARCHAR(80),
  STALE_SOURCE_COUNT           NUMBER,
  SOURCE_GAP_DETAIL            VARCHAR(4000),
  ACCOUNT_BILLED_CREDITS       NUMBER(38,6),
  ACCOUNT_BILLED_COST_USD      NUMBER(38,6),
  ACCOUNT_USED_CREDITS         NUMBER(38,6),
  COMPUTE_CREDITS              NUMBER(38,6),
  CLOUD_SERVICES_CREDITS       NUMBER(38,6),
  CLOUD_SERVICES_ADJUSTMENT    NUMBER(38,6),
  ACCOUNT_CLOUD_SERVICES_ADJUSTMENT NUMBER(38,6),
  WAREHOUSE_CREDITS            NUMBER(38,6),
  WAREHOUSE_COST_ESTIMATE_USD  NUMBER(38,6),
  WAREHOUSE_COST_USD           NUMBER(38,6),
  SERVICE_OTHER_CREDITS        NUMBER(38,6),
  SERVICE_OTHER_COST_USD       NUMBER(38,6),
  BILLING_BRIDGE_DELTA_CREDITS NUMBER(38,6),
  BILLING_BRIDGE_DELTA_USD     NUMBER(38,6),
  BILLING_BRIDGE_STATUS        VARCHAR(80),
  CORTEX_AI_CREDITS            NUMBER(38,6),
  CORTEX_AI_COST_USD           NUMBER(38,6),
  BILLING_RECONCILIATION_STATUS VARCHAR(80),
  BILLING_WINDOW_START         DATE,
  BILLING_WINDOW_END           DATE,
  BILLING_WINDOW_COMPLETE      BOOLEAN,
  BILLING_SOURCE_FRESHNESS_TS  TIMESTAMP_NTZ,
  BILLING_LATENCY_NOTE         VARCHAR(1000),
  BILLING_RECONCILIATION_WINDOW_START DATE,
  BILLING_RECONCILIATION_WINDOW_END DATE,
  BILLING_RECONCILIATION_FRESHNESS VARCHAR(200),
  SPEND_MOVEMENT_PCT           NUMBER(18,4),
  FORECAST_RUN_RATE_USD        NUMBER(38,6),
  SECURITY_CREDENTIAL_EXPIRATION_RISK_COUNT NUMBER,
  SECURITY_CREDENTIALS_EXPIRING_30D_COUNT NUMBER,
  SECURITY_CREDENTIALS_EXPIRING_7D_COUNT NUMBER,
  SECURITY_CREDENTIALS_EXPIRED_COUNT NUMBER,
  SECURITY_CREDENTIAL_NEXT_EXPIRATION_TS TIMESTAMP_NTZ,
  SECURITY_CREDENTIAL_NEXT_EXPIRATION_USER VARCHAR(500),
  SECURITY_CREDENTIAL_NEXT_EXPIRATION_TYPE VARCHAR(120),
  SECURITY_CREDENTIAL_EXPIRATION_STATUS VARCHAR(80),
  SECURITY_CREDENTIAL_EXPIRATION_FINDINGS VARIANT,
  SECURITY_CREDENTIAL_SOURCE_CONFIRMED_ZERO BOOLEAN,
  SECURITY_CREDENTIAL_SOURCE_STATUS VARCHAR(80),
  SECURITY_CREDENTIAL_SOURCE_FRESHNESS_TS TIMESTAMP_NTZ,
  SECURITY_CREDENTIAL_SOURCE_LATENCY_NOTE VARCHAR(1000),
  PRIMARY_ACTION_KEY           VARCHAR(200),
  PRIMARY_ROUTE_KEY            VARCHAR(200),
  PRIMARY_ACTION_LABEL         VARCHAR(500),
  PRIMARY_ACTION_DETAIL        VARCHAR(2000),
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  METRICS                      VARIANT,
  EXCEPTIONS                   VARIANT,
  ACTIONS                      VARIANT,
  SOURCES                      VARIANT,
  PACKET_BYTES                 NUMBER,
  IS_ACTIVE                    BOOLEAN DEFAULT TRUE
);

ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS ACCOUNT_BILLED_CREDITS NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS ACCOUNT_BILLED_COST_USD NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS ACCOUNT_USED_CREDITS NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS COMPUTE_CREDITS NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS CLOUD_SERVICES_CREDITS NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS CLOUD_SERVICES_ADJUSTMENT NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS ACCOUNT_CLOUD_SERVICES_ADJUSTMENT NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS WAREHOUSE_CREDITS NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS WAREHOUSE_COST_ESTIMATE_USD NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS WAREHOUSE_COST_USD NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS SERVICE_OTHER_CREDITS NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS SERVICE_OTHER_COST_USD NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS BILLING_BRIDGE_DELTA_CREDITS NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS BILLING_BRIDGE_DELTA_USD NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS BILLING_BRIDGE_STATUS VARCHAR(80);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS CORTEX_AI_CREDITS NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS CORTEX_AI_COST_USD NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS BILLING_RECONCILIATION_STATUS VARCHAR(80);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS BILLING_WINDOW_START DATE;
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS BILLING_WINDOW_END DATE;
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS BILLING_WINDOW_COMPLETE BOOLEAN;
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS BILLING_SOURCE_FRESHNESS_TS TIMESTAMP_NTZ;
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS BILLING_LATENCY_NOTE VARCHAR(1000);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS BILLING_RECONCILIATION_WINDOW_START DATE;
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS BILLING_RECONCILIATION_WINDOW_END DATE;
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS BILLING_RECONCILIATION_FRESHNESS VARCHAR(200);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS SPEND_MOVEMENT_PCT NUMBER(18,4);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS FORECAST_RUN_RATE_USD NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS SECURITY_CREDENTIAL_EXPIRATION_RISK_COUNT NUMBER;
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS SECURITY_CREDENTIALS_EXPIRING_30D_COUNT NUMBER;
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS SECURITY_CREDENTIALS_EXPIRING_7D_COUNT NUMBER;
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS SECURITY_CREDENTIALS_EXPIRED_COUNT NUMBER;
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS SECURITY_CREDENTIAL_NEXT_EXPIRATION_TS TIMESTAMP_NTZ;
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS SECURITY_CREDENTIAL_NEXT_EXPIRATION_USER VARCHAR(500);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS SECURITY_CREDENTIAL_NEXT_EXPIRATION_TYPE VARCHAR(120);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS SECURITY_CREDENTIAL_EXPIRATION_STATUS VARCHAR(80);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS SECURITY_CREDENTIAL_EXPIRATION_FINDINGS VARIANT;
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS SECURITY_CREDENTIAL_SOURCE_CONFIRMED_ZERO BOOLEAN;
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS SECURITY_CREDENTIAL_SOURCE_STATUS VARCHAR(80);
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS SECURITY_CREDENTIAL_SOURCE_FRESHNESS_TS TIMESTAMP_NTZ;
ALTER TABLE IF EXISTS MART_SECTION_DECISION_CURRENT_FLAT ADD COLUMN IF NOT EXISTS SECURITY_CREDENTIAL_SOURCE_LATENCY_NOTE VARCHAR(1000);

MERGE INTO MART_SECTION_DECISION_CURRENT_FLAT flat
USING (
  SELECT
    COALESCE(SECTION_NAME_NORM, UPPER(SECTION_NAME)) AS SECTION_NAME_NORM,
    COALESCE(COMPANY_NORM, UPPER(COMPANY)) AS COMPANY_NORM,
    COALESCE(ENVIRONMENT_NORM, UPPER(ENVIRONMENT)) AS ENVIRONMENT_NORM,
    COALESCE(WINDOW_DAYS_NORM, WINDOW_DAYS) AS WINDOW_DAYS_NORM,
    COALESCE(SCOPE_PRIORITY, 0) AS SCOPE_PRIORITY,
    COALESCE(IS_EXACT_SCOPE, FALSE) AS IS_EXACT_SCOPE,
    BRIEF_ID, SECTION_NAME, COMPANY, ENVIRONMENT, WINDOW_DAYS,
    COALESCE(DECISION_PACKET:"SNAPSHOT_TS"::TIMESTAMP_NTZ, SNAPSHOT_TS) AS SNAPSHOT_TS,
    DECISION_PACKET:"STATE"::VARCHAR AS STATE,
    DECISION_PACKET:"HEADLINE"::VARCHAR AS HEADLINE,
    DECISION_PACKET:"SUMMARY"::VARCHAR AS SUMMARY,
    DECISION_PACKET:"TOP_SIGNAL"::VARCHAR AS TOP_SIGNAL,
    DECISION_PACKET:"TOP_ENTITY"::VARCHAR AS TOP_ENTITY,
    DECISION_PACKET:"TOP_ACTION"::VARCHAR AS TOP_ACTION,
    DECISION_PACKET:"SOURCE_STATUS"::VARCHAR AS SOURCE_STATUS,
    DECISION_PACKET:"SOURCE_FRESHNESS"::VARCHAR AS SOURCE_FRESHNESS,
    DECISION_PACKET:"SOURCE_OBJECTS"::VARCHAR AS SOURCE_OBJECTS,
    COALESCE(DECISION_PACKET:"SOURCE_SNAPSHOT_TS"::TIMESTAMP_NTZ, SOURCE_SNAPSHOT_TS) AS SOURCE_SNAPSHOT_TS,
    COALESCE(TRY_TO_NUMBER(DECISION_PACKET:"FRESHNESS_MINUTES"::VARCHAR), FRESHNESS_MINUTES) AS FRESHNESS_MINUTES,
    TRY_TO_NUMBER(DECISION_PACKET:"TARGET_FRESHNESS_MINUTES"::VARCHAR) AS TARGET_FRESHNESS_MINUTES,
    DECISION_PACKET:"IS_STALE"::BOOLEAN AS IS_STALE,
    DECISION_PACKET:"RESOLVED_COMPANY"::VARCHAR AS RESOLVED_COMPANY,
    DECISION_PACKET:"RESOLVED_ENVIRONMENT"::VARCHAR AS RESOLVED_ENVIRONMENT,
    TRY_TO_NUMBER(DECISION_PACKET:"RESOLVED_WINDOW_DAYS"::VARCHAR) AS RESOLVED_WINDOW_DAYS,
    DECISION_PACKET:"CONFIDENCE"::VARCHAR AS CONFIDENCE,
    TRY_TO_NUMBER(DECISION_PACKET:"REQUIRED_SOURCE_COUNT"::VARCHAR) AS REQUIRED_SOURCE_COUNT,
    COALESCE(
      TRY_TO_NUMBER(DECISION_PACKET:"AVAILABLE_REQUIRED_SOURCE_COUNT"::VARCHAR),
      TRY_TO_NUMBER(DECISION_PACKET:"AVAILABLE_SOURCE_COUNT"::VARCHAR)
    ) AS AVAILABLE_SOURCE_COUNT,
    COALESCE(
      TRY_TO_NUMBER(DECISION_PACKET:"REQUIRED_MISSING_SOURCE_COUNT"::VARCHAR),
      TRY_TO_NUMBER(DECISION_PACKET:"MISSING_SOURCE_COUNT"::VARCHAR)
    ) AS MISSING_SOURCE_COUNT,
    TRY_TO_NUMBER(DECISION_PACKET:"AVAILABLE_REQUIRED_SOURCE_COUNT"::VARCHAR) AS AVAILABLE_REQUIRED_SOURCE_COUNT,
    TRY_TO_NUMBER(DECISION_PACKET:"REQUIRED_MISSING_SOURCE_COUNT"::VARCHAR) AS REQUIRED_MISSING_SOURCE_COUNT,
    TRY_TO_NUMBER(DECISION_PACKET:"REQUIRED_STALE_SOURCE_COUNT"::VARCHAR) AS REQUIRED_STALE_SOURCE_COUNT,
    TRY_TO_NUMBER(DECISION_PACKET:"OPTIONAL_SOURCE_COUNT"::VARCHAR) AS OPTIONAL_SOURCE_COUNT,
    TRY_TO_NUMBER(DECISION_PACKET:"AVAILABLE_OPTIONAL_SOURCE_COUNT"::VARCHAR) AS AVAILABLE_OPTIONAL_SOURCE_COUNT,
    TRY_TO_NUMBER(DECISION_PACKET:"OPTIONAL_MISSING_SOURCE_COUNT"::VARCHAR) AS OPTIONAL_MISSING_SOURCE_COUNT,
    TRY_TO_NUMBER(DECISION_PACKET:"OPTIONAL_STALE_SOURCE_COUNT"::VARCHAR) AS OPTIONAL_STALE_SOURCE_COUNT,
    TRY_TO_NUMBER(DECISION_PACKET:"SOURCE_COVERAGE_PCT"::VARCHAR) AS SOURCE_COVERAGE_PCT,
    DECISION_PACKET:"DATA_AVAILABILITY_STATE"::VARCHAR AS DATA_AVAILABILITY_STATE,
    TRY_TO_NUMBER(DECISION_PACKET:"STALE_SOURCE_COUNT"::VARCHAR) AS STALE_SOURCE_COUNT,
    DECISION_PACKET:"SOURCE_GAP_DETAIL"::VARCHAR AS SOURCE_GAP_DETAIL,
    TRY_TO_NUMBER(DECISION_PACKET:"ACCOUNT_BILLED_CREDITS"::VARCHAR) AS ACCOUNT_BILLED_CREDITS,
    TRY_TO_NUMBER(DECISION_PACKET:"ACCOUNT_BILLED_COST_USD"::VARCHAR) AS ACCOUNT_BILLED_COST_USD,
    TRY_TO_NUMBER(DECISION_PACKET:"ACCOUNT_USED_CREDITS"::VARCHAR) AS ACCOUNT_USED_CREDITS,
    TRY_TO_NUMBER(DECISION_PACKET:"COMPUTE_CREDITS"::VARCHAR) AS COMPUTE_CREDITS,
    TRY_TO_NUMBER(DECISION_PACKET:"CLOUD_SERVICES_CREDITS"::VARCHAR) AS CLOUD_SERVICES_CREDITS,
    TRY_TO_NUMBER(DECISION_PACKET:"CLOUD_SERVICES_ADJUSTMENT"::VARCHAR) AS CLOUD_SERVICES_ADJUSTMENT,
    TRY_TO_NUMBER(DECISION_PACKET:"ACCOUNT_CLOUD_SERVICES_ADJUSTMENT"::VARCHAR) AS ACCOUNT_CLOUD_SERVICES_ADJUSTMENT,
    TRY_TO_NUMBER(DECISION_PACKET:"WAREHOUSE_CREDITS"::VARCHAR) AS WAREHOUSE_CREDITS,
    TRY_TO_NUMBER(DECISION_PACKET:"WAREHOUSE_COST_ESTIMATE_USD"::VARCHAR) AS WAREHOUSE_COST_ESTIMATE_USD,
    TRY_TO_NUMBER(DECISION_PACKET:"WAREHOUSE_COST_USD"::VARCHAR) AS WAREHOUSE_COST_USD,
    TRY_TO_NUMBER(DECISION_PACKET:"SERVICE_OTHER_CREDITS"::VARCHAR) AS SERVICE_OTHER_CREDITS,
    TRY_TO_NUMBER(DECISION_PACKET:"SERVICE_OTHER_COST_USD"::VARCHAR) AS SERVICE_OTHER_COST_USD,
    TRY_TO_NUMBER(DECISION_PACKET:"BILLING_BRIDGE_DELTA_CREDITS"::VARCHAR) AS BILLING_BRIDGE_DELTA_CREDITS,
    TRY_TO_NUMBER(DECISION_PACKET:"BILLING_BRIDGE_DELTA_USD"::VARCHAR) AS BILLING_BRIDGE_DELTA_USD,
    DECISION_PACKET:"BILLING_BRIDGE_STATUS"::VARCHAR AS BILLING_BRIDGE_STATUS,
    TRY_TO_NUMBER(DECISION_PACKET:"CORTEX_AI_CREDITS"::VARCHAR) AS CORTEX_AI_CREDITS,
    TRY_TO_NUMBER(DECISION_PACKET:"CORTEX_AI_COST_USD"::VARCHAR) AS CORTEX_AI_COST_USD,
    DECISION_PACKET:"BILLING_RECONCILIATION_STATUS"::VARCHAR AS BILLING_RECONCILIATION_STATUS,
    DECISION_PACKET:"BILLING_WINDOW_START"::DATE AS BILLING_WINDOW_START,
    DECISION_PACKET:"BILLING_WINDOW_END"::DATE AS BILLING_WINDOW_END,
    DECISION_PACKET:"BILLING_WINDOW_COMPLETE"::BOOLEAN AS BILLING_WINDOW_COMPLETE,
    DECISION_PACKET:"BILLING_SOURCE_FRESHNESS_TS"::TIMESTAMP_NTZ AS BILLING_SOURCE_FRESHNESS_TS,
    DECISION_PACKET:"BILLING_LATENCY_NOTE"::VARCHAR AS BILLING_LATENCY_NOTE,
    DECISION_PACKET:"BILLING_RECONCILIATION_WINDOW_START"::DATE AS BILLING_RECONCILIATION_WINDOW_START,
    DECISION_PACKET:"BILLING_RECONCILIATION_WINDOW_END"::DATE AS BILLING_RECONCILIATION_WINDOW_END,
    DECISION_PACKET:"BILLING_RECONCILIATION_FRESHNESS"::VARCHAR AS BILLING_RECONCILIATION_FRESHNESS,
    TRY_TO_NUMBER(DECISION_PACKET:"SPEND_MOVEMENT_PCT"::VARCHAR) AS SPEND_MOVEMENT_PCT,
    TRY_TO_NUMBER(DECISION_PACKET:"FORECAST_RUN_RATE_USD"::VARCHAR) AS FORECAST_RUN_RATE_USD,
    TRY_TO_NUMBER(DECISION_PACKET:"SECURITY_CREDENTIAL_EXPIRATION_RISK_COUNT"::VARCHAR) AS SECURITY_CREDENTIAL_EXPIRATION_RISK_COUNT,
    TRY_TO_NUMBER(DECISION_PACKET:"SECURITY_CREDENTIALS_EXPIRING_30D_COUNT"::VARCHAR) AS SECURITY_CREDENTIALS_EXPIRING_30D_COUNT,
    TRY_TO_NUMBER(DECISION_PACKET:"SECURITY_CREDENTIALS_EXPIRING_7D_COUNT"::VARCHAR) AS SECURITY_CREDENTIALS_EXPIRING_7D_COUNT,
    TRY_TO_NUMBER(DECISION_PACKET:"SECURITY_CREDENTIALS_EXPIRED_COUNT"::VARCHAR) AS SECURITY_CREDENTIALS_EXPIRED_COUNT,
    DECISION_PACKET:"SECURITY_CREDENTIAL_NEXT_EXPIRATION_TS"::TIMESTAMP_NTZ AS SECURITY_CREDENTIAL_NEXT_EXPIRATION_TS,
    DECISION_PACKET:"SECURITY_CREDENTIAL_NEXT_EXPIRATION_USER"::VARCHAR AS SECURITY_CREDENTIAL_NEXT_EXPIRATION_USER,
    DECISION_PACKET:"SECURITY_CREDENTIAL_NEXT_EXPIRATION_TYPE"::VARCHAR AS SECURITY_CREDENTIAL_NEXT_EXPIRATION_TYPE,
    DECISION_PACKET:"SECURITY_CREDENTIAL_EXPIRATION_STATUS"::VARCHAR AS SECURITY_CREDENTIAL_EXPIRATION_STATUS,
    DECISION_PACKET:"SECURITY_CREDENTIAL_EXPIRATION_FINDINGS" AS SECURITY_CREDENTIAL_EXPIRATION_FINDINGS,
    DECISION_PACKET:"SECURITY_CREDENTIAL_SOURCE_CONFIRMED_ZERO"::BOOLEAN AS SECURITY_CREDENTIAL_SOURCE_CONFIRMED_ZERO,
    DECISION_PACKET:"SECURITY_CREDENTIAL_SOURCE_STATUS"::VARCHAR AS SECURITY_CREDENTIAL_SOURCE_STATUS,
    DECISION_PACKET:"SECURITY_CREDENTIAL_SOURCE_FRESHNESS_TS"::TIMESTAMP_NTZ AS SECURITY_CREDENTIAL_SOURCE_FRESHNESS_TS,
    DECISION_PACKET:"SECURITY_CREDENTIAL_SOURCE_LATENCY_NOTE"::VARCHAR AS SECURITY_CREDENTIAL_SOURCE_LATENCY_NOTE,
    DECISION_PACKET:"PRIMARY_ACTION_KEY"::VARCHAR AS PRIMARY_ACTION_KEY,
    DECISION_PACKET:"PRIMARY_ROUTE_KEY"::VARCHAR AS PRIMARY_ROUTE_KEY,
    DECISION_PACKET:"PRIMARY_ACTION_LABEL"::VARCHAR AS PRIMARY_ACTION_LABEL,
    DECISION_PACKET:"PRIMARY_ACTION_DETAIL"::VARCHAR AS PRIMARY_ACTION_DETAIL,
    COALESCE(DECISION_PACKET:"LOAD_TS"::TIMESTAMP_NTZ, LOAD_TS) AS LOAD_TS,
    DECISION_PACKET:"METRICS" AS METRICS,
    DECISION_PACKET:"EXCEPTIONS" AS EXCEPTIONS,
    DECISION_PACKET:"ACTIONS" AS ACTIONS,
    DECISION_PACKET:"SOURCES" AS SOURCES,
    PACKET_BYTES,
    COALESCE(IS_ACTIVE, TRUE) AS IS_ACTIVE
  FROM MART_SECTION_DECISION_CURRENT
) cur
ON flat.SECTION_NAME = cur.SECTION_NAME
AND flat.COMPANY = cur.COMPANY
AND flat.ENVIRONMENT = cur.ENVIRONMENT
AND flat.WINDOW_DAYS = cur.WINDOW_DAYS
WHEN MATCHED THEN UPDATE SET
  SECTION_NAME_NORM = cur.SECTION_NAME_NORM,
  COMPANY_NORM = cur.COMPANY_NORM,
  ENVIRONMENT_NORM = cur.ENVIRONMENT_NORM,
  WINDOW_DAYS_NORM = cur.WINDOW_DAYS_NORM,
  SCOPE_PRIORITY = cur.SCOPE_PRIORITY,
  IS_EXACT_SCOPE = cur.IS_EXACT_SCOPE,
  BRIEF_ID = cur.BRIEF_ID,
  SNAPSHOT_TS = cur.SNAPSHOT_TS,
  STATE = cur.STATE,
  HEADLINE = cur.HEADLINE,
  SUMMARY = cur.SUMMARY,
  TOP_SIGNAL = cur.TOP_SIGNAL,
  TOP_ENTITY = cur.TOP_ENTITY,
  TOP_ACTION = cur.TOP_ACTION,
  SOURCE_STATUS = cur.SOURCE_STATUS,
  SOURCE_FRESHNESS = cur.SOURCE_FRESHNESS,
  SOURCE_OBJECTS = cur.SOURCE_OBJECTS,
  SOURCE_SNAPSHOT_TS = cur.SOURCE_SNAPSHOT_TS,
  FRESHNESS_MINUTES = cur.FRESHNESS_MINUTES,
  TARGET_FRESHNESS_MINUTES = cur.TARGET_FRESHNESS_MINUTES,
  IS_STALE = cur.IS_STALE,
  RESOLVED_COMPANY = cur.RESOLVED_COMPANY,
  RESOLVED_ENVIRONMENT = cur.RESOLVED_ENVIRONMENT,
  RESOLVED_WINDOW_DAYS = cur.RESOLVED_WINDOW_DAYS,
  CONFIDENCE = cur.CONFIDENCE,
  REQUIRED_SOURCE_COUNT = cur.REQUIRED_SOURCE_COUNT,
  AVAILABLE_SOURCE_COUNT = cur.AVAILABLE_SOURCE_COUNT,
  MISSING_SOURCE_COUNT = cur.MISSING_SOURCE_COUNT,
  AVAILABLE_REQUIRED_SOURCE_COUNT = cur.AVAILABLE_REQUIRED_SOURCE_COUNT,
  REQUIRED_MISSING_SOURCE_COUNT = cur.REQUIRED_MISSING_SOURCE_COUNT,
  REQUIRED_STALE_SOURCE_COUNT = cur.REQUIRED_STALE_SOURCE_COUNT,
  OPTIONAL_SOURCE_COUNT = cur.OPTIONAL_SOURCE_COUNT,
  AVAILABLE_OPTIONAL_SOURCE_COUNT = cur.AVAILABLE_OPTIONAL_SOURCE_COUNT,
  OPTIONAL_MISSING_SOURCE_COUNT = cur.OPTIONAL_MISSING_SOURCE_COUNT,
  OPTIONAL_STALE_SOURCE_COUNT = cur.OPTIONAL_STALE_SOURCE_COUNT,
  SOURCE_COVERAGE_PCT = cur.SOURCE_COVERAGE_PCT,
  DATA_AVAILABILITY_STATE = cur.DATA_AVAILABILITY_STATE,
  STALE_SOURCE_COUNT = cur.STALE_SOURCE_COUNT,
  SOURCE_GAP_DETAIL = cur.SOURCE_GAP_DETAIL,
  ACCOUNT_BILLED_CREDITS = cur.ACCOUNT_BILLED_CREDITS,
  ACCOUNT_BILLED_COST_USD = cur.ACCOUNT_BILLED_COST_USD,
  ACCOUNT_USED_CREDITS = cur.ACCOUNT_USED_CREDITS,
  COMPUTE_CREDITS = cur.COMPUTE_CREDITS,
  CLOUD_SERVICES_CREDITS = cur.CLOUD_SERVICES_CREDITS,
  CLOUD_SERVICES_ADJUSTMENT = cur.CLOUD_SERVICES_ADJUSTMENT,
  ACCOUNT_CLOUD_SERVICES_ADJUSTMENT = cur.ACCOUNT_CLOUD_SERVICES_ADJUSTMENT,
  WAREHOUSE_CREDITS = cur.WAREHOUSE_CREDITS,
  WAREHOUSE_COST_ESTIMATE_USD = cur.WAREHOUSE_COST_ESTIMATE_USD,
  WAREHOUSE_COST_USD = cur.WAREHOUSE_COST_USD,
  SERVICE_OTHER_CREDITS = cur.SERVICE_OTHER_CREDITS,
  SERVICE_OTHER_COST_USD = cur.SERVICE_OTHER_COST_USD,
  BILLING_BRIDGE_DELTA_CREDITS = cur.BILLING_BRIDGE_DELTA_CREDITS,
  BILLING_BRIDGE_DELTA_USD = cur.BILLING_BRIDGE_DELTA_USD,
  BILLING_BRIDGE_STATUS = cur.BILLING_BRIDGE_STATUS,
  CORTEX_AI_CREDITS = cur.CORTEX_AI_CREDITS,
  CORTEX_AI_COST_USD = cur.CORTEX_AI_COST_USD,
  BILLING_RECONCILIATION_STATUS = cur.BILLING_RECONCILIATION_STATUS,
  BILLING_WINDOW_START = cur.BILLING_WINDOW_START,
  BILLING_WINDOW_END = cur.BILLING_WINDOW_END,
  BILLING_WINDOW_COMPLETE = cur.BILLING_WINDOW_COMPLETE,
  BILLING_SOURCE_FRESHNESS_TS = cur.BILLING_SOURCE_FRESHNESS_TS,
  BILLING_LATENCY_NOTE = cur.BILLING_LATENCY_NOTE,
  BILLING_RECONCILIATION_WINDOW_START = cur.BILLING_RECONCILIATION_WINDOW_START,
  BILLING_RECONCILIATION_WINDOW_END = cur.BILLING_RECONCILIATION_WINDOW_END,
  BILLING_RECONCILIATION_FRESHNESS = cur.BILLING_RECONCILIATION_FRESHNESS,
  SPEND_MOVEMENT_PCT = cur.SPEND_MOVEMENT_PCT,
  FORECAST_RUN_RATE_USD = cur.FORECAST_RUN_RATE_USD,
  SECURITY_CREDENTIAL_EXPIRATION_RISK_COUNT = cur.SECURITY_CREDENTIAL_EXPIRATION_RISK_COUNT,
  SECURITY_CREDENTIALS_EXPIRING_30D_COUNT = cur.SECURITY_CREDENTIALS_EXPIRING_30D_COUNT,
  SECURITY_CREDENTIALS_EXPIRING_7D_COUNT = cur.SECURITY_CREDENTIALS_EXPIRING_7D_COUNT,
  SECURITY_CREDENTIALS_EXPIRED_COUNT = cur.SECURITY_CREDENTIALS_EXPIRED_COUNT,
  SECURITY_CREDENTIAL_NEXT_EXPIRATION_TS = cur.SECURITY_CREDENTIAL_NEXT_EXPIRATION_TS,
  SECURITY_CREDENTIAL_NEXT_EXPIRATION_USER = cur.SECURITY_CREDENTIAL_NEXT_EXPIRATION_USER,
  SECURITY_CREDENTIAL_NEXT_EXPIRATION_TYPE = cur.SECURITY_CREDENTIAL_NEXT_EXPIRATION_TYPE,
  SECURITY_CREDENTIAL_EXPIRATION_STATUS = cur.SECURITY_CREDENTIAL_EXPIRATION_STATUS,
  SECURITY_CREDENTIAL_EXPIRATION_FINDINGS = cur.SECURITY_CREDENTIAL_EXPIRATION_FINDINGS,
  SECURITY_CREDENTIAL_SOURCE_CONFIRMED_ZERO = cur.SECURITY_CREDENTIAL_SOURCE_CONFIRMED_ZERO,
  SECURITY_CREDENTIAL_SOURCE_STATUS = cur.SECURITY_CREDENTIAL_SOURCE_STATUS,
  SECURITY_CREDENTIAL_SOURCE_FRESHNESS_TS = cur.SECURITY_CREDENTIAL_SOURCE_FRESHNESS_TS,
  SECURITY_CREDENTIAL_SOURCE_LATENCY_NOTE = cur.SECURITY_CREDENTIAL_SOURCE_LATENCY_NOTE,
  PRIMARY_ACTION_KEY = cur.PRIMARY_ACTION_KEY,
  PRIMARY_ROUTE_KEY = cur.PRIMARY_ROUTE_KEY,
  PRIMARY_ACTION_LABEL = cur.PRIMARY_ACTION_LABEL,
  PRIMARY_ACTION_DETAIL = cur.PRIMARY_ACTION_DETAIL,
  LOAD_TS = cur.LOAD_TS,
  METRICS = cur.METRICS,
  EXCEPTIONS = cur.EXCEPTIONS,
  ACTIONS = cur.ACTIONS,
  SOURCES = cur.SOURCES,
  PACKET_BYTES = cur.PACKET_BYTES,
  IS_ACTIVE = cur.IS_ACTIVE
WHEN NOT MATCHED THEN INSERT (
  SECTION_NAME_NORM, COMPANY_NORM, ENVIRONMENT_NORM, WINDOW_DAYS_NORM, SCOPE_PRIORITY, IS_EXACT_SCOPE,
  BRIEF_ID, SECTION_NAME, COMPANY, ENVIRONMENT, WINDOW_DAYS, SNAPSHOT_TS, STATE, HEADLINE, SUMMARY,
  TOP_SIGNAL, TOP_ENTITY, TOP_ACTION, SOURCE_STATUS, SOURCE_FRESHNESS, SOURCE_OBJECTS, SOURCE_SNAPSHOT_TS,
  FRESHNESS_MINUTES, TARGET_FRESHNESS_MINUTES, IS_STALE, RESOLVED_COMPANY, RESOLVED_ENVIRONMENT,
  RESOLVED_WINDOW_DAYS, CONFIDENCE, REQUIRED_SOURCE_COUNT, AVAILABLE_SOURCE_COUNT, MISSING_SOURCE_COUNT,
  AVAILABLE_REQUIRED_SOURCE_COUNT, REQUIRED_MISSING_SOURCE_COUNT, REQUIRED_STALE_SOURCE_COUNT,
  OPTIONAL_SOURCE_COUNT, AVAILABLE_OPTIONAL_SOURCE_COUNT, OPTIONAL_MISSING_SOURCE_COUNT,
  OPTIONAL_STALE_SOURCE_COUNT, SOURCE_COVERAGE_PCT, DATA_AVAILABILITY_STATE, STALE_SOURCE_COUNT,
  SOURCE_GAP_DETAIL,
  ACCOUNT_BILLED_CREDITS, ACCOUNT_BILLED_COST_USD, ACCOUNT_USED_CREDITS, COMPUTE_CREDITS,
  CLOUD_SERVICES_CREDITS, CLOUD_SERVICES_ADJUSTMENT, ACCOUNT_CLOUD_SERVICES_ADJUSTMENT,
  WAREHOUSE_CREDITS, WAREHOUSE_COST_ESTIMATE_USD, WAREHOUSE_COST_USD,
  SERVICE_OTHER_CREDITS, SERVICE_OTHER_COST_USD, BILLING_BRIDGE_DELTA_CREDITS,
  BILLING_BRIDGE_DELTA_USD, BILLING_BRIDGE_STATUS, CORTEX_AI_CREDITS, CORTEX_AI_COST_USD,
  BILLING_RECONCILIATION_STATUS, BILLING_WINDOW_START, BILLING_WINDOW_END, BILLING_WINDOW_COMPLETE,
  BILLING_SOURCE_FRESHNESS_TS, BILLING_LATENCY_NOTE, BILLING_RECONCILIATION_WINDOW_START,
  BILLING_RECONCILIATION_WINDOW_END, BILLING_RECONCILIATION_FRESHNESS, SPEND_MOVEMENT_PCT,
  FORECAST_RUN_RATE_USD,
  SECURITY_CREDENTIAL_EXPIRATION_RISK_COUNT, SECURITY_CREDENTIALS_EXPIRING_30D_COUNT,
  SECURITY_CREDENTIALS_EXPIRING_7D_COUNT, SECURITY_CREDENTIALS_EXPIRED_COUNT,
  SECURITY_CREDENTIAL_NEXT_EXPIRATION_TS, SECURITY_CREDENTIAL_NEXT_EXPIRATION_USER,
  SECURITY_CREDENTIAL_NEXT_EXPIRATION_TYPE, SECURITY_CREDENTIAL_EXPIRATION_STATUS,
  SECURITY_CREDENTIAL_EXPIRATION_FINDINGS, SECURITY_CREDENTIAL_SOURCE_CONFIRMED_ZERO,
  SECURITY_CREDENTIAL_SOURCE_STATUS, SECURITY_CREDENTIAL_SOURCE_FRESHNESS_TS,
  SECURITY_CREDENTIAL_SOURCE_LATENCY_NOTE,
  PRIMARY_ACTION_KEY, PRIMARY_ROUTE_KEY, PRIMARY_ACTION_LABEL, PRIMARY_ACTION_DETAIL,
  LOAD_TS, METRICS, EXCEPTIONS, ACTIONS, SOURCES, PACKET_BYTES, IS_ACTIVE
) VALUES (
  cur.SECTION_NAME_NORM, cur.COMPANY_NORM, cur.ENVIRONMENT_NORM, cur.WINDOW_DAYS_NORM, cur.SCOPE_PRIORITY, cur.IS_EXACT_SCOPE,
  cur.BRIEF_ID, cur.SECTION_NAME, cur.COMPANY, cur.ENVIRONMENT, cur.WINDOW_DAYS, cur.SNAPSHOT_TS, cur.STATE, cur.HEADLINE, cur.SUMMARY,
  cur.TOP_SIGNAL, cur.TOP_ENTITY, cur.TOP_ACTION, cur.SOURCE_STATUS, cur.SOURCE_FRESHNESS, cur.SOURCE_OBJECTS, cur.SOURCE_SNAPSHOT_TS,
  cur.FRESHNESS_MINUTES, cur.TARGET_FRESHNESS_MINUTES, cur.IS_STALE, cur.RESOLVED_COMPANY, cur.RESOLVED_ENVIRONMENT,
  cur.RESOLVED_WINDOW_DAYS, cur.CONFIDENCE, cur.REQUIRED_SOURCE_COUNT, cur.AVAILABLE_SOURCE_COUNT, cur.MISSING_SOURCE_COUNT,
  cur.AVAILABLE_REQUIRED_SOURCE_COUNT, cur.REQUIRED_MISSING_SOURCE_COUNT, cur.REQUIRED_STALE_SOURCE_COUNT,
  cur.OPTIONAL_SOURCE_COUNT, cur.AVAILABLE_OPTIONAL_SOURCE_COUNT, cur.OPTIONAL_MISSING_SOURCE_COUNT,
  cur.OPTIONAL_STALE_SOURCE_COUNT, cur.SOURCE_COVERAGE_PCT, cur.DATA_AVAILABILITY_STATE, cur.STALE_SOURCE_COUNT,
  cur.SOURCE_GAP_DETAIL,
  cur.ACCOUNT_BILLED_CREDITS, cur.ACCOUNT_BILLED_COST_USD, cur.ACCOUNT_USED_CREDITS, cur.COMPUTE_CREDITS,
  cur.CLOUD_SERVICES_CREDITS, cur.CLOUD_SERVICES_ADJUSTMENT, cur.ACCOUNT_CLOUD_SERVICES_ADJUSTMENT,
  cur.WAREHOUSE_CREDITS, cur.WAREHOUSE_COST_ESTIMATE_USD, cur.WAREHOUSE_COST_USD,
  cur.SERVICE_OTHER_CREDITS, cur.SERVICE_OTHER_COST_USD, cur.BILLING_BRIDGE_DELTA_CREDITS,
  cur.BILLING_BRIDGE_DELTA_USD, cur.BILLING_BRIDGE_STATUS, cur.CORTEX_AI_CREDITS, cur.CORTEX_AI_COST_USD,
  cur.BILLING_RECONCILIATION_STATUS, cur.BILLING_WINDOW_START, cur.BILLING_WINDOW_END, cur.BILLING_WINDOW_COMPLETE,
  cur.BILLING_SOURCE_FRESHNESS_TS, cur.BILLING_LATENCY_NOTE, cur.BILLING_RECONCILIATION_WINDOW_START,
  cur.BILLING_RECONCILIATION_WINDOW_END, cur.BILLING_RECONCILIATION_FRESHNESS, cur.SPEND_MOVEMENT_PCT,
  cur.FORECAST_RUN_RATE_USD,
  cur.SECURITY_CREDENTIAL_EXPIRATION_RISK_COUNT, cur.SECURITY_CREDENTIALS_EXPIRING_30D_COUNT,
  cur.SECURITY_CREDENTIALS_EXPIRING_7D_COUNT, cur.SECURITY_CREDENTIALS_EXPIRED_COUNT,
  cur.SECURITY_CREDENTIAL_NEXT_EXPIRATION_TS, cur.SECURITY_CREDENTIAL_NEXT_EXPIRATION_USER,
  cur.SECURITY_CREDENTIAL_NEXT_EXPIRATION_TYPE, cur.SECURITY_CREDENTIAL_EXPIRATION_STATUS,
  cur.SECURITY_CREDENTIAL_EXPIRATION_FINDINGS, cur.SECURITY_CREDENTIAL_SOURCE_CONFIRMED_ZERO,
  cur.SECURITY_CREDENTIAL_SOURCE_STATUS, cur.SECURITY_CREDENTIAL_SOURCE_FRESHNESS_TS,
  cur.SECURITY_CREDENTIAL_SOURCE_LATENCY_NOTE,
  cur.PRIMARY_ACTION_KEY, cur.PRIMARY_ROUTE_KEY, cur.PRIMARY_ACTION_LABEL, cur.PRIMARY_ACTION_DETAIL,
  cur.LOAD_TS, cur.METRICS, cur.EXCEPTIONS, cur.ACTIONS, cur.SOURCES, cur.PACKET_BYTES, cur.IS_ACTIVE
);

CREATE TABLE IF NOT EXISTS OVERWATCH_DECISION_SETUP_HEALTH (
  EVENT_ID                     VARCHAR(64),
  EVENT_TS                     TIMESTAMP_NTZ,
  STATUS                       VARCHAR(40),
  USER_MESSAGE                 VARCHAR(2000),
  GLOBAL_STATUS                VARCHAR(40),
  SELECTED_SCOPE_STATUS        VARCHAR(40),
  CURRENT_SECTION_STATUS       VARCHAR(40),
  SELECTED_PROCEDURE           VARCHAR(300),
  FALLBACK_USED                BOOLEAN,
  CURRENT_PACKET_COUNT         NUMBER,
  SECTIONS_PRESENT             VARIANT,
  MISSING_SECTIONS             VARIANT,
  DUPLICATE_CURRENT_KEYS       NUMBER,
  STALE_SECTIONS               VARIANT,
  DATA_GAP_SECTIONS            VARIANT,
  MISSING_METRIC_SECTIONS      VARIANT,
  DEGRADED_SECTIONS            VARIANT,
  INVALID_SECTIONS             VARIANT,
  WARNING_SECTIONS             VARIANT,
  MAX_PACKET_BYTES             NUMBER,
  REQUESTED_SCOPE              VARCHAR(500),
  RESOLVED_SCOPE               VARCHAR(500),
  ADMIN_DETAIL                 VARCHAR(8000),
  SUGGESTED_REMEDIATION        VARCHAR(4000),
  ACTOR_ROLE                   VARCHAR(200),
  APP_VERSION                  VARCHAR(120),
  PERSISTENCE_STATUS           VARCHAR(40),
  PERSISTENCE_ERROR            VARCHAR(4000),
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

ALTER TABLE IF EXISTS OVERWATCH_DECISION_SETUP_HEALTH ADD COLUMN IF NOT EXISTS GLOBAL_STATUS VARCHAR(40);
ALTER TABLE IF EXISTS OVERWATCH_DECISION_SETUP_HEALTH ADD COLUMN IF NOT EXISTS SELECTED_SCOPE_STATUS VARCHAR(40);
ALTER TABLE IF EXISTS OVERWATCH_DECISION_SETUP_HEALTH ADD COLUMN IF NOT EXISTS CURRENT_SECTION_STATUS VARCHAR(40);
ALTER TABLE IF EXISTS OVERWATCH_DECISION_SETUP_HEALTH ADD COLUMN IF NOT EXISTS DEGRADED_SECTIONS VARIANT;
ALTER TABLE IF EXISTS OVERWATCH_DECISION_SETUP_HEALTH ADD COLUMN IF NOT EXISTS INVALID_SECTIONS VARIANT;
ALTER TABLE IF EXISTS OVERWATCH_DECISION_SETUP_HEALTH ADD COLUMN IF NOT EXISTS WARNING_SECTIONS VARIANT;
ALTER TABLE IF EXISTS OVERWATCH_DECISION_SETUP_HEALTH ADD COLUMN IF NOT EXISTS PERSISTENCE_STATUS VARCHAR(40);
ALTER TABLE IF EXISTS OVERWATCH_DECISION_SETUP_HEALTH ADD COLUMN IF NOT EXISTS PERSISTENCE_ERROR VARCHAR(4000);

CREATE TRANSIENT TABLE IF NOT EXISTS MART_EXECUTIVE_DECISION_INBOX (
  PRIORITY                     NUMBER,
  SEVERITY                     VARCHAR(80),
  SECTION_NAME                 VARCHAR(200),
  SIGNAL                       VARCHAR(1000),
  ENTITY                       VARCHAR(500),
  IMPACT_VALUE                 NUMBER(18,2),
  IMPACT_UNIT                  VARCHAR(80),
  OWNER_ROUTE                  VARCHAR(200),
  OWNER_GAP                    BOOLEAN,
  AGE_MINUTES                  NUMBER,
  SLA_STATE                    VARCHAR(80),
  ROUTE_KEY                    VARCHAR(200),
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS MART_QUERY_EVIDENCE_RECENT (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  START_TIME                   TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  QUERY_ID                     VARCHAR(200),
  QUERY_HASH                   VARCHAR(200),
  QUERY_SIGNATURE              VARCHAR(500),
  WAREHOUSE_NAME               VARCHAR(300),
  USER_NAME                    VARCHAR(300),
  ROLE_NAME                    VARCHAR(300),
  DATABASE_NAME                VARCHAR(300),
  TASK_NAME                    VARCHAR(500),
  ROOT_TASK_NAME               VARCHAR(500),
  PROCEDURE_NAME               VARCHAR(500),
  EVIDENCE_KIND                VARCHAR(100),
  SEVERITY                     VARCHAR(80),
  SUMMARY                      VARCHAR(2000),
  DETAILS                      VARIANT,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS MART_ALERT_EVIDENCE_RECENT (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  EVENT_TS                     TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  ALERT_ID                     VARCHAR(200),
  ALERT_KEY                    VARCHAR(500),
  EVENT_ID                     VARCHAR(500),
  ACTION_ID                    VARCHAR(500),
  WAREHOUSE_NAME               VARCHAR(300),
  USER_NAME                    VARCHAR(300),
  ROLE_NAME                    VARCHAR(300),
  DATABASE_NAME                VARCHAR(300),
  EVIDENCE_KIND                VARCHAR(100),
  SEVERITY                     VARCHAR(80),
  SUMMARY                      VARCHAR(2000),
  DETAILS                      VARIANT,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS MART_SECURITY_EVIDENCE_RECENT (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  EVENT_TS                     TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  USER_NAME                    VARCHAR(300),
  LOGIN_NAME                   VARCHAR(300),
  ROLE_NAME                    VARCHAR(300),
  GRANTEE_NAME                 VARCHAR(300),
  GRANT_ID                     VARCHAR(500),
  SHARE_NAME                   VARCHAR(500),
  DATABASE_NAME                VARCHAR(300),
  OBJECT_NAME                  VARCHAR(500),
  EVIDENCE_KIND                VARCHAR(100),
  SEVERITY                     VARCHAR(80),
  SUMMARY                      VARCHAR(2000),
  DETAILS                      VARIANT,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS MART_SECURITY_CREDENTIAL_EXPIRATIONS_CURRENT (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  CREDENTIAL_ID                VARCHAR(300),
  CREDENTIAL_NAME              VARCHAR(500),
  USER_NAME                    VARCHAR(300),
  USER_DISPLAY_NAME            VARCHAR(500),
  USER_CHART_LABEL             VARCHAR(500),
  USER_ADMIN_LABEL             VARCHAR(800),
  USER_EMAIL                   VARCHAR(500),
  TYPE                         VARCHAR(120),
  DOMAIN                       VARCHAR(300),
  STATUS                       VARCHAR(80),
  CREATED_BY                   VARCHAR(300),
  LAST_ALTERED_BY              VARCHAR(300),
  CREATED_ON                   TIMESTAMP_NTZ,
  LAST_USED_ON                 TIMESTAMP_NTZ,
  LAST_ALTERED                 TIMESTAMP_NTZ,
  EXPIRATION_DATE              TIMESTAMP_NTZ,
  DAYS_TO_EXPIRATION           NUMBER,
  EXPIRATION_BUCKET            VARCHAR(80),
  CREDENTIAL_EXPIRING_30D_FLAG BOOLEAN,
  CREDENTIAL_EXPIRING_7D_FLAG  BOOLEAN,
  CREDENTIAL_EXPIRED_FLAG      BOOLEAN,
  CREDENTIAL_EXPIRATION_SEVERITY VARCHAR(40),
  RECOMMENDED_ACTION           VARCHAR(1000),
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS MART_COST_EVIDENCE_RECENT (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  USAGE_DATE                   DATE,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  WAREHOUSE_NAME               VARCHAR(300),
  USER_NAME                    VARCHAR(300),
  ROLE_NAME                    VARCHAR(300),
  DATABASE_NAME                VARCHAR(300),
  SERVICE_CATEGORY             VARCHAR(300),
  SERVICE_TYPE                 VARCHAR(300),
  DEPARTMENT                   VARCHAR(300),
  APPLICATION                  VARCHAR(300),
  ENTITY_NAME                  VARCHAR(500),
  ENTITY_ID                    VARCHAR(500),
  EST_COST                     NUMBER(18,4),
  TOTAL_CREDITS                NUMBER(18,4),
  QUERY_COUNT                  NUMBER,
  EVIDENCE_KIND                VARCHAR(100),
  SUMMARY                      VARCHAR(2000),
  DETAILS                      VARIANT,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS MART_DBA_EVIDENCE_RECENT (
  SNAPSHOT_TS                  TIMESTAMP_NTZ,
  EVENT_TS                     TIMESTAMP_NTZ,
  COMPANY                      VARCHAR(100),
  ENVIRONMENT                  VARCHAR(100),
  QUERY_ID                     VARCHAR(200),
  QUERY_HASH                   VARCHAR(200),
  QUERY_SIGNATURE              VARCHAR(500),
  WAREHOUSE_NAME               VARCHAR(300),
  TASK_NAME                    VARCHAR(500),
  ROOT_TASK_NAME               VARCHAR(500),
  PROCEDURE_NAME               VARCHAR(500),
  DATABASE_NAME                VARCHAR(300),
  EVIDENCE_KIND                VARCHAR(100),
  SEVERITY                     VARCHAR(80),
  SUMMARY                      VARCHAR(2000),
  DETAILS                      VARIANT,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

ALTER TABLE IF EXISTS MART_QUERY_EVIDENCE_RECENT ADD COLUMN IF NOT EXISTS START_TIME TIMESTAMP_NTZ;
ALTER TABLE IF EXISTS MART_QUERY_EVIDENCE_RECENT ADD COLUMN IF NOT EXISTS ROOT_TASK_NAME VARCHAR(500);
ALTER TABLE IF EXISTS MART_ALERT_EVIDENCE_RECENT ADD COLUMN IF NOT EXISTS EVENT_TS TIMESTAMP_NTZ;
ALTER TABLE IF EXISTS MART_SECURITY_EVIDENCE_RECENT ADD COLUMN IF NOT EXISTS EVENT_TS TIMESTAMP_NTZ;
ALTER TABLE IF EXISTS MART_SECURITY_EVIDENCE_RECENT ADD COLUMN IF NOT EXISTS USER_DISPLAY_NAME VARCHAR(500);
ALTER TABLE IF EXISTS MART_SECURITY_EVIDENCE_RECENT ADD COLUMN IF NOT EXISTS USER_CHART_LABEL VARCHAR(500);
ALTER TABLE IF EXISTS MART_SECURITY_EVIDENCE_RECENT ADD COLUMN IF NOT EXISTS CREDENTIAL_ID VARCHAR(300);
ALTER TABLE IF EXISTS MART_SECURITY_EVIDENCE_RECENT ADD COLUMN IF NOT EXISTS CREDENTIAL_NAME VARCHAR(500);
ALTER TABLE IF EXISTS MART_SECURITY_EVIDENCE_RECENT ADD COLUMN IF NOT EXISTS CREDENTIAL_TYPE VARCHAR(120);
ALTER TABLE IF EXISTS MART_SECURITY_EVIDENCE_RECENT ADD COLUMN IF NOT EXISTS CREDENTIAL_STATUS VARCHAR(80);
ALTER TABLE IF EXISTS MART_SECURITY_EVIDENCE_RECENT ADD COLUMN IF NOT EXISTS EXPIRATION_DATE TIMESTAMP_NTZ;
ALTER TABLE IF EXISTS MART_SECURITY_EVIDENCE_RECENT ADD COLUMN IF NOT EXISTS DAYS_TO_EXPIRATION NUMBER;
ALTER TABLE IF EXISTS MART_SECURITY_EVIDENCE_RECENT ADD COLUMN IF NOT EXISTS RECOMMENDED_ACTION VARCHAR(1000);
ALTER TABLE IF EXISTS MART_COST_EVIDENCE_RECENT ADD COLUMN IF NOT EXISTS USAGE_DATE DATE;
ALTER TABLE IF EXISTS MART_DBA_EVIDENCE_RECENT ADD COLUMN IF NOT EXISTS EVENT_TS TIMESTAMP_NTZ;

CREATE TABLE IF NOT EXISTS OVERWATCH_DECISION_REFRESH_AUDIT (
  EVENT_ID                     VARCHAR(64),
  EVENT_TS                     TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  REFRESH_MODE                 VARCHAR(40),
  LOAD_STARTED_AT              TIMESTAMP_NTZ,
  LOAD_FINISHED_AT             TIMESTAMP_NTZ,
  ELAPSED_SECONDS              NUMBER(18,3),
  PARENT_ROWS                  NUMBER,
  METRIC_ROWS                  NUMBER,
  EXCEPTION_ROWS               NUMBER,
  ACTION_ROWS                  NUMBER,
  SOURCE_ROWS                  NUMBER,
  CURRENT_PACKET_ROWS          NUMBER,
  LAST_GOOD_ROWS               NUMBER,
  MAX_PACKET_BYTES             NUMBER,
  AVG_PACKET_BYTES             NUMBER(18,2),
  MAX_SOURCE_ROW_COUNT         NUMBER,
  MAX_TREND_POINTS             NUMBER,
  DATA_GAP_COUNT               NUMBER,
  DEGRADED_COUNT               NUMBER,
  FAILED_SECTION_COUNT         NUMBER,
  FAST_PRUNED_OPTIONAL_BRANCHES BOOLEAN,
  GENERATED_WINDOW_COUNT       NUMBER,
  GENERATED_SCOPE_COUNT        NUMBER,
  ERROR_MESSAGE                VARCHAR(4000),
  ROWS_BY_STAGE                VARIANT,
  BYTES_BY_STAGE               VARIANT,
  LOAD_TS                      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

ALTER TABLE IF EXISTS OVERWATCH_DECISION_REFRESH_AUDIT ADD COLUMN IF NOT EXISTS FAST_PRUNED_OPTIONAL_BRANCHES BOOLEAN;
ALTER TABLE IF EXISTS OVERWATCH_DECISION_REFRESH_AUDIT ADD COLUMN IF NOT EXISTS GENERATED_WINDOW_COUNT NUMBER;
ALTER TABLE IF EXISTS OVERWATCH_DECISION_REFRESH_AUDIT ADD COLUMN IF NOT EXISTS GENERATED_SCOPE_COUNT NUMBER;
ALTER TABLE IF EXISTS OVERWATCH_DECISION_REFRESH_AUDIT ADD COLUMN IF NOT EXISTS ROWS_BY_STAGE VARIANT;
ALTER TABLE IF EXISTS OVERWATCH_DECISION_REFRESH_AUDIT ADD COLUMN IF NOT EXISTS BYTES_BY_STAGE VARIANT;

CREATE TABLE IF NOT EXISTS OVERWATCH_PERFORMANCE_OPTIMIZATION_AUDIT (
  EVENT_ID                     VARCHAR(64) DEFAULT UUID_STRING(),
  EVENT_TS                     TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  SETTING_VALUES               VARIANT,
  OBJECT_NAME                  VARCHAR(256),
  OPERATION                    VARCHAR(80),
  STATUS                       VARCHAR(40),
  ELAPSED_SECONDS              NUMBER(18,3),
  ERROR_MESSAGE                VARCHAR(4000),
  SKIPPED_REASON               VARCHAR(1000)
);

ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS BRIEF_ID VARCHAR(64);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS SOURCE_OBJECTS VARCHAR(2000);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS SOURCE_SNAPSHOT_TS TIMESTAMP_NTZ;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS FRESHNESS_MINUTES NUMBER;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS TARGET_FRESHNESS_MINUTES NUMBER;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS IS_STALE BOOLEAN;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS RESOLVED_COMPANY VARCHAR(100);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS RESOLVED_ENVIRONMENT VARCHAR(100);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS RESOLVED_WINDOW_DAYS NUMBER;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS CONFIDENCE VARCHAR(40);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS REQUIRED_SOURCE_COUNT NUMBER;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS AVAILABLE_SOURCE_COUNT NUMBER;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS MISSING_SOURCE_COUNT NUMBER;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS AVAILABLE_REQUIRED_SOURCE_COUNT NUMBER;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS REQUIRED_MISSING_SOURCE_COUNT NUMBER;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS REQUIRED_STALE_SOURCE_COUNT NUMBER;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS OPTIONAL_SOURCE_COUNT NUMBER;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS AVAILABLE_OPTIONAL_SOURCE_COUNT NUMBER;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS OPTIONAL_MISSING_SOURCE_COUNT NUMBER;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS OPTIONAL_STALE_SOURCE_COUNT NUMBER;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS SOURCE_COVERAGE_PCT NUMBER(8,2);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS DATA_AVAILABILITY_STATE VARCHAR(80);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS STALE_SOURCE_COUNT NUMBER;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS SOURCE_GAP_DETAIL VARCHAR(4000);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS ACCOUNT_BILLED_CREDITS NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS ACCOUNT_BILLED_COST_USD NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS ACCOUNT_USED_CREDITS NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS COMPUTE_CREDITS NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS CLOUD_SERVICES_CREDITS NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS CLOUD_SERVICES_ADJUSTMENT NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS ACCOUNT_CLOUD_SERVICES_ADJUSTMENT NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS WAREHOUSE_CREDITS NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS WAREHOUSE_COST_ESTIMATE_USD NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS WAREHOUSE_COST_USD NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS SERVICE_OTHER_CREDITS NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS SERVICE_OTHER_COST_USD NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS BILLING_BRIDGE_DELTA_CREDITS NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS BILLING_BRIDGE_DELTA_USD NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS BILLING_BRIDGE_STATUS VARCHAR(80);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS CORTEX_AI_CREDITS NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS CORTEX_AI_COST_USD NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS BILLING_RECONCILIATION_STATUS VARCHAR(80);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS BILLING_WINDOW_START DATE;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS BILLING_WINDOW_END DATE;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS BILLING_WINDOW_COMPLETE BOOLEAN;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS BILLING_SOURCE_FRESHNESS_TS TIMESTAMP_NTZ;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS BILLING_LATENCY_NOTE VARCHAR(1000);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS BILLING_RECONCILIATION_WINDOW_START DATE;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS BILLING_RECONCILIATION_WINDOW_END DATE;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS BILLING_RECONCILIATION_FRESHNESS VARCHAR(200);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS SPEND_MOVEMENT_PCT NUMBER(18,4);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS FORECAST_RUN_RATE_USD NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS SECURITY_CREDENTIAL_EXPIRATION_RISK_COUNT NUMBER;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS SECURITY_CREDENTIALS_EXPIRING_30D_COUNT NUMBER;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS SECURITY_CREDENTIALS_EXPIRING_7D_COUNT NUMBER;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS SECURITY_CREDENTIALS_EXPIRED_COUNT NUMBER;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS SECURITY_CREDENTIAL_NEXT_EXPIRATION_TS TIMESTAMP_NTZ;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS SECURITY_CREDENTIAL_NEXT_EXPIRATION_USER VARCHAR(500);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS SECURITY_CREDENTIAL_NEXT_EXPIRATION_TYPE VARCHAR(120);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS SECURITY_CREDENTIAL_EXPIRATION_STATUS VARCHAR(80);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS SECURITY_CREDENTIAL_EXPIRATION_FINDINGS VARIANT;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS SECURITY_CREDENTIAL_SOURCE_CONFIRMED_ZERO BOOLEAN;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS SECURITY_CREDENTIAL_SOURCE_STATUS VARCHAR(80);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS SECURITY_CREDENTIAL_SOURCE_FRESHNESS_TS TIMESTAMP_NTZ;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS SECURITY_CREDENTIAL_SOURCE_LATENCY_NOTE VARCHAR(1000);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_METRIC ADD COLUMN IF NOT EXISTS BRIEF_ID VARCHAR(64);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_METRIC ADD COLUMN IF NOT EXISTS METRIC_NUMERIC_VALUE NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_METRIC ADD COLUMN IF NOT EXISTS METRIC_TEXT_VALUE VARCHAR(500);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_METRIC ADD COLUMN IF NOT EXISTS METRIC_FORMAT VARCHAR(80);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_METRIC ADD COLUMN IF NOT EXISTS TREND_NUMERIC_VALUE NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_METRIC ADD COLUMN IF NOT EXISTS TREND_POINTS VARIANT;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_METRIC ADD COLUMN IF NOT EXISTS TREND_PERIOD VARCHAR(80);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_METRIC ADD COLUMN IF NOT EXISTS TREND_POINT_COUNT NUMBER;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_METRIC ADD COLUMN IF NOT EXISTS TREND_QUALITY VARCHAR(80);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_METRIC ADD COLUMN IF NOT EXISTS ZERO_FILL_POLICY VARCHAR(80);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_METRIC ADD COLUMN IF NOT EXISTS PRIOR_VALUE NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_METRIC ADD COLUMN IF NOT EXISTS DELTA_NUMERIC_VALUE NUMBER(38,6);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_METRIC ADD COLUMN IF NOT EXISTS DELTA_PERCENT NUMBER(18,4);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_METRIC ADD COLUMN IF NOT EXISTS TREND_DIRECTION VARCHAR(40);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_METRIC ADD COLUMN IF NOT EXISTS IS_AVAILABLE BOOLEAN;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_METRIC ADD COLUMN IF NOT EXISTS AVAILABILITY_STATE VARCHAR(80);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_METRIC ADD COLUMN IF NOT EXISTS UNAVAILABLE_REASON VARCHAR(1000);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_METRIC ADD COLUMN IF NOT EXISTS SOURCE_KEY VARCHAR(200);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_METRIC ADD COLUMN IF NOT EXISTS CONFIDENCE VARCHAR(40);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_EXCEPTION ADD COLUMN IF NOT EXISTS BRIEF_ID VARCHAR(64);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_EXCEPTION ADD COLUMN IF NOT EXISTS FINDING_KEY VARCHAR(200);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_EXCEPTION ADD COLUMN IF NOT EXISTS DEDUPE_KEY VARCHAR(500);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_EXCEPTION ADD COLUMN IF NOT EXISTS ENTITY_ID VARCHAR(500);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_EXCEPTION ADD COLUMN IF NOT EXISTS EVIDENCE_ID VARCHAR(500);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_EXCEPTION ADD COLUMN IF NOT EXISTS EVIDENCE_QUERY VARCHAR(16000);
--ALTER TABLE IF EXISTS MART_SECTION_COMMAND_EXCEPTION ADD COLUMN IF NOT EXISTS FIRST_SEEN_TS TIMESTAMP_NTZ;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_EXCEPTION ADD COLUMN IF NOT EXISTS DUE_TS TIMESTAMP_NTZ;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_EXCEPTION ADD COLUMN IF NOT EXISTS OWNER_ID VARCHAR(300);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_EXCEPTION ADD COLUMN IF NOT EXISTS OWNER_NAME VARCHAR(300);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_EXCEPTION ADD COLUMN IF NOT EXISTS PRIORITY_SCORE NUMBER;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_EXCEPTION ADD COLUMN IF NOT EXISTS IMPACT_VALUE NUMBER(18,2);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_EXCEPTION ADD COLUMN IF NOT EXISTS IMPACT_UNIT VARCHAR(80);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_EXCEPTION ADD COLUMN IF NOT EXISTS OWNER_ROUTE VARCHAR(200);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_EXCEPTION ADD COLUMN IF NOT EXISTS OWNER_GAP BOOLEAN;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_EXCEPTION ADD COLUMN IF NOT EXISTS AGE_MINUTES NUMBER;
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_EXCEPTION ADD COLUMN IF NOT EXISTS SLA_STATE VARCHAR(80);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_ACTION ADD COLUMN IF NOT EXISTS BRIEF_ID VARCHAR(64);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_ACTION ADD COLUMN IF NOT EXISTS ACTION_KEY VARCHAR(200);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_ACTION ADD COLUMN IF NOT EXISTS ROUTE_KEY VARCHAR(200);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_ACTION ADD COLUMN IF NOT EXISTS CTA_LABEL VARCHAR(300);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_METRIC ADD COLUMN IF NOT EXISTS DIRECTIONALITY VARCHAR(80);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_EXCEPTION ADD COLUMN IF NOT EXISTS ROUTE_KEY VARCHAR(200);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_EXCEPTION ADD COLUMN IF NOT EXISTS EVIDENCE_SOURCE VARCHAR(500);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_EXCEPTION ADD COLUMN IF NOT EXISTS CONFIDENCE VARCHAR(40);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS PRIMARY_ACTION_KEY VARCHAR(200);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS PRIMARY_ROUTE_KEY VARCHAR(200);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS PRIMARY_ACTION_LABEL VARCHAR(300);
ALTER TABLE IF EXISTS MART_SECTION_COMMAND_BRIEF ADD COLUMN IF NOT EXISTS PRIMARY_ACTION_DETAIL VARCHAR(1200);

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

CREATE TRANSIENT TABLE IF NOT EXISTS MART_EXECUTIVE_COMMAND_CENTER_KPI (
    COMPANY VARCHAR(100),
    ENVIRONMENT VARCHAR(100),
    WINDOW_START TIMESTAMP_NTZ,
    WINDOW_END TIMESTAMP_NTZ,
    WAREHOUSE_SCOPE VARCHAR(255),
    METRIC_KEY VARCHAR(100),
    METRIC_LABEL VARCHAR(255),
    METRIC_VALUE_TEXT VARCHAR(1000),
    METRIC_VALUE_NUMBER FLOAT,
    METRIC_UNIT VARCHAR(50),
    STATUS_TONE VARCHAR(50),
    STATUS_LABEL VARCHAR(255),
    TREND_DIRECTION VARCHAR(50),
    TREND_VALUE_TEXT VARCHAR(255),
    TREND_POINTS VARIANT,
    UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    SOURCE_QUALITY VARCHAR(100),
    SOURCE_NOTE VARCHAR(1000)
);

CREATE TRANSIENT TABLE IF NOT EXISTS MART_EXECUTIVE_COMMAND_CENTER_TIMESERIES (
    COMPANY VARCHAR(100),
    ENVIRONMENT VARCHAR(100),
    WAREHOUSE_NAME VARCHAR(255),
    METRIC_KEY VARCHAR(100),
    POINT_TS TIMESTAMP_NTZ,
    POINT_DATE DATE,
    METRIC_VALUE FLOAT,
    METRIC_VALUE_TEXT VARCHAR(1000),
    STATUS_TONE VARCHAR(50),
    UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS MART_EXECUTIVE_COMMAND_CENTER_WAREHOUSE (
    COMPANY VARCHAR(100),
    ENVIRONMENT VARCHAR(100),
    WINDOW_START TIMESTAMP_NTZ,
    WINDOW_END TIMESTAMP_NTZ,
    WAREHOUSE_NAME VARCHAR(255),
    CREDITS_USED FLOAT,
    ESTIMATED_COST_USD FLOAT,
    PCT_OF_TOTAL FLOAT,
    QUERY_COUNT NUMBER,
    FAILED_QUERY_COUNT NUMBER,
    AVG_DURATION_SEC FLOAT,
    P95_DURATION_SEC FLOAT,
    UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS MART_EXECUTIVE_COMMAND_CENTER_ALERTS (
    COMPANY VARCHAR(100),
    ENVIRONMENT VARCHAR(100),
    SEVERITY VARCHAR(50),
    STATUS VARCHAR(100),
    SIGNAL VARCHAR(255),
    DETAILS VARCHAR(2000),
    OBJECT_NAME VARCHAR(500),
    OWNER VARCHAR(255),
    SLA VARCHAR(100),
    EVENT_TS TIMESTAMP_NTZ,
    ROUTE_KEY VARCHAR(255),
    EVIDENCE_ID VARCHAR(500),
    UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TRANSIENT TABLE IF NOT EXISTS MART_EXECUTIVE_COMMAND_CENTER_CONTEXT (
    COMPANY VARCHAR(100),
    ENVIRONMENT VARCHAR(100),
    WINDOW_START TIMESTAMP_NTZ,
    WINDOW_END TIMESTAMP_NTZ,
    WAREHOUSES_MONITORED VARCHAR(255),
    DATA_SOURCE_STATUS VARCHAR(255),
    FRESHNESS_STATUS VARCHAR(255),
    EVIDENCE_LOAD_STATUS VARCHAR(255),
    LAST_SUCCESSFUL_SNAPSHOT_AT TIMESTAMP_NTZ,
    SOURCE_QUALITY VARCHAR(100),
    UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);
