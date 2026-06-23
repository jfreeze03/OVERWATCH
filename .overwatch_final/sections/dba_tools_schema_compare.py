# sections/dba_tools_schema_compare.py - Schema compare normalization and DDL helpers.

import pandas as pd

from sections.dba_tools_common import _qualified_name, _quote_identifier
from sections.dba_tools_contracts import SCHEMA_COMPARE_OBJECT_COVERAGE
from utils import format_snowflake_error, run_query_or_raise, safe_int, sql_literal

def _schema_compare_show_objects_sql(database: str, schema: str) -> str:
    """Return the Snowflake command that lists every object visible in a schema."""
    return f"SHOW OBJECTS IN SCHEMA {_qualified_name(database, schema)}"


def _schema_compare_columns_sql(database: str, schema: str) -> str:
    """Return account-level column metadata so object compare also catches column drift."""
    database_lit = sql_literal(database, 300)
    schema_lit = sql_literal(schema, 300)
    return f"""
SELECT
    'COLUMN' AS object_type,
    c.table_name || '.' || c.column_name AS object_name,
    c.table_name AS parent_object_name,
    COALESCE(t.table_type, 'TABLE') AS parent_object_type,
    c.ordinal_position AS ordinal_position,
    c.data_type AS data_type,
    c.character_maximum_length AS character_maximum_length,
    c.numeric_precision AS numeric_precision,
    c.numeric_scale AS numeric_scale,
    c.datetime_precision AS datetime_precision,
    c.is_nullable AS is_nullable,
    c.column_default AS column_default,
    c.comment AS comment,
    c.data_type
        || COALESCE('(' || c.character_maximum_length::VARCHAR || ')', '')
        || COALESCE(' precision=' || c.numeric_precision::VARCHAR, '')
        || COALESCE(' scale=' || c.numeric_scale::VARCHAR, '')
        || COALESCE(' datetime_precision=' || c.datetime_precision::VARCHAR, '')
        || ' nullable=' || COALESCE(c.is_nullable, 'UNKNOWN')
        || COALESCE(' default=' || c.column_default, '') AS object_signature
FROM SNOWFLAKE.ACCOUNT_USAGE.COLUMNS c
LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.TABLES t
  ON c.table_id = t.table_id
 AND t.deleted IS NULL
WHERE UPPER(c.table_catalog) = UPPER({database_lit})
  AND UPPER(c.table_schema) = UPPER({schema_lit})
  AND c.deleted IS NULL
""".strip()


def _schema_compare_normalize_kind(value: object) -> str:
    text = str(value or "OBJECT").strip().upper().replace("_", " ")
    aliases = {
        "BASE TABLE": "TABLE",
        "TEMPORARY TABLE": "TABLE",
        "TRANSIENT TABLE": "TABLE",
        "MATERIALIZED VIEW": "MATERIALIZED VIEW",
        "FILE FORMAT": "FILE FORMAT",
        "DYNAMIC TABLE": "DYNAMIC TABLE",
        "EXTERNAL TABLE": "EXTERNAL TABLE",
        "ROW ACCESS POLICY": "ROW ACCESS POLICY",
        "MASKING POLICY": "MASKING POLICY",
    }
    return aliases.get(text, text or "OBJECT")


def _schema_compare_get_ddl_type(object_type: object) -> str:
    kind = _schema_compare_normalize_kind(object_type)
    mapping = {
        "DYNAMIC TABLE": "DYNAMIC_TABLE",
        "EXTERNAL TABLE": "EXTERNAL_TABLE",
        "EVENT TABLE": "TABLE",
        "FILE FORMAT": "FILE_FORMAT",
        "MATERIALIZED VIEW": "MATERIALIZED_VIEW",
        "MASKING POLICY": "MASKING_POLICY",
        "ROW ACCESS POLICY": "ROW_ACCESS_POLICY",
    }
    if kind in mapping:
        return mapping[kind]
    if "PROCEDURE" in kind:
        return "PROCEDURE"
    if "FUNCTION" in kind:
        return "FUNCTION"
    if "VIEW" in kind:
        return "VIEW"
    if "TABLE" in kind:
        return "TABLE"
    if "STAGE" in kind:
        return "STAGE"
    if "SEQUENCE" in kind:
        return "SEQUENCE"
    if "PIPE" in kind:
        return "PIPE"
    if "STREAM" in kind:
        return "STREAM"
    if "TASK" in kind:
        return "TASK"
    if "TAG" in kind:
        return "TAG"
    return kind.replace(" ", "_")


def _first_present_column(df: pd.DataFrame, *candidates: str) -> str | None:
    columns = {str(col).upper(): str(col) for col in df.columns}
    for candidate in candidates:
        if str(candidate).upper() in columns:
            return columns[str(candidate).upper()]
    return None


def _schema_compare_normalize_show_objects(
    df: pd.DataFrame | None,
    *,
    database: str,
    schema: str,
    side: str,
) -> pd.DataFrame:
    """Normalize SHOW OBJECTS output into a compare-ready object inventory."""
    empty_cols = [
        "OBJECT_TYPE", "OBJECT_NAME", "PARENT_OBJECT_NAME", "PARENT_OBJECT_TYPE",
        "OBJECT_SIGNATURE", "OBJECT_DETAIL", "ROW_COUNT", "BYTES", "PRESENT",
        "SOURCE_SIDE", "DATABASE_NAME", "SCHEMA_NAME", "DATA_TYPE",
        "CHARACTER_MAXIMUM_LENGTH", "NUMERIC_PRECISION", "NUMERIC_SCALE",
        "DATETIME_PRECISION", "IS_NULLABLE", "COLUMN_DEFAULT", "COLUMN_COMMENT",
        "ORDINAL_POSITION",
    ]
    if df is None or df.empty:
        return pd.DataFrame(columns=empty_cols)
    frame = df.copy()
    name_col = _first_present_column(frame, "NAME", "OBJECT_NAME")
    kind_col = _first_present_column(frame, "KIND", "OBJECT_TYPE", "TYPE")
    rows_col = _first_present_column(frame, "ROWS", "ROW_COUNT")
    bytes_col = _first_present_column(frame, "BYTES")
    comment_col = _first_present_column(frame, "COMMENT")
    owner_col = _first_present_column(frame, "OWNER")
    created_col = _first_present_column(frame, "CREATED_ON", "CREATED")

    rows = []
    for _, item in frame.iterrows():
        name = str(item.get(name_col, "") if name_col else "").strip()
        if not name:
            continue
        object_type = _schema_compare_normalize_kind(item.get(kind_col, "OBJECT") if kind_col else "OBJECT")
        row_count = safe_int(item.get(rows_col, 0) if rows_col else 0)
        bytes_value = safe_int(item.get(bytes_col, 0) if bytes_col else 0)
        owner = str(item.get(owner_col, "") if owner_col else "").strip()
        comment = str(item.get(comment_col, "") if comment_col else "").strip()
        created = str(item.get(created_col, "") if created_col else "").strip()
        detail_parts = [f"type={object_type}"]
        if owner:
            detail_parts.append(f"owner={owner}")
        if comment:
            detail_parts.append(f"comment={comment}")
        if created:
            detail_parts.append(f"created={created}")
        rows.append({
            "OBJECT_TYPE": object_type,
            "OBJECT_NAME": name,
            "PARENT_OBJECT_NAME": "",
            "PARENT_OBJECT_TYPE": "",
            "OBJECT_SIGNATURE": object_type,
            "OBJECT_DETAIL": "; ".join(detail_parts),
            "ROW_COUNT": row_count,
            "BYTES": bytes_value,
            "PRESENT": True,
            "SOURCE_SIDE": side,
            "DATABASE_NAME": database,
            "SCHEMA_NAME": schema,
            "DATA_TYPE": "",
            "CHARACTER_MAXIMUM_LENGTH": "",
            "NUMERIC_PRECISION": "",
            "NUMERIC_SCALE": "",
            "DATETIME_PRECISION": "",
            "IS_NULLABLE": "",
            "COLUMN_DEFAULT": "",
            "COLUMN_COMMENT": "",
            "ORDINAL_POSITION": "",
        })
    return pd.DataFrame(rows, columns=empty_cols)


def _schema_compare_normalize_columns(
    df: pd.DataFrame | None,
    *,
    database: str,
    schema: str,
    side: str,
) -> pd.DataFrame:
    """Normalize account column metadata into compare-ready child objects."""
    empty_cols = [
        "OBJECT_TYPE", "OBJECT_NAME", "PARENT_OBJECT_NAME", "PARENT_OBJECT_TYPE",
        "OBJECT_SIGNATURE", "OBJECT_DETAIL", "ROW_COUNT", "BYTES", "PRESENT",
        "SOURCE_SIDE", "DATABASE_NAME", "SCHEMA_NAME", "DATA_TYPE",
        "CHARACTER_MAXIMUM_LENGTH", "NUMERIC_PRECISION", "NUMERIC_SCALE",
        "DATETIME_PRECISION", "IS_NULLABLE", "COLUMN_DEFAULT", "COLUMN_COMMENT",
        "ORDINAL_POSITION",
    ]
    if df is None or df.empty:
        return pd.DataFrame(columns=empty_cols)
    frame = df.copy()
    frame.columns = [str(col).upper() for col in frame.columns]
    rows = []
    for _, item in frame.iterrows():
        object_name = str(item.get("OBJECT_NAME", "") or "").strip()
        if not object_name:
            continue
        signature = str(item.get("OBJECT_SIGNATURE", "") or "").strip()
        parent_type = _schema_compare_normalize_kind(item.get("PARENT_OBJECT_TYPE", "TABLE"))
        detail_parts = [
            f"ordinal={item.get('ORDINAL_POSITION', '')}",
            f"type={item.get('DATA_TYPE', '')}",
            f"nullable={item.get('IS_NULLABLE', '')}",
        ]
        if str(item.get("COLUMN_DEFAULT", "") or "").strip():
            detail_parts.append(f"default={item.get('COLUMN_DEFAULT')}")
        if str(item.get("COMMENT", "") or "").strip():
            detail_parts.append(f"comment={item.get('COMMENT')}")
        rows.append({
            "OBJECT_TYPE": "COLUMN",
            "OBJECT_NAME": object_name,
            "PARENT_OBJECT_NAME": str(item.get("PARENT_OBJECT_NAME", "") or "").strip(),
            "PARENT_OBJECT_TYPE": parent_type,
            "OBJECT_SIGNATURE": signature,
            "OBJECT_DETAIL": "; ".join(str(part) for part in detail_parts if str(part).strip()),
            "ROW_COUNT": 0,
            "BYTES": 0,
            "PRESENT": True,
            "SOURCE_SIDE": side,
            "DATABASE_NAME": database,
            "SCHEMA_NAME": schema,
            "DATA_TYPE": str(item.get("DATA_TYPE", "") or "").strip(),
            "CHARACTER_MAXIMUM_LENGTH": item.get("CHARACTER_MAXIMUM_LENGTH", ""),
            "NUMERIC_PRECISION": item.get("NUMERIC_PRECISION", ""),
            "NUMERIC_SCALE": item.get("NUMERIC_SCALE", ""),
            "DATETIME_PRECISION": item.get("DATETIME_PRECISION", ""),
            "IS_NULLABLE": str(item.get("IS_NULLABLE", "") or "").strip(),
            "COLUMN_DEFAULT": str(item.get("COLUMN_DEFAULT", "") or "").strip(),
            "COLUMN_COMMENT": str(item.get("COMMENT", "") or "").strip(),
            "ORDINAL_POSITION": item.get("ORDINAL_POSITION", ""),
        })
    return pd.DataFrame(rows, columns=empty_cols)


def _schema_compare_inventory(
    objects_df: pd.DataFrame | None,
    columns_df: pd.DataFrame | None,
    *,
    database: str,
    schema: str,
    side: str,
) -> pd.DataFrame:
    frames = [
        _schema_compare_normalize_show_objects(objects_df, database=database, schema=schema, side=side),
        _schema_compare_normalize_columns(columns_df, database=database, schema=schema, side=side),
    ]
    inventory = pd.concat(frames, ignore_index=True)
    if inventory.empty:
        return inventory
    inventory["COMPARE_KEY"] = (
        inventory["OBJECT_TYPE"].fillna("").astype(str).str.upper()
        + "::"
        + inventory["OBJECT_NAME"].fillna("").astype(str).str.upper()
    )
    return inventory.drop_duplicates(subset=["COMPARE_KEY"], keep="first")


def _schema_compare_object_fqn(database: str, schema: str, object_name: str) -> str:
    return _qualified_name(database, schema, object_name)


def _schema_compare_numeric_text(value: object) -> str:
    try:
        if value is None or str(value).strip().lower() in {"", "nan", "none", "null"}:
            return ""
        number = float(value)
        return str(int(number)) if number.is_integer() else str(number)
    except Exception:
        return ""


def _schema_compare_column_type(row: pd.Series | dict, suffix: str) -> str:
    data_type = str(row.get(f"DATA_TYPE_{suffix}") or row.get("DATA_TYPE") or "").strip().upper()
    if not data_type:
        return "VARIANT"
    length = _schema_compare_numeric_text(
        row.get(f"CHARACTER_MAXIMUM_LENGTH_{suffix}") or row.get("CHARACTER_MAXIMUM_LENGTH")
    )
    precision = _schema_compare_numeric_text(
        row.get(f"NUMERIC_PRECISION_{suffix}") or row.get("NUMERIC_PRECISION")
    )
    scale = _schema_compare_numeric_text(
        row.get(f"NUMERIC_SCALE_{suffix}") or row.get("NUMERIC_SCALE")
    )
    datetime_precision = _schema_compare_numeric_text(
        row.get(f"DATETIME_PRECISION_{suffix}") or row.get("DATETIME_PRECISION")
    )
    if data_type in {"VARCHAR", "CHAR", "CHARACTER", "STRING", "TEXT", "BINARY"} and length:
        return f"{data_type}({length})"
    if data_type in {"NUMBER", "NUMERIC", "DECIMAL"} and precision and scale:
        return f"{data_type}({precision},{scale})"
    if data_type in {"NUMBER", "NUMERIC", "DECIMAL"} and precision:
        return f"{data_type}({precision})"
    if data_type.startswith("TIMESTAMP") and datetime_precision:
        return f"{data_type}({datetime_precision})"
    if data_type == "TIME" and datetime_precision:
        return f"{data_type}({datetime_precision})"
    return data_type


def _schema_compare_missing_column_ddl(
    row: pd.Series | dict,
    source_db: str,
    source_schema: str,
    target_db: str,
    target_schema: str,
) -> str:
    status = str(row.get("COMPARE_STATUS") or "")
    suffix = "SOURCE" if status == "Only in source" else "TARGET"
    to_db, to_schema = (
        (target_db, target_schema)
        if status == "Only in source"
        else (source_db, source_schema)
    )
    object_name = str(row.get("OBJECT_NAME") or "").strip()
    parent_name = str(row.get("PARENT_OBJECT_NAME") or object_name.split(".", 1)[0]).strip()
    column_name = object_name.split(".", 1)[1].strip() if "." in object_name else object_name
    if not parent_name or not column_name:
        return ""
    table_fqn = _schema_compare_object_fqn(to_db, to_schema, parent_name)
    column_type = _schema_compare_column_type(row, suffix)
    nullable = str(row.get(f"IS_NULLABLE_{suffix}") or row.get("IS_NULLABLE") or "").strip().upper()
    default_value = str(row.get(f"COLUMN_DEFAULT_{suffix}") or row.get("COLUMN_DEFAULT") or "").strip()
    comment = str(row.get(f"COLUMN_COMMENT_{suffix}") or row.get("COLUMN_COMMENT") or "").strip()
    ddl_parts = [f"ALTER TABLE {table_fqn} ADD COLUMN {_quote_identifier(column_name)} {column_type}"]
    if default_value:
        ddl_parts.append(f"DEFAULT {default_value}")
    if nullable == "NO":
        ddl_parts.append("NOT NULL")
    add_column_sql = " ".join(ddl_parts) + ";"
    statements = [
        f"-- {object_name} is missing; review against existing data before executing.",
        add_column_sql,
    ]
    if comment:
        statements.append(
            f"COMMENT ON COLUMN {table_fqn}.{_quote_identifier(column_name)} IS {sql_literal(comment, 1000)};"
        )
    return "\n".join(statements)


def _schema_compare_missing_ddl(
    row: pd.Series | dict,
    source_db: str,
    source_schema: str,
    target_db: str,
    target_schema: str,
) -> str:
    """Build direct DDL where safe, otherwise SQL that retrieves Snowflake DDL."""
    status = str(row.get("COMPARE_STATUS") or "")
    if status not in {"Only in source", "Only in target"}:
        return ""
    object_type = str(row.get("OBJECT_TYPE") or "OBJECT")
    object_name = str(row.get("OBJECT_NAME") or "").strip()
    if not object_name:
        return ""
    from_db, from_schema, to_db, to_schema = (
        (source_db, source_schema, target_db, target_schema)
        if status == "Only in source"
        else (target_db, target_schema, source_db, source_schema)
    )
    direction = (
        f"create in target {to_db}.{to_schema} from source {from_db}.{from_schema}"
        if status == "Only in source"
        else f"create in source {to_db}.{to_schema} from target {from_db}.{from_schema}"
    )
    from_schema_fqn = _qualified_name(from_db, from_schema)
    to_schema_fqn = _qualified_name(to_db, to_schema)

    if object_type == "COLUMN":
        return _schema_compare_missing_column_ddl(
            row,
            source_db=source_db,
            source_schema=source_schema,
            target_db=target_db,
            target_schema=target_schema,
        )

    ddl_type = _schema_compare_get_ddl_type(object_type)
    from_fqn = _schema_compare_object_fqn(from_db, from_schema, object_name)
    return (
        f"-- {object_type} {object_name} is missing; {direction}.\n"
        f"-- Review before executing. GET_DDL preserves source definition; REPLACE retargets fully qualified names.\n"
        f"SELECT REPLACE(GET_DDL({sql_literal(ddl_type)}, {sql_literal(from_fqn, 1000)}, TRUE), "
        f"{sql_literal(from_schema_fqn, 1000)}, {sql_literal(to_schema_fqn, 1000)}) AS DDL_STATEMENT;"
    )


def _schema_compare_fetch_missing_ddl_statements(
    ddl_rows: pd.DataFrame,
    *,
    source_db: str,
    source_schema: str,
    target_db: str,
    target_schema: str,
    max_objects: int = 100,
) -> pd.DataFrame:
    """Fetch actual GET_DDL output for missing objects and keep safe fallbacks."""
    if ddl_rows is None or ddl_rows.empty:
        return ddl_rows
    frame = ddl_rows.copy()
    statements: list[str] = []
    statuses: list[str] = []
    for idx, (_, row) in enumerate(frame.iterrows()):
        fallback = str(row.get("DDL_REVIEW_SQL") or "").strip()
        object_type = str(row.get("OBJECT_TYPE") or "").upper()
        if not fallback:
            statements.append("")
            statuses.append("No review needed")
            continue
        if object_type == "COLUMN":
            statements.append(fallback)
            statuses.append("Generated ADD COLUMN")
            continue
        if idx >= max_objects:
            statements.append(f"-- Definition fetch cap reached. Review manually:\n{fallback}")
            statuses.append("Manual object review required")
            continue
        try:
            result = run_query_or_raise(
                fallback,
                section="Schema Compare",
                ttl_key=f"schema_compare_get_ddl_{idx}_{source_db}_{source_schema}_{target_db}_{target_schema}",
                tier="metadata",
                use_cache=False,
                max_rows=5,
            )
            if result is not None and not result.empty:
                value = str(result.iloc[0].get("DDL_STATEMENT", "") or "").strip()
                if not value:
                    value = str(result.iloc[0, 0] or "").strip()
                if value:
                    statements.append(value.rstrip(";") + ";")
                    statuses.append("Fetched GET_DDL")
                    continue
        except Exception as exc:
            statuses.append(f"Manual object review required: {format_snowflake_error(exc)}")
            statements.append(f"-- Could not fetch GET_DDL automatically. Run manually:\n{fallback}")
            continue
        statements.append(f"-- Could not fetch object definition automatically. Review manually:\n{fallback}")
        statuses.append("Manual object review required")
    frame["DDL_STATEMENT"] = statements
    frame["DDL_STATUS"] = statuses
    return frame


def _schema_compare_ddl_script(
    ddl_rows: pd.DataFrame,
    *,
    source_db: str,
    source_schema: str,
    target_db: str,
    target_schema: str,
) -> str:
    """Build a review-only DDL script for objects missing on one side of the compare."""
    if ddl_rows is None or ddl_rows.empty:
        return ""
    statements = [
        "-- OVERWATCH schema compare missing-object script",
        f"-- Source: {source_db}.{source_schema}",
        f"-- Target: {target_db}.{target_schema}",
        "-- Review dependencies, policies, grants, and environment-specific references before executing.",
    ]
    for _, row in ddl_rows.iterrows():
        statement = str(row.get("DDL_STATEMENT") or row.get("DDL_REVIEW_SQL") or "").strip()
        if not statement:
            continue
        object_type = str(row.get("OBJECT_TYPE") or "OBJECT").strip()
        object_name = str(row.get("OBJECT_NAME") or "").strip()
        compare_status = str(row.get("COMPARE_STATUS") or "").strip()
        if not statement.endswith(";"):
            statement += ";"
        statements.append(
            "\n".join([
                "",
                f"-- {compare_status}: {object_type} {object_name}",
                statement,
            ])
        )
    return "\n".join(statements).strip()


def _schema_compare_coverage_label() -> str:
    return ", ".join(SCHEMA_COMPARE_OBJECT_COVERAGE)


def _schema_compare_persistence_sql(
    compare: pd.DataFrame | None,
    *,
    source_db: str,
    source_schema: str,
    target_db: str,
    target_schema: str,
    owner: str = "",
    severity: str = "MEDIUM",
) -> str:
    rows = compare.copy() if isinstance(compare, pd.DataFrame) else pd.DataFrame()
    if rows.empty:
        return "-- No schema compare rows available to persist."
    if "COMPARE_STATUS" in rows.columns:
        rows = rows[rows["COMPARE_STATUS"].fillna("").astype(str).ne("Matched")]
    if rows.empty:
        return "-- Schema compare matched; no difference rows to persist."
    select_rows = []
    for _, row in rows.iterrows():
        generated_ddl = str(row.get("DDL_STATEMENT") or row.get("DDL_REVIEW_SQL") or "").strip()
        select_rows.append(
            "SELECT "
            f"{sql_literal(source_db, 300)} AS SOURCE_DATABASE, "
            f"{sql_literal(source_schema, 300)} AS SOURCE_SCHEMA, "
            f"{sql_literal(target_db, 300)} AS TARGET_DATABASE, "
            f"{sql_literal(target_schema, 300)} AS TARGET_SCHEMA, "
            f"{sql_literal(row.get('OBJECT_TYPE', ''), 100)} AS OBJECT_TYPE, "
            f"{sql_literal(row.get('OBJECT_NAME', ''), 1000)} AS OBJECT_NAME, "
            f"{sql_literal(row.get('COMPARE_STATUS', ''), 100)} AS DIFF_TYPE, "
            f"{sql_literal(generated_ddl, 16000)} AS GENERATED_DDL, "
            f"{sql_literal(owner, 300)} AS OWNER, "
            f"{sql_literal(str(severity or 'MEDIUM').upper(), 40)} AS SEVERITY"
        )
    select_sql = " UNION ALL\n".join(select_rows)
    return f"""
INSERT INTO OVERWATCH_SCHEMA_DIFF_RESULT (
    SOURCE_DATABASE, SOURCE_SCHEMA, TARGET_DATABASE, TARGET_SCHEMA,
    OBJECT_TYPE, OBJECT_NAME, DIFF_TYPE, GENERATED_DDL, OWNER, SEVERITY
)
{select_sql};
""".strip()


def _build_schema_compare_frame(
    source_inventory: pd.DataFrame,
    target_inventory: pd.DataFrame,
    *,
    source_db: str,
    source_schema: str,
    target_db: str,
    target_schema: str,
) -> pd.DataFrame:
    source = source_inventory.copy() if source_inventory is not None else pd.DataFrame()
    target = target_inventory.copy() if target_inventory is not None else pd.DataFrame()
    for frame in (source, target):
        if "COMPARE_KEY" not in frame.columns:
            frame["COMPARE_KEY"] = pd.Series(dtype=str)
        if not frame.empty:
            frame["COMPARE_KEY"] = (
                frame["OBJECT_TYPE"].fillna("").astype(str).str.upper()
                + "::"
                + frame["OBJECT_NAME"].fillna("").astype(str).str.upper()
            )
    merged = target.merge(source, on="COMPARE_KEY", how="outer", suffixes=("_TARGET", "_SOURCE"))
    if merged.empty:
        return pd.DataFrame(columns=[
            "COMPARE_STATUS", "OBJECT_TYPE", "OBJECT_NAME", "ROW_COUNT_TARGET",
            "ROW_COUNT_SOURCE", "ROW_DIFF", "DDL_REVIEW_SQL",
        ])

    def _coalesce(row, name: str) -> object:
        target_value = row.get(f"{name}_TARGET")
        return target_value if pd.notna(target_value) and str(target_value).strip() else row.get(f"{name}_SOURCE")

    merged["OBJECT_TYPE"] = merged.apply(lambda row: _coalesce(row, "OBJECT_TYPE"), axis=1)
    merged["OBJECT_NAME"] = merged.apply(lambda row: _coalesce(row, "OBJECT_NAME"), axis=1)
    merged["PARENT_OBJECT_NAME"] = merged.apply(lambda row: _coalesce(row, "PARENT_OBJECT_NAME"), axis=1)
    merged["PARENT_OBJECT_TYPE"] = merged.apply(lambda row: _coalesce(row, "PARENT_OBJECT_TYPE"), axis=1)
    target_present = merged.get("PRESENT_TARGET", pd.Series([False] * len(merged), index=merged.index)).fillna(False).astype(bool)
    source_present = merged.get("PRESENT_SOURCE", pd.Series([False] * len(merged), index=merged.index)).fillna(False).astype(bool)
    target_sig = merged.get("OBJECT_SIGNATURE_TARGET", pd.Series([""] * len(merged), index=merged.index)).fillna("").astype(str)
    source_sig = merged.get("OBJECT_SIGNATURE_SOURCE", pd.Series([""] * len(merged), index=merged.index)).fillna("").astype(str)
    merged["COMPARE_STATUS"] = "Matched"
    merged.loc[source_present & ~target_present, "COMPARE_STATUS"] = "Only in source"
    merged.loc[target_present & ~source_present, "COMPARE_STATUS"] = "Only in target"
    merged.loc[source_present & target_present & target_sig.ne(source_sig), "COMPARE_STATUS"] = "Changed"
    merged["ROW_COUNT_TARGET"] = merged.get("ROW_COUNT_TARGET", pd.Series([0] * len(merged), index=merged.index)).fillna(0).astype(float).astype(int)
    merged["ROW_COUNT_SOURCE"] = merged.get("ROW_COUNT_SOURCE", pd.Series([0] * len(merged), index=merged.index)).fillna(0).astype(float).astype(int)
    merged["ROW_DIFF"] = merged["ROW_COUNT_TARGET"] - merged["ROW_COUNT_SOURCE"]
    merged["DDL_REVIEW_SQL"] = merged.apply(
        lambda row: _schema_compare_missing_ddl(
            row,
            source_db=source_db,
            source_schema=source_schema,
            target_db=target_db,
            target_schema=target_schema,
        ),
        axis=1,
    )
    status_rank = {"Only in source": 0, "Only in target": 1, "Changed": 2, "Matched": 9}
    merged["COMPARE_RANK"] = merged["COMPARE_STATUS"].map(status_rank).fillna(5).astype(int)
    columns = [
        "COMPARE_STATUS", "OBJECT_TYPE", "OBJECT_NAME", "PARENT_OBJECT_NAME",
        "PARENT_OBJECT_TYPE", "ROW_COUNT_TARGET", "ROW_COUNT_SOURCE", "ROW_DIFF",
        "OBJECT_DETAIL_TARGET", "OBJECT_DETAIL_SOURCE", "DDL_REVIEW_SQL", "COMPARE_RANK",
    ]
    for column in columns:
        if column not in merged.columns:
            merged[column] = ""
    return merged[columns].sort_values(["COMPARE_RANK", "OBJECT_TYPE", "OBJECT_NAME"]).reset_index(drop=True)
