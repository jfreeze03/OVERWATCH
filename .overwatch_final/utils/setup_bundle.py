# utils/setup_bundle.py - one-place setup DDL for OVERWATCH persistent features
from config import ETL_AUDIT_DB, ETL_AUDIT_SCHEMA
from .action_queue import build_action_queue_ddl
from .alerts import build_alert_task_sql, build_annotation_ddl
from .bookmarks import build_bookmark_ddl
from .logging import build_usage_log_ddl
from .owner_directory import build_owner_directory_ddl
from .query import safe_identifier
from .workload_audit import build_workload_recovery_audit_ddl


def build_snowflake_value_ddl() -> str:
    value_table = (
        f"{safe_identifier(ETL_AUDIT_DB)}."
        f"{safe_identifier(ETL_AUDIT_SCHEMA)}."
        f"{safe_identifier('OVERWATCH_ROI_LOG')}"
    )
    return f"""-- OVERWATCH Snowflake Value Log
CREATE TABLE IF NOT EXISTS {value_table} (
    ROI_ID           NUMBER AUTOINCREMENT PRIMARY KEY,
    LOGGED_DATE      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    LOGGED_BY        VARCHAR(200),
    CATEGORY         VARCHAR(100),
    DESCRIPTION      VARCHAR(1000),
    ENTITY           VARCHAR(500),
    BASELINE_CREDITS FLOAT,
    CURRENT_CREDITS  FLOAT,
    SAVINGS_CREDITS  FLOAT,
    SAVINGS_MONTHLY  FLOAT,
    VERIFIED         BOOLEAN DEFAULT FALSE,
    COMPANY          VARCHAR(50),
    NOTES            VARCHAR(2000)
);

ALTER TABLE {value_table} ADD COLUMN IF NOT EXISTS COMPANY VARCHAR(50);"""


def build_overwatch_setup_bundle() -> str:
    return "\n\n".join([
        "-- OVERWATCH Persistent Feature Setup Bundle",
        build_bookmark_ddl(),
        build_annotation_ddl(),
        build_owner_directory_ddl(),
        build_action_queue_ddl(),
        build_workload_recovery_audit_ddl(),
        build_snowflake_value_ddl(),
        build_usage_log_ddl(),
        "-- Optional: scheduled alert task",
        build_alert_task_sql(),
    ])
