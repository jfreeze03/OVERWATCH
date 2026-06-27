# sections/dba_tools_setup.py - DBA Tools setup/status checks.

import pandas as pd

from config import ALERT_DB, ALERT_SCHEMA, ALERT_TABLE, ACTION_QUEUE_TABLE
from sections.dba_tools_common import _qualified_name
from utils import safe_identifier, sql_literal

def _table_exists(session, db: str, schema: str, table: str):
    try:
        db_ident = safe_identifier(db)
        # DIRECT_SQL_ADMIN_OK boundary=metadata reason=metadata_probe budget=advanced_diagnostics owner=platform
        row = session.sql(f"""
            SELECT COUNT(*) AS CNT
            FROM {db_ident}.INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = {sql_literal(schema.upper())}
              AND TABLE_NAME = {sql_literal(table.upper())}
        """).collect()[0]
        return int(row["CNT"]) > 0
    except Exception:
        return None


def _task_exists(session, db: str, schema: str, task_name: str):
    try:
        schema_fqn = _qualified_name(db, schema)
        # DIRECT_SQL_ADMIN_OK boundary=metadata reason=metadata_probe budget=advanced_diagnostics owner=platform
        rows = session.sql(
            f"SHOW TASKS LIKE {sql_literal(task_name.upper())} IN SCHEMA {schema_fqn}"
        ).collect()
        return len(rows) > 0
    except Exception:
        return None


def _setup_status_df(session) -> pd.DataFrame:
    checks = [
        ("Annotation Windows", "TABLE", ALERT_DB, ALERT_SCHEMA, "OVERWATCH_ANNOTATIONS"),
        ("Alert History", "TABLE", ALERT_DB, ALERT_SCHEMA, ALERT_TABLE),
        ("Action Queue", "TABLE", ALERT_DB, ALERT_SCHEMA, ACTION_QUEUE_TABLE),
        ("Anomaly Alert Task", "TASK", ALERT_DB, ALERT_SCHEMA, "OVERWATCH_ANOMALY_CHECK"),
    ]
    rows = []
    for feature, object_type, db, schema, object_name in checks:
        exists = (
            _task_exists(session, db, schema, object_name)
            if object_type == "TASK"
            else _table_exists(session, db, schema, object_name)
        )
        if exists is True:
            status = "Present"
        elif exists is False:
            status = "Missing"
        else:
            status = "Unknown"
        rows.append({
            "FEATURE": feature,
            "OBJECT_TYPE": object_type,
            "OBJECT_NAME": f"{db}.{schema}.{object_name}",
            "STATUS": status,
        })
    return pd.DataFrame(rows)
