# sections/dba_tools_data_compare_view.py - Data Compare render branch.

import pandas as pd
import streamlit as st

from sections.dba_tools_common import _select_option
from sections.dba_tools_contracts import DATA_COMPARE_EXECUTION_STAGES
from sections.dba_tools_data_compare import (
    _build_data_compare_plan,
    _data_compare_bucket_sql,
    _data_compare_extract_summary,
    _data_compare_forensic_sql,
    _data_compare_hash_sql,
    _data_compare_outcome,
    _data_compare_parse_identifiers,
    _data_compare_tables_sql,
    _data_compare_where_clause,
    _recon_config_insert_sql,
    _recon_history_sql,
)
from sections.dba_tools_schema_compare import _schema_compare_columns_sql
from sections.shell_helpers import render_setup_health_board, render_shell_snapshot
from utils import (
    company_value_allowed,
    download_csv,
    format_snowflake_error,
    get_active_company,
    get_active_environment,
    load_database_options,
    load_schema_options,
    run_query,
    safe_identifier,
)
from utils.workflows import render_priority_dataframe


def _render_data_compare_command_model() -> None:
    render_shell_snapshot((
        ("Stage 1", "Metadata inventory"),
        ("Stage 2", "COUNT + HASH_AGG"),
        ("Stage 3", "Bucket isolate"),
        ("Stage 4", "Forensic diff"),
    ))
    render_setup_health_board(
        "Data Compare Readiness",
        (
            ("Scope", "Database + schema"),
            ("Detection", "Row count + hash"),
            ("Isolation", "Bucket mismatch"),
            ("Proof", "Keyed or EXCEPT-style diff"),
        ),
        cadence="Operator-triggered bounded scans",
        fallback="Reduce table count/filter for large schemas",
        owner="Release DBA / Data Owner",
    )


def render_data_compare_tool(session, company: str) -> None:
    st.subheader("Data Compare")
    st.caption(
        "Validates row-count sameness and data likeness between matching tables in two schemas. "
        "Quick compare runs COUNT plus explicit-column HASH_AGG; mismatch rows get bucket and forensic diff guidance for DBA review."
    )
    _render_data_compare_command_model()
    refresh_data_meta = st.button("Refresh database and schema choices", key="dc_refresh_metadata")
    scope_key = f"{get_active_company()}_{get_active_environment()}"
    database_cache_key = f"dc_database_options_{scope_key}"
    if refresh_data_meta or database_cache_key not in st.session_state:
        st.session_state[database_cache_key] = load_database_options(
            session,
            company=get_active_company(),
            force_refresh=bool(refresh_data_meta),
        )
    database_options = list(st.session_state.get(database_cache_key) or [])
    if not database_options:
        st.info("No scoped databases were returned by SHOW DATABASES. Enter database names directly or refresh after changing role.")
    src_col, tgt_col = st.columns(2)
    with src_col:
        data_src_db = _select_option(
            "Source database",
            database_options,
            "dc_source_db",
            "DEV_DB",
            allow_current_outside_options=False,
        )
        source_schema_cache_key = f"dc_schema_options_source_{scope_key}_{data_src_db}"
        if refresh_data_meta or source_schema_cache_key not in st.session_state:
            st.session_state[source_schema_cache_key] = load_schema_options(
                session,
                data_src_db,
                company=get_active_company(),
                force_refresh=bool(refresh_data_meta),
            )
        data_src_schema = _select_option(
            "Source schema",
            list(st.session_state.get(source_schema_cache_key) or []),
            "dc_source_schema",
            "PUBLIC",
            allow_current_outside_options=False,
        )
    with tgt_col:
        data_tgt_db = _select_option(
            "Target database",
            database_options,
            "dc_target_db",
            "PROD_DB",
            allow_current_outside_options=False,
        )
        target_schema_cache_key = f"dc_schema_options_target_{scope_key}_{data_tgt_db}"
        if refresh_data_meta or target_schema_cache_key not in st.session_state:
            st.session_state[target_schema_cache_key] = load_schema_options(
                session,
                data_tgt_db,
                company=get_active_company(),
                force_refresh=bool(refresh_data_meta),
            )
        data_tgt_schema = _select_option(
            "Target schema",
            list(st.session_state.get(target_schema_cache_key) or []),
            "dc_target_schema",
            "PUBLIC",
            allow_current_outside_options=False,
        )

    opt1, opt2, opt3 = st.columns([1, 1, 1])
    with opt1:
        data_table_filter = st.text_input(
            "Table contains",
            key="dc_table_filter",
            placeholder="blank = all matching tables",
        )
    with opt2:
        data_max_tables = st.number_input(
            "Max tables to scan",
            min_value=1,
            max_value=100,
            value=25,
            step=5,
            key="dc_max_tables",
            help="COUNT/HASH scans can be expensive. Start small for large schemas.",
        )
    with opt3:
        data_diff_limit = st.number_input(
            "Forensic sample limit",
            min_value=10,
            max_value=1000,
            value=100,
            step=10,
            key="dc_diff_limit",
        )
    excluded_columns_text = st.text_input(
        "Excluded columns",
        key="dc_excluded_columns",
        placeholder="LOAD_TS, UPDATED_AT, AUDIT_ID",
        help="Comma-separated columns excluded from HASH_AGG when timestamps or audit values are expected to differ.",
    )
    key_columns_text = st.text_input(
        "Key columns for forensic diff",
        key="dc_key_columns",
        placeholder="POLICY_ID, CLAIM_ID",
        help="Optional. When supplied, mismatch review uses key-based matching; otherwise it compares both directions.",
    )
    row_filter_text = st.text_input(
        "Row filter",
        key="dc_row_filter",
        placeholder="BUSINESS_DATE >= '2026-01-01'",
        help="Optional SELECT predicate applied to both sides. Leave blank for full-table compare.",
    )
    st.caption(
        "Hashing is a fast detection signal, not a destructive action. For critical mismatches, use the reviewed bucket and forensic diff runbook."
    )
    data_config_sql = _recon_config_insert_sql(
        check_name=f"Data compare {data_src_db}.{data_src_schema} to {data_tgt_db}.{data_tgt_schema}",
        source_db=data_src_db,
        source_schema=data_src_schema,
        target_db=data_tgt_db,
        target_schema=data_tgt_schema,
        table_pattern=f"%{data_table_filter.strip()}%" if str(data_table_filter or "").strip() else "%",
        key_columns=key_columns_text,
        exclude_columns=excluded_columns_text,
        where_clause=row_filter_text,
        hash_bucket_count=128,
        check_mode="COUNT_HASH_BUCKET_FORENSIC",
        severity="MEDIUM",
        owner="Release DBA",
    )
    recon_history_sql = _recon_history_sql(days=30)
    config_cols = st.columns([1.0, 1.0, 1.0, 2.0])
    with config_cols[0]:
        st.caption("Recurring data checks are tracked through the DBA monitoring runbook.")
    with config_cols[1]:
        st.caption("Recurring reconciliation history is managed through the DBA monitoring runbook.")
    with config_cols[2]:
        st.caption("Configuration changes are review-only from this page.")
    with config_cols[3]:
        st.caption("Register recurring reconciliation checks in OVERWATCH_RECON_CONFIG; review prior runs from OVERWATCH_RECON_RUN.")

    if st.button("Run Quick Data Compare", key="dc_run"):
        try:
            source_db_safe = safe_identifier(data_src_db)
            target_db_safe = safe_identifier(data_tgt_db)
            if not (
                company_value_allowed(data_src_db, "database")
                and company_value_allowed(data_tgt_db, "database")
            ):
                st.warning(
                    f"Data Compare is scoped to {get_active_company()}. "
                    "Enter databases that belong to the selected company view."
                )
                st.stop()
            excluded_columns = _data_compare_parse_identifiers(excluded_columns_text)
            key_columns = _data_compare_parse_identifiers(key_columns_text)
            _data_compare_where_clause(row_filter_text)

            source_tables = run_query(
                _data_compare_tables_sql(data_src_db, data_src_schema),
                ttl_key=f"dba_data_compare_tables_source_{company}_{source_db_safe}_{data_src_schema}",
                tier="metadata",
            )
            target_tables = run_query(
                _data_compare_tables_sql(data_tgt_db, data_tgt_schema),
                ttl_key=f"dba_data_compare_tables_target_{company}_{target_db_safe}_{data_tgt_schema}",
                tier="metadata",
            )
            source_columns = run_query(
                _schema_compare_columns_sql(data_src_db, data_src_schema),
                ttl_key=f"dba_data_compare_columns_source_{company}_{source_db_safe}_{data_src_schema}",
                tier="metadata",
            )
            target_columns = run_query(
                _schema_compare_columns_sql(data_tgt_db, data_tgt_schema),
                ttl_key=f"dba_data_compare_columns_target_{company}_{target_db_safe}_{data_tgt_schema}",
                tier="metadata",
            )
            plan = _build_data_compare_plan(
                source_tables,
                target_tables,
                source_columns,
                target_columns,
                excluded_columns=excluded_columns,
                table_filter=data_table_filter,
            )
            runnable = plan[
                plan["COMPARE_STATUS"].isin(["Ready", "Comparable with structure drift"])
                & plan["COMPARABLE_COLUMN_COUNT"].gt(0)
            ].head(int(data_max_tables))
            result_rows = []
            scripts = []
            for _, row in runnable.iterrows():
                table_name = str(row.get("TABLE_NAME") or "").strip()
                columns = [col.strip() for col in str(row.get("COMPARABLE_COLUMNS") or "").split(",") if col.strip()]
                try:
                    source_summary = run_query(
                        _data_compare_hash_sql(data_src_db, data_src_schema, table_name, columns, row_filter_text),
                        ttl_key=f"dba_data_compare_source_hash_{company}_{source_db_safe}_{data_src_schema}_{table_name}",
                        tier="historical",
                        max_rows=5,
                    )
                    target_summary = run_query(
                        _data_compare_hash_sql(data_tgt_db, data_tgt_schema, table_name, columns, row_filter_text),
                        ttl_key=f"dba_data_compare_target_hash_{company}_{target_db_safe}_{data_tgt_schema}_{table_name}",
                        tier="historical",
                        max_rows=5,
                    )
                    source_count, source_hash = _data_compare_extract_summary(source_summary)
                    target_count, target_hash = _data_compare_extract_summary(target_summary)
                    outcome = _data_compare_outcome(source_count, target_count, source_hash, target_hash)
                except Exception as exc:
                    source_count, target_count, source_hash, target_hash = None, None, "", ""
                    outcome = f"Unavailable: {format_snowflake_error(exc)}"
                bucket_sql = _data_compare_bucket_sql(
                    data_src_db,
                    data_src_schema,
                    data_tgt_db,
                    data_tgt_schema,
                    table_name,
                    columns,
                    key_columns=key_columns,
                    row_filter=row_filter_text,
                )
                forensic_sql = _data_compare_forensic_sql(
                    data_src_db,
                    data_src_schema,
                    data_tgt_db,
                    data_tgt_schema,
                    table_name,
                    columns,
                    key_columns=key_columns,
                    row_filter=row_filter_text,
                    limit=int(data_diff_limit),
                )
                script_block = (
                    f"-- {table_name}: {outcome}\n"
                    f"-- Bucket compare narrows the mismatch to hash buckets.\n{bucket_sql}\n\n"
                    f"-- Forensic compare returns sample mismatch rows.\n{forensic_sql}"
                )
                scripts.append(script_block)
                result_rows.append({
                    "TABLE_NAME": table_name,
                    "DATA_COMPARE_STATUS": outcome,
                    "VALIDATION_STAGES": " > ".join(DATA_COMPARE_EXECUTION_STAGES),
                    "STRUCTURE_STATUS": row.get("COMPARE_STATUS", ""),
                    "SOURCE_ACTUAL_ROW_COUNT": source_count,
                    "TARGET_ACTUAL_ROW_COUNT": target_count,
                    "ROW_COUNT_DIFF": (
                        int(target_count or 0) - int(source_count or 0)
                        if source_count is not None and target_count is not None else None
                    ),
                    "SOURCE_DATA_HASH": source_hash,
                    "TARGET_DATA_HASH": target_hash,
                    "COMPARABLE_COLUMN_COUNT": row.get("COMPARABLE_COLUMN_COUNT", 0),
                    "SOURCE_ONLY_COLUMNS": row.get("SOURCE_ONLY_COLUMNS", ""),
                    "TARGET_ONLY_COLUMNS": row.get("TARGET_ONLY_COLUMNS", ""),
                    "TYPE_MISMATCH_COLUMNS": row.get("TYPE_MISMATCH_COLUMNS", ""),
                    "UNSUPPORTED_HASH_COLUMNS": row.get("UNSUPPORTED_HASH_COLUMNS", ""),
                    "BUCKET_COMPARE_SQL": bucket_sql,
                    "FORENSIC_DIFF_SQL": forensic_sql,
                })
            results = pd.DataFrame(result_rows)
            if not plan.empty:
                skipped = plan[~plan["TABLE_NAME"].isin(results["TABLE_NAME"].tolist() if not results.empty else [])]
            else:
                skipped = plan
            mismatches = results[results["DATA_COMPARE_STATUS"].ne("Matched")] if not results.empty else results
            render_shell_snapshot((
                ("Tables Planned", f"{len(plan):,}"),
                ("Tables Scanned", f"{len(results):,}"),
                ("Matched", f"{int(results['DATA_COMPARE_STATUS'].eq('Matched').sum()) if not results.empty else 0:,}"),
                ("Needs Review", f"{len(mismatches):,}" if mismatches is not None else "0"),
            ))
            if not results.empty:
                render_priority_dataframe(
                    results,
                    title="Data compare results",
                    priority_columns=[
                        "TABLE_NAME", "DATA_COMPARE_STATUS", "VALIDATION_STAGES", "STRUCTURE_STATUS",
                        "SOURCE_ACTUAL_ROW_COUNT", "TARGET_ACTUAL_ROW_COUNT", "ROW_COUNT_DIFF",
                        "COMPARABLE_COLUMN_COUNT", "SOURCE_ONLY_COLUMNS", "TARGET_ONLY_COLUMNS",
                        "TYPE_MISMATCH_COLUMNS", "UNSUPPORTED_HASH_COLUMNS",
                    ],
                    sort_by=["DATA_COMPARE_STATUS", "TABLE_NAME"],
                    ascending=[True, True],
                    raw_label="All data compare result rows",
                )
                download_csv(results, "data_compare_results.csv")
                st.caption("Data compare run results are ready for the DBA monitoring log after review.")
            else:
                st.info("No comparable tables were scanned. Check source/target schemas, table filter, or comparable columns.")
            if skipped is not None and not skipped.empty:
                render_priority_dataframe(
                    skipped,
                    title="Tables not scanned",
                    priority_columns=[
                        "TABLE_NAME", "COMPARE_STATUS", "SOURCE_METADATA_ROW_COUNT",
                        "TARGET_METADATA_ROW_COUNT", "SOURCE_ONLY_COLUMNS",
                        "TARGET_ONLY_COLUMNS", "TYPE_MISMATCH_COLUMNS", "UNSUPPORTED_HASH_COLUMNS",
                    ],
                    sort_by=["COMPARE_RANK", "TABLE_NAME"],
                    ascending=[True, True],
                    raw_label="All planned table rows",
                    height=220,
                )
            if scripts:
                st.caption("Bucket and forensic diff steps are available through the DBA monitoring runbook.")
        except Exception as e:
            st.error(f"Data Compare failed: {format_snowflake_error(e)}")
