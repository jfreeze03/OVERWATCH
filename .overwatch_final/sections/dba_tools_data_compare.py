# sections/dba_tools_data_compare.py - Data compare planning and SQL helpers.

import pandas as pd

from sections.dba_tools_common import _qualified_name, _quote_identifier
from sections.dba_tools_schema_compare import _first_present_column, _schema_compare_column_type
from utils import safe_identifier, safe_int, sql_literal

def _data_compare_tables_sql(database: str, schema: str) -> str:
    """Return data-bearing tables from Snowflake account metadata."""
    database_lit = sql_literal(database, 300)
    schema_lit = sql_literal(schema, 300)
    return f"""
SELECT
    table_name,
    table_type,
    row_count AS metadata_row_count,
    bytes AS metadata_bytes,
    created,
    last_altered
FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES
WHERE UPPER(table_catalog) = UPPER({database_lit})
  AND UPPER(table_schema) = UPPER({schema_lit})
  AND deleted IS NULL
  AND (
      UPPER(table_type) IN ('BASE TABLE', 'TRANSIENT TABLE', 'TEMPORARY TABLE', 'EXTERNAL TABLE', 'DYNAMIC TABLE', 'EVENT TABLE')
      OR UPPER(table_type) LIKE '%TABLE%'
      OR UPPER(COALESCE(is_dynamic, '')) = 'YES'
  )
ORDER BY table_name
""".strip()


def _data_compare_where_clause(raw_filter: object) -> str:
    """Return a bounded SELECT-only row filter clause."""
    text = str(raw_filter or "").strip()
    if not text:
        return ""
    upper = f" {text.upper()} "
    blocked = (";", "--", "/*", "*/", " DROP ", " ALTER ", " INSERT ", " UPDATE ", " DELETE ", " MERGE ", " COPY ", " CALL ")
    if any(token in upper for token in blocked):
        raise ValueError("Row filter can only contain one SELECT predicate. Remove comments, semicolons, or write operations.")
    return f"WHERE {text[:1200]}"


def _data_compare_parse_identifiers(value: object) -> list[str]:
    parts = []
    for raw in str(value or "").replace("\n", ",").split(","):
        text = raw.strip().strip('"')
        if not text:
            continue
        parts.append(safe_identifier(text).upper())
    return list(dict.fromkeys(parts))


def _data_compare_normalize_tables(df: pd.DataFrame | None) -> dict[str, dict]:
    if df is None or df.empty:
        return {}
    frame = df.copy()
    frame.columns = [str(col).upper() for col in frame.columns]
    name_col = _first_present_column(frame, "TABLE_NAME", "NAME")
    if not name_col:
        return {}
    result = {}
    for _, row in frame.iterrows():
        name = str(row.get(name_col, "") or "").strip()
        if not name:
            continue
        key = name.upper()
        result[key] = {
            "TABLE_NAME": name,
            "TABLE_TYPE": str(row.get("TABLE_TYPE", "") or "").strip(),
            "METADATA_ROW_COUNT": safe_int(row.get("METADATA_ROW_COUNT", row.get("ROW_COUNT", 0))),
            "METADATA_BYTES": safe_int(row.get("METADATA_BYTES", row.get("BYTES", 0))),
            "LAST_ALTERED": str(row.get("LAST_ALTERED", "") or ""),
        }
    return result


def _data_compare_column_rows(
    df: pd.DataFrame | None,
    table_name: str,
    excluded_columns: list[str] | None = None,
) -> list[dict]:
    if df is None or df.empty:
        return []
    frame = df.copy()
    frame.columns = [str(col).upper() for col in frame.columns]
    excluded = {str(col).upper() for col in (excluded_columns or [])}
    rows = []
    table_key = str(table_name or "").upper()
    for _, row in frame.iterrows():
        parent = str(row.get("PARENT_OBJECT_NAME", row.get("TABLE_NAME", "")) or "").strip()
        if parent.upper() != table_key:
            continue
        object_name = str(row.get("OBJECT_NAME", "") or "").strip()
        col_name = object_name.split(".", 1)[1] if "." in object_name else str(row.get("COLUMN_NAME", "") or "").strip()
        if not col_name or col_name.upper() in excluded:
            continue
        rows.append({
            "COLUMN_NAME": col_name,
            "COLUMN_KEY": col_name.upper(),
            "ORDINAL_POSITION": safe_int(row.get("ORDINAL_POSITION", 0)),
            "DATA_TYPE": str(row.get("DATA_TYPE", "") or "").strip().upper(),
            "COLUMN_TYPE": _schema_compare_column_type(row, ""),
            "IS_NULLABLE": str(row.get("IS_NULLABLE", "") or "").strip().upper(),
            "COLUMN_DEFAULT": str(row.get("COLUMN_DEFAULT", "") or "").strip(),
        })
    return sorted(rows, key=lambda item: (safe_int(item.get("ORDINAL_POSITION", 0)), str(item.get("COLUMN_NAME", ""))))


def _data_compare_column_signature(row: dict) -> str:
    return "|".join([
        str(row.get("COLUMN_TYPE", "")).upper(),
        str(row.get("IS_NULLABLE", "")).upper(),
        str(row.get("COLUMN_DEFAULT", "")),
    ])


def _data_compare_supported_hash_column(row: dict) -> bool:
    return str(row.get("DATA_TYPE", "") or "").upper() not in {"GEOGRAPHY", "GEOMETRY"}


def _build_data_compare_plan(
    source_tables: pd.DataFrame | None,
    target_tables: pd.DataFrame | None,
    source_columns: pd.DataFrame | None,
    target_columns: pd.DataFrame | None,
    *,
    excluded_columns: list[str] | None = None,
    table_filter: str = "",
) -> pd.DataFrame:
    source_table_map = _data_compare_normalize_tables(source_tables)
    target_table_map = _data_compare_normalize_tables(target_tables)
    filter_text = str(table_filter or "").strip().upper()
    table_names = sorted(set(source_table_map) | set(target_table_map))
    if filter_text:
        table_names = [name for name in table_names if filter_text in name]

    rows = []
    for table_key in table_names:
        source_meta = source_table_map.get(table_key, {})
        target_meta = target_table_map.get(table_key, {})
        table_name = str(source_meta.get("TABLE_NAME") or target_meta.get("TABLE_NAME") or table_key)
        source_present = bool(source_meta)
        target_present = bool(target_meta)
        source_cols = _data_compare_column_rows(source_columns, table_name, excluded_columns)
        target_cols = _data_compare_column_rows(target_columns, table_name, excluded_columns)
        source_col_map = {row["COLUMN_KEY"]: row for row in source_cols}
        target_col_map = {row["COLUMN_KEY"]: row for row in target_cols}
        source_col_keys = [row["COLUMN_KEY"] for row in source_cols]
        target_col_keys = [row["COLUMN_KEY"] for row in target_cols]
        common_keys = [key for key in source_col_keys if key in target_col_map]
        source_only = [source_col_map[key]["COLUMN_NAME"] for key in source_col_keys if key not in target_col_map]
        target_only = [target_col_map[key]["COLUMN_NAME"] for key in target_col_keys if key not in source_col_map]
        type_mismatch = [
            source_col_map[key]["COLUMN_NAME"]
            for key in common_keys
            if _data_compare_column_signature(source_col_map[key]) != _data_compare_column_signature(target_col_map[key])
        ]
        unsupported = [
            source_col_map[key]["COLUMN_NAME"]
            for key in common_keys
            if not _data_compare_supported_hash_column(source_col_map[key])
            or not _data_compare_supported_hash_column(target_col_map[key])
        ]
        comparable_keys = [
            key for key in common_keys
            if key not in {col.upper() for col in type_mismatch}
            and key not in {col.upper() for col in unsupported}
        ]
        comparable_columns = [source_col_map[key]["COLUMN_NAME"] for key in comparable_keys]
        if not source_present:
            status = "Missing in source"
        elif not target_present:
            status = "Missing in target"
        elif not comparable_columns:
            status = "No comparable columns"
        elif source_only or target_only or type_mismatch or unsupported:
            status = "Comparable with structure drift"
        else:
            status = "Ready"
        rows.append({
            "TABLE_NAME": table_name,
            "COMPARE_STATUS": status,
            "SOURCE_PRESENT": source_present,
            "TARGET_PRESENT": target_present,
            "SOURCE_METADATA_ROW_COUNT": safe_int(source_meta.get("METADATA_ROW_COUNT", 0)),
            "TARGET_METADATA_ROW_COUNT": safe_int(target_meta.get("METADATA_ROW_COUNT", 0)),
            "SOURCE_COLUMNS": len(source_cols),
            "TARGET_COLUMNS": len(target_cols),
            "COMPARABLE_COLUMN_COUNT": len(comparable_columns),
            "COMPARABLE_COLUMNS": ", ".join(comparable_columns),
            "SOURCE_ONLY_COLUMNS": ", ".join(source_only),
            "TARGET_ONLY_COLUMNS": ", ".join(target_only),
            "TYPE_MISMATCH_COLUMNS": ", ".join(type_mismatch),
            "UNSUPPORTED_HASH_COLUMNS": ", ".join(unsupported),
        })
    rank = {
        "Ready": 0,
        "Comparable with structure drift": 1,
        "No comparable columns": 2,
        "Missing in target": 3,
        "Missing in source": 4,
    }
    plan = pd.DataFrame(rows)
    if plan.empty:
        return pd.DataFrame(columns=[
            "TABLE_NAME", "COMPARE_STATUS", "COMPARABLE_COLUMNS", "SOURCE_METADATA_ROW_COUNT",
            "TARGET_METADATA_ROW_COUNT", "COMPARE_RANK",
        ])
    plan["COMPARE_RANK"] = plan["COMPARE_STATUS"].map(rank).fillna(9).astype(int)
    return plan.sort_values(["COMPARE_RANK", "TABLE_NAME"]).reset_index(drop=True)


def _data_compare_hash_sql(
    database: str,
    schema: str,
    table: str,
    columns: list[str],
    row_filter: str = "",
) -> str:
    table_fqn = _qualified_name(database, schema, table)
    where_clause = _data_compare_where_clause(row_filter)
    if columns:
        column_expr = ", ".join(_quote_identifier(col) for col in columns)
        hash_expr = f"HASH_AGG({column_expr})"
    else:
        hash_expr = "NULL"
    return f"""
SELECT
    COUNT(*) AS actual_row_count,
    {hash_expr} AS data_hash
FROM {table_fqn}
{where_clause}
""".strip()


def _data_compare_bucket_sql(
    source_db: str,
    source_schema: str,
    target_db: str,
    target_schema: str,
    table: str,
    columns: list[str],
    key_columns: list[str] | None = None,
    row_filter: str = "",
    buckets: int = 128,
) -> str:
    hash_columns = list(key_columns or columns)
    if not hash_columns or not columns:
        return f"-- Bucket compare for {table} needs comparable columns."
    bucket_expr = f"MOD(ABS(HASH({', '.join(_quote_identifier(col) for col in hash_columns)})), {int(buckets)})"
    data_expr = ", ".join(_quote_identifier(col) for col in columns)
    where_clause = _data_compare_where_clause(row_filter)
    source_fqn = _qualified_name(source_db, source_schema, table)
    target_fqn = _qualified_name(target_db, target_schema, table)
    return f"""
WITH source_bucket AS (
    SELECT {bucket_expr} AS bucket_id, COUNT(*) AS source_rows, HASH_AGG({data_expr}) AS source_hash
    FROM {source_fqn}
    {where_clause}
    GROUP BY 1
),
target_bucket AS (
    SELECT {bucket_expr} AS bucket_id, COUNT(*) AS target_rows, HASH_AGG({data_expr}) AS target_hash
    FROM {target_fqn}
    {where_clause}
    GROUP BY 1
)
SELECT
    COALESCE(s.bucket_id, t.bucket_id) AS bucket_id,
    COALESCE(s.source_rows, 0) AS source_rows,
    COALESCE(t.target_rows, 0) AS target_rows,
    s.source_hash,
    t.target_hash
FROM source_bucket s
FULL OUTER JOIN target_bucket t USING (bucket_id)
WHERE COALESCE(s.source_rows, 0) <> COALESCE(t.target_rows, 0)
   OR COALESCE(s.source_hash, 0) <> COALESCE(t.target_hash, 0)
ORDER BY bucket_id;
""".strip()


def _data_compare_forensic_sql(
    source_db: str,
    source_schema: str,
    target_db: str,
    target_schema: str,
    table: str,
    columns: list[str],
    key_columns: list[str] | None = None,
    row_filter: str = "",
    limit: int = 100,
) -> str:
    if not columns:
        return f"-- Forensic compare for {table} needs comparable columns."
    source_fqn = _qualified_name(source_db, source_schema, table)
    target_fqn = _qualified_name(target_db, target_schema, table)
    where_clause = _data_compare_where_clause(row_filter)
    select_cols = ", ".join(_quote_identifier(col) for col in columns)
    safe_limit = max(1, min(int(limit or 100), 1000))
    keys = list(key_columns or [])
    if keys:
        key_select = ", ".join(_quote_identifier(col) for col in keys)
        hash_select = ", ".join(_quote_identifier(col) for col in columns)
        join_clause = " AND ".join(
            f"s.{_quote_identifier(col)} IS NOT DISTINCT FROM t.{_quote_identifier(col)}"
            for col in keys
        )
        key_projection = ", ".join(f"COALESCE(s.{_quote_identifier(col)}, t.{_quote_identifier(col)}) AS {_quote_identifier(col)}" for col in keys)
        return f"""
WITH source_rows AS (
    SELECT {key_select}, HASH({hash_select}) AS source_row_hash
    FROM {source_fqn}
    {where_clause}
),
target_rows AS (
    SELECT {key_select}, HASH({hash_select}) AS target_row_hash
    FROM {target_fqn}
    {where_clause}
)
SELECT
    CASE
        WHEN s.source_row_hash IS NULL THEN 'ONLY_IN_TARGET'
        WHEN t.target_row_hash IS NULL THEN 'ONLY_IN_SOURCE'
        ELSE 'ROW_HASH_MISMATCH'
    END AS diff_type,
    {key_projection},
    s.source_row_hash,
    t.target_row_hash
FROM source_rows s
FULL OUTER JOIN target_rows t
  ON {join_clause}
WHERE s.source_row_hash IS NULL
   OR t.target_row_hash IS NULL
   OR s.source_row_hash <> t.target_row_hash
LIMIT {safe_limit};
""".strip()
    join_clause = " AND ".join(
        f"s.{_quote_identifier(col)} IS NOT DISTINCT FROM t.{_quote_identifier(col)}"
        for col in columns
    )
    projected_cols = ", ".join(
        f"COALESCE(s.{_quote_identifier(col)}, t.{_quote_identifier(col)}) AS {_quote_identifier(col)}"
        for col in columns
    )
    return f"""
WITH source_counts AS (
    SELECT {select_cols}, COUNT(*) AS source_duplicate_count
    FROM {source_fqn}
    {where_clause}
    GROUP BY {select_cols}
),
target_counts AS (
    SELECT {select_cols}, COUNT(*) AS target_duplicate_count
    FROM {target_fqn}
    {where_clause}
    GROUP BY {select_cols}
)
SELECT
    CASE
        WHEN t.target_duplicate_count IS NULL THEN 'ONLY_IN_SOURCE'
        WHEN s.source_duplicate_count IS NULL THEN 'ONLY_IN_TARGET'
        ELSE 'DUPLICATE_COUNT_MISMATCH'
    END AS diff_type,
    {projected_cols},
    COALESCE(s.source_duplicate_count, 0) AS source_duplicate_count,
    COALESCE(t.target_duplicate_count, 0) AS target_duplicate_count
FROM source_counts s
FULL OUTER JOIN target_counts t
  ON {join_clause}
WHERE COALESCE(s.source_duplicate_count, 0) <> COALESCE(t.target_duplicate_count, 0)
LIMIT {safe_limit};
""".strip()


def _data_compare_extract_summary(df: pd.DataFrame | None) -> tuple[int | None, str]:
    if df is None or df.empty:
        return None, ""
    frame = df.copy()
    frame.columns = [str(col).upper() for col in frame.columns]
    row = frame.iloc[0]
    return safe_int(row.get("ACTUAL_ROW_COUNT", 0)), str(row.get("DATA_HASH", "") or "")


def _data_compare_outcome(source_count: int | None, target_count: int | None, source_hash: str, target_hash: str) -> str:
    if source_count is None or target_count is None:
        return "Unavailable"
    if source_count != target_count:
        return "Count mismatch"
    if str(source_hash) != str(target_hash):
        return "Hash mismatch"
    return "Matched"


def _sql_number_expr(value: object) -> str:
    if value is None:
        return "NULL"
    try:
        if pd.isna(value):
            return "NULL"
    except Exception:
        pass
    text = str(value).strip()
    if not text:
        return "NULL"
    try:
        number = float(text)
    except ValueError:
        return "NULL"
    if number.is_integer():
        return str(int(number))
    return str(number)


def _data_compare_persistence_sql(
    results: pd.DataFrame | None,
    *,
    check_id: int | str | None = None,
    recommended_action: str = "Review mismatches and run reviewed forensic diff before release cutover.",
) -> str:
    rows = results.copy() if isinstance(results, pd.DataFrame) else pd.DataFrame()
    if rows.empty:
        return "-- No data compare result rows available to persist."
    select_rows = []
    check_expr = "NULL" if check_id in (None, "") else f"TRY_TO_NUMBER({sql_literal(str(check_id), 100)})"
    for _, row in rows.iterrows():
        status = str(row.get("DATA_COMPARE_STATUS") or "Unavailable").strip()
        table_name = str(row.get("TABLE_NAME") or "Unknown table").strip()
        mismatch = 0 if status == "Matched" else 1
        table_action = f"{recommended_action} Table: {table_name}. Status: {status}."
        select_rows.append(
            "SELECT "
            f"{check_expr} AS CHECK_ID, "
            f"{sql_literal(status, 40)} AS RUN_STATUS, "
            f"{_sql_number_expr(row.get('SOURCE_ACTUAL_ROW_COUNT'))} AS SOURCE_ROW_COUNT, "
            f"{_sql_number_expr(row.get('TARGET_ACTUAL_ROW_COUNT'))} AS TARGET_ROW_COUNT, "
            f"{sql_literal(row.get('SOURCE_DATA_HASH', ''), 200)} AS SOURCE_HASH, "
            f"{sql_literal(row.get('TARGET_DATA_HASH', ''), 200)} AS TARGET_HASH, "
            f"{mismatch} AS MISMATCH_COUNT, "
            f"{sql_literal(row.get('FORENSIC_DIFF_SQL', ''), 16000)} AS SAMPLE_DIFF_SQL, "
            f"{sql_literal(table_action, 2000)} AS RECOMMENDED_ACTION"
        )
    select_sql = " UNION ALL\n".join(select_rows)
    return f"""
INSERT INTO OVERWATCH_RECON_RUN (
    CHECK_ID, RUN_STATUS, SOURCE_ROW_COUNT, TARGET_ROW_COUNT,
    SOURCE_HASH, TARGET_HASH, MISMATCH_COUNT, SAMPLE_DIFF_SQL, RECOMMENDED_ACTION
)
{select_sql};
""".strip()


def _recon_config_insert_sql(
    *,
    check_name: str,
    source_db: str,
    source_schema: str,
    target_db: str,
    target_schema: str,
    table_pattern: str = "%",
    key_columns: str = "",
    exclude_columns: str = "",
    where_clause: str = "",
    hash_bucket_count: int = 64,
    check_mode: str = "COUNT_AND_HASH",
    severity: str = "MEDIUM",
    owner: str = "Release DBA",
    enabled: bool = True,
) -> str:
    enabled_sql = "TRUE" if enabled else "FALSE"
    return f"""
INSERT INTO OVERWATCH_RECON_CONFIG (
    CHECK_NAME, SOURCE_DATABASE, SOURCE_SCHEMA, TARGET_DATABASE, TARGET_SCHEMA,
    TABLE_PATTERN, KEY_COLUMNS, EXCLUDE_COLUMNS, WHERE_CLAUSE, HASH_BUCKET_COUNT,
    CHECK_MODE, SEVERITY, OWNER, ENABLED
)
SELECT
    {sql_literal(check_name, 300)} AS CHECK_NAME,
    {sql_literal(source_db, 300)} AS SOURCE_DATABASE,
    {sql_literal(source_schema, 300)} AS SOURCE_SCHEMA,
    {sql_literal(target_db, 300)} AS TARGET_DATABASE,
    {sql_literal(target_schema, 300)} AS TARGET_SCHEMA,
    {sql_literal(table_pattern or '%', 300)} AS TABLE_PATTERN,
    {sql_literal(key_columns, 2000)} AS KEY_COLUMNS,
    {sql_literal(exclude_columns, 2000)} AS EXCLUDE_COLUMNS,
    {sql_literal(where_clause, 4000)} AS WHERE_CLAUSE,
    {max(1, int(hash_bucket_count or 64))} AS HASH_BUCKET_COUNT,
    {sql_literal(str(check_mode or 'COUNT_AND_HASH').upper(), 50)} AS CHECK_MODE,
    {sql_literal(str(severity or 'MEDIUM').upper(), 40)} AS SEVERITY,
    {sql_literal(owner, 300)} AS OWNER,
    {enabled_sql} AS ENABLED;
""".strip()


def _recon_history_sql(days: int = 30) -> str:
    days = max(1, int(days or 30))
    return f"""
SELECT
    r.RUN_ID,
    r.RUN_TS,
    c.CHECK_NAME,
    c.SOURCE_DATABASE,
    c.SOURCE_SCHEMA,
    c.TARGET_DATABASE,
    c.TARGET_SCHEMA,
    c.TABLE_PATTERN,
    c.CHECK_MODE,
    c.OWNER,
    c.SEVERITY,
    r.RUN_STATUS,
    r.SOURCE_ROW_COUNT,
    r.TARGET_ROW_COUNT,
    r.MISMATCH_COUNT,
    r.RECOMMENDED_ACTION
FROM OVERWATCH_RECON_RUN r
LEFT JOIN OVERWATCH_RECON_CONFIG c
  ON r.CHECK_ID = c.CHECK_ID
WHERE r.RUN_TS >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
ORDER BY r.RUN_TS DESC, r.RUN_ID DESC;
""".strip()
