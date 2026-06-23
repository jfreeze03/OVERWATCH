# sections/dba_tools_schema_compare_view.py - Schema Compare render branch.

import streamlit as st

from sections.dba_tools_common import _select_option
from sections.dba_tools_data_compare import _recon_config_insert_sql
from sections.dba_tools_schema_compare import (
    _build_schema_compare_frame,
    _schema_compare_columns_sql,
    _schema_compare_coverage_label,
    _schema_compare_ddl_script,
    _schema_compare_fetch_missing_ddl_statements,
    _schema_compare_inventory,
    _schema_compare_persistence_sql,
    _schema_compare_show_objects_sql,
)
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


def _render_schema_compare_command_model() -> None:
    render_shell_snapshot((
        ("Inventory", "SHOW OBJECTS"),
        ("Columns", "Snowflake account metadata"),
        ("Coverage", "All visible schema objects"),
        ("Missing Objects", "Review queue"),
    ))
    render_setup_health_board(
        "Schema Compare Readiness",
        (
            ("Object scope", "All visible schema objects"),
            ("Column drift", "Column signature compare"),
            ("Missing objects", "DBA review"),
            ("Coverage list", _schema_compare_coverage_label()),
        ),
        cadence="Operator-triggered metadata read",
        fallback="DBA review when metadata access is limited",
        owner="Release DBA",
    )


def render_schema_compare_tool(session, company: str) -> None:
    st.subheader("Schema Compare")
    st.caption(
        "Compares every visible schema object from SHOW OBJECTS, plus table and column inventory from "
        "Snowflake account metadata. Missing objects include a DBA-reviewed create script."
    )
    _render_schema_compare_command_model()
    refresh_schema_meta = st.button("Refresh database and schema choices", key="sc_refresh_metadata")
    scope_key = f"{get_active_company()}_{get_active_environment()}"
    database_cache_key = f"sc_database_options_{scope_key}"
    if refresh_schema_meta or database_cache_key not in st.session_state:
        st.session_state[database_cache_key] = load_database_options(
            session,
            company=get_active_company(),
            force_refresh=bool(refresh_schema_meta),
        )
    database_options = list(st.session_state.get(database_cache_key) or [])
    if not database_options:
        st.info("No scoped databases were returned by SHOW DATABASES. Enter database names directly or refresh after changing role.")
    c1, c2 = st.columns(2)
    with c1:
        dev_db = _select_option(
            "Source database",
            database_options,
            "sc_dev",
            "DEV_DB",
            allow_current_outside_options=False,
        )
        source_schema_cache_key = f"sc_schema_options_source_{scope_key}_{dev_db}"
        if refresh_schema_meta or source_schema_cache_key not in st.session_state:
            st.session_state[source_schema_cache_key] = load_schema_options(
                session,
                dev_db,
                company=get_active_company(),
                force_refresh=bool(refresh_schema_meta),
            )
        dev_sch = _select_option(
            "Source schema",
            list(st.session_state.get(source_schema_cache_key) or []),
            "sc_devsch",
            "PUBLIC",
            allow_current_outside_options=False,
        )
    with c2:
        prod_db = _select_option(
            "Target database",
            database_options,
            "sc_prod",
            "PROD_DB",
            allow_current_outside_options=False,
        )
        target_schema_cache_key = f"sc_schema_options_target_{scope_key}_{prod_db}"
        if refresh_schema_meta or target_schema_cache_key not in st.session_state:
            st.session_state[target_schema_cache_key] = load_schema_options(
                session,
                prod_db,
                company=get_active_company(),
                force_refresh=bool(refresh_schema_meta),
            )
        prod_sch = _select_option(
            "Target schema",
            list(st.session_state.get(target_schema_cache_key) or []),
            "sc_prodsch",
            "PUBLIC",
            allow_current_outside_options=False,
        )
    schema_config_sql = _recon_config_insert_sql(
        check_name=f"Schema compare {dev_db}.{dev_sch} to {prod_db}.{prod_sch}",
        source_db=dev_db,
        source_schema=dev_sch,
        target_db=prod_db,
        target_schema=prod_sch,
        table_pattern="%",
        check_mode="SCHEMA_OBJECT_DDL",
        severity="MEDIUM",
        owner="Release DBA",
    )
    config_cols = st.columns([1.0, 1.0, 3.0])
    with config_cols[0]:
        st.caption("Recurring schema-pair checks are tracked through the DBA monitoring runbook.")
    with config_cols[1]:
        st.caption("Keep schema comparison telemetry with operational status when promotion depends on it.")
    with config_cols[2]:
        st.caption("Use the review table below for missing objects and drift decisions.")
    if st.button("Compare Schemas", key="sc_run"):
        try:
            dev_db_safe = safe_identifier(dev_db)
            prod_db_safe = safe_identifier(prod_db)
            if not (
                company_value_allowed(dev_db, "database")
                and company_value_allowed(prod_db, "database")
            ):
                st.warning(
                    f"Schema Compare is scoped to {get_active_company()}. "
                    "Enter databases that belong to the selected company view."
                )
                st.stop()
            source_objects = run_query(
                _schema_compare_show_objects_sql(dev_db, dev_sch),
                ttl_key=f"dba_schema_objects_source_{company}_{dev_db_safe}_{dev_sch}",
                tier="metadata",
            )
            target_objects = run_query(
                _schema_compare_show_objects_sql(prod_db, prod_sch),
                ttl_key=f"dba_schema_objects_target_{company}_{prod_db_safe}_{prod_sch}",
                tier="metadata",
            )
            source_columns = run_query(
                _schema_compare_columns_sql(dev_db, dev_sch),
                ttl_key=f"dba_schema_columns_source_{company}_{dev_db_safe}_{dev_sch}",
                tier="metadata",
            )
            target_columns = run_query(
                _schema_compare_columns_sql(prod_db, prod_sch),
                ttl_key=f"dba_schema_columns_target_{company}_{prod_db_safe}_{prod_sch}",
                tier="metadata",
            )
            source_inventory = _schema_compare_inventory(
                source_objects,
                source_columns,
                database=dev_db,
                schema=dev_sch,
                side="SOURCE",
            )
            target_inventory = _schema_compare_inventory(
                target_objects,
                target_columns,
                database=prod_db,
                schema=prod_sch,
                side="TARGET",
            )
            df_cmp = _build_schema_compare_frame(
                source_inventory,
                target_inventory,
                source_db=dev_db,
                source_schema=dev_sch,
                target_db=prod_db,
                target_schema=prod_sch,
            )
            missing_or_changed = df_cmp[df_cmp["COMPARE_STATUS"].ne("Matched")] if not df_cmp.empty else df_cmp
            ddl_rows = df_cmp[df_cmp["DDL_REVIEW_SQL"].fillna("").astype(str).str.strip().ne("")] if not df_cmp.empty else df_cmp
            ddl_statement_rows = _schema_compare_fetch_missing_ddl_statements(
                ddl_rows,
                source_db=dev_db,
                source_schema=dev_sch,
                target_db=prod_db,
                target_schema=prod_sch,
            ) if ddl_rows is not None and not ddl_rows.empty else ddl_rows
            render_shell_snapshot((
                ("Compared Objects", f"{len(df_cmp):,}"),
                ("Missing", f"{int(df_cmp['COMPARE_STATUS'].isin(['Only in source', 'Only in target']).sum()) if not df_cmp.empty else 0:,}"),
                ("Changed", f"{int(df_cmp['COMPARE_STATUS'].eq('Changed').sum()) if not df_cmp.empty else 0:,}"),
                ("Review Items", f"{len(ddl_statement_rows):,}" if ddl_statement_rows is not None else "0"),
            ))
            render_priority_dataframe(
                missing_or_changed if missing_or_changed is not None and not missing_or_changed.empty else df_cmp,
                title="Schema object differences",
                priority_columns=[
                    "COMPARE_STATUS", "OBJECT_TYPE", "OBJECT_NAME", "PARENT_OBJECT_TYPE",
                    "ROW_COUNT_TARGET", "ROW_COUNT_SOURCE", "ROW_DIFF",
                    "OBJECT_DETAIL_TARGET", "OBJECT_DETAIL_SOURCE",
                ],
                sort_by=["COMPARE_RANK", "OBJECT_TYPE", "OBJECT_NAME"],
                ascending=[True, True, True],
                raw_label="All schema compare rows",
            )
            if ddl_statement_rows is not None and not ddl_statement_rows.empty:
                review_rows = ddl_statement_rows.drop(
                    columns=["DDL_STATUS", "DDL_STATEMENT", "DDL_REVIEW_SQL"],
                    errors="ignore",
                )
                render_priority_dataframe(
                    review_rows,
                    title="Missing objects requiring DBA review",
                    priority_columns=[
                        "COMPARE_STATUS", "OBJECT_TYPE", "OBJECT_NAME",
                    ],
                    sort_by=["COMPARE_STATUS", "OBJECT_TYPE", "OBJECT_NAME"],
                    ascending=[True, True, True],
                    raw_label="All missing-object review rows",
                    height=260,
                )
                ddl_script = _schema_compare_ddl_script(
                    ddl_statement_rows,
                    source_db=dev_db,
                    source_schema=dev_sch,
                    target_db=prod_db,
                    target_schema=prod_sch,
                )
                if ddl_script:
                    st.text_area(
                        "Missing-object DDL script",
                        value=ddl_script,
                        height=360,
                        key="sc_missing_object_ddl_script",
                    )
                    st.download_button(
                        "Download missing-object DDL",
                        data=ddl_script,
                        file_name="schema_compare_missing_objects.sql",
                        mime="text/sql",
                        key="sc_download_missing_object_ddl",
                    )
            else:
                st.success("No missing objects were found between the selected schemas.")
            download_csv(df_cmp, "schema_compare.csv")
            if missing_or_changed is not None and not missing_or_changed.empty:
                persistence_rows = missing_or_changed.copy()
                if ddl_statement_rows is not None and not ddl_statement_rows.empty:
                    ddl_lookup = {
                        (
                            str(row.get("OBJECT_TYPE") or "").upper(),
                            str(row.get("OBJECT_NAME") or "").upper(),
                        ): str(row.get("DDL_STATEMENT") or "")
                        for _, row in ddl_statement_rows.iterrows()
                    }
                    persistence_rows["DDL_STATEMENT"] = persistence_rows.apply(
                        lambda row: ddl_lookup.get(
                            (
                                str(row.get("OBJECT_TYPE") or "").upper(),
                                str(row.get("OBJECT_NAME") or "").upper(),
                            ),
                            str(row.get("DDL_REVIEW_SQL") or ""),
                        ),
                        axis=1,
                    )
                schema_persist_sql = _schema_compare_persistence_sql(
                    persistence_rows,
                    source_db=dev_db,
                    source_schema=dev_sch,
                    target_db=prod_db,
                    target_schema=prod_sch,
                    owner="Release DBA",
                    severity="MEDIUM",
                )
                st.caption("Schema diff results are ready for the DBA monitoring log after review.")
        except Exception as e:
            st.error(f"Compare failed: {format_snowflake_error(e)}")
