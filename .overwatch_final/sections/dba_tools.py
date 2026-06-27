# sections/dba_tools.py - DBA admin toolkit compatibility facade.

import streamlit as st

from utils import get_active_company, get_session
from sections.navigation import apply_navigation_state
from utils.dba_tool_catalog import (
    DBA_TOOL_FOCUS_GROUPS,
    DBA_TOOL_FOCUS_HINTS,
    DBA_TOOL_GROUPS,
)
from utils.workflows import render_workflow_selector

from sections.dba_tools_contracts import (
    ACCOUNT_PARAMETER_ADMIN_ROLES,
    DATA_COMPARE_EXECUTION_STAGES,
    SCHEMA_COMPARE_OBJECT_COVERAGE,
)
from sections.dba_tools_common import (
    _as_bool,
    _as_int,
    _current_role_allows_alter_account,
    _ensure_column_alias,
    _first_existing_column,
    _load_button,
    _load_task_inventory,
    _prioritize_query_context,
    _qualified_name,
    _query_context_expr,
    _quote_identifier,
    _require_typed_confirmation,
    _scope_metadata_df,
    _scope_warehouse_names,
    _select_option,
    _show_to_df,
    _task_history_sql,
    _typed_confirmation,
)
from sections.dba_tools_data_compare import (
    _build_data_compare_plan,
    _data_compare_bucket_sql,
    _data_compare_column_rows,
    _data_compare_column_signature,
    _data_compare_extract_summary,
    _data_compare_forensic_sql,
    _data_compare_hash_sql,
    _data_compare_normalize_tables,
    _data_compare_outcome,
    _data_compare_parse_identifiers,
    _data_compare_persistence_sql,
    _data_compare_supported_hash_column,
    _data_compare_tables_sql,
    _data_compare_where_clause,
    _recon_config_insert_sql,
    _recon_history_sql,
    _sql_number_expr,
)
from sections.dba_tools_schema_compare import (
    _build_schema_compare_frame,
    _first_present_column,
    _schema_compare_columns_sql,
    _schema_compare_coverage_label,
    _schema_compare_column_type,
    _schema_compare_ddl_script,
    _schema_compare_fetch_missing_ddl_statements,
    _schema_compare_get_ddl_type,
    _schema_compare_inventory,
    _schema_compare_missing_column_ddl,
    _schema_compare_missing_ddl,
    _schema_compare_normalize_columns,
    _schema_compare_normalize_kind,
    _schema_compare_normalize_show_objects,
    _schema_compare_numeric_text,
    _schema_compare_object_fqn,
    _schema_compare_persistence_sql,
    _schema_compare_show_objects_sql,
)
from sections.dba_tools_setup import (
    _setup_status_df,
    _table_exists,
    _task_exists,
)
from sections.dba_tools_warehouse_settings import (
    _build_warehouse_setting_plan,
    _is_unknown_setting,
    _normalize_warehouse_setting,
    _warehouse_setting_review_gate,
    _warehouse_setting_risk,
    _warehouse_settings_preflight_sql,
    _warehouse_size_sql,
)
from sections.dba_tools_data_compare_view import (
    _render_data_compare_command_model,
    render_data_compare_tool,
)
from sections.dba_tools_schema_compare_view import (
    _render_schema_compare_command_model,
    render_schema_compare_tool,
)
from sections.dba_tools_warehouse_settings_view import render_warehouse_settings_tool
from sections.dba_tools_qas_monitor_view import render_qas_monitor_tool
from sections.dba_tools_query_kill_view import render_query_kill_list_tool
from sections.dba_tools_cortex_limits_view import render_cortex_ai_limits_tool
from sections.dba_tools_task_graph_control_view import render_task_graph_control_tool
from sections.dba_tools_cost_health_view import (
    render_cost_formula_audit_tool,
    render_data_health_tool,
    render_serverless_costs_tool,
    render_summary_status_tool,
)
from sections.dba_tools_data_movement_view import (
    render_data_loading_tool,
    render_dynamic_tables_tool,
    render_replication_tool,
    render_snowpipe_monitor_tool,
)
from sections.dba_tools_object_monitoring_view import (
    render_network_sessions_tool,
    render_recent_objects_tool,
    render_unused_objects_tool,
)


DBA_TOOL_RENDERERS = {
    "Query Kill List": render_query_kill_list_tool,
    "Warehouse Settings": render_warehouse_settings_tool,
    "QAS Monitor": render_qas_monitor_tool,
    "Task Graph Control": render_task_graph_control_tool,
    "Data Loading": render_data_loading_tool,
    "Snowpipe Monitor": render_snowpipe_monitor_tool,
    "Dynamic Tables": render_dynamic_tables_tool,
    "Replication": render_replication_tool,
    "Network & Sessions": render_network_sessions_tool,
    "Unused Objects": render_unused_objects_tool,
    "Schema Compare": render_schema_compare_tool,
    "Data Compare": render_data_compare_tool,
    "Recent Objects": render_recent_objects_tool,
    "Summary Status": render_summary_status_tool,
    "Serverless Costs": render_serverless_costs_tool,
    "Cost Formula Audit": render_cost_formula_audit_tool,
    "Cortex AI Limits": render_cortex_ai_limits_tool,
    "Data Health": render_data_health_tool,
}

INLINE_DBA_TOOL_HANDLERS = frozenset()

__all__ = [
    "ACCOUNT_PARAMETER_ADMIN_ROLES",
    "DATA_COMPARE_EXECUTION_STAGES",
    "DBA_TOOL_RENDERERS",
    "INLINE_DBA_TOOL_HANDLERS",
    "SCHEMA_COMPARE_OBJECT_COVERAGE",
    "_as_bool",
    "_as_int",
    "_build_data_compare_plan",
    "_build_schema_compare_frame",
    "_build_warehouse_setting_plan",
    "_current_role_allows_alter_account",
    "_data_compare_bucket_sql",
    "_data_compare_column_rows",
    "_data_compare_column_signature",
    "_data_compare_extract_summary",
    "_data_compare_forensic_sql",
    "_data_compare_hash_sql",
    "_data_compare_normalize_tables",
    "_data_compare_outcome",
    "_data_compare_parse_identifiers",
    "_data_compare_persistence_sql",
    "_data_compare_supported_hash_column",
    "_data_compare_tables_sql",
    "_data_compare_where_clause",
    "_ensure_column_alias",
    "_first_existing_column",
    "_first_present_column",
    "_is_unknown_setting",
    "_load_button",
    "_load_task_inventory",
    "_normalize_warehouse_setting",
    "_prioritize_query_context",
    "_qualified_name",
    "_query_context_expr",
    "_quote_identifier",
    "_recon_config_insert_sql",
    "_recon_history_sql",
    "_render_data_compare_command_model",
    "_render_schema_compare_command_model",
    "_require_typed_confirmation",
    "_schema_compare_columns_sql",
    "_schema_compare_coverage_label",
    "_schema_compare_column_type",
    "_schema_compare_ddl_script",
    "_schema_compare_fetch_missing_ddl_statements",
    "_schema_compare_get_ddl_type",
    "_schema_compare_inventory",
    "_schema_compare_missing_column_ddl",
    "_schema_compare_missing_ddl",
    "_schema_compare_normalize_columns",
    "_schema_compare_normalize_kind",
    "_schema_compare_normalize_show_objects",
    "_schema_compare_numeric_text",
    "_schema_compare_object_fqn",
    "_schema_compare_persistence_sql",
    "_schema_compare_show_objects_sql",
    "_scope_metadata_df",
    "_scope_warehouse_names",
    "_select_option",
    "_setup_status_df",
    "_show_to_df",
    "_sql_number_expr",
    "_table_exists",
    "_task_exists",
    "_task_history_sql",
    "_typed_confirmation",
    "_warehouse_setting_review_gate",
    "_warehouse_setting_risk",
    "_warehouse_settings_preflight_sql",
    "_warehouse_size_sql",
    "render",
]


def render():
    session = get_session()
    company = get_active_company()

    focus = st.session_state.get("dba_tools_focus")
    default_group = DBA_TOOL_FOCUS_GROUPS.get(str(focus), "Warehouse Ops")
    group_names = list(DBA_TOOL_GROUPS)
    focus_tool = str(st.session_state.get("dba_tools_focus_tool") or "")
    focus_tool_active = (
        focus_tool
        and default_group in DBA_TOOL_GROUPS
        and focus_tool in DBA_TOOL_GROUPS[default_group]
    )
    if focus_tool_active:
        selected_group = default_group
        tool_options = DBA_TOOL_GROUPS[selected_group]
        selected_tool = focus_tool
        focus_hint = DBA_TOOL_FOCUS_HINTS.get(
            str(focus),
            "Use the matching workflow when you need additional DBA tools.",
        )
        st.caption(f"Workflow focus: {selected_tool}. {focus_hint}")
    else:
        st.caption(
            "Guarded admin workflows are grouped to keep the high-value controls easy to find. "
            "Open a group, then choose the specific operation."
        )
        if focus:
            focus_hint = DBA_TOOL_FOCUS_HINTS.get(
                str(focus),
                "Use the matching tab group below first; other tools remain available when needed.",
            )
            st.info(f"Security Monitoring focus: {focus}. {focus_hint}")
        with st.expander("Guarded Admin Operating Model", expanded=not bool(focus)):
            risk_a, risk_b, risk_c = st.columns(3)
            with risk_a:
                st.info(
                    "Safe Observability\n\n"
                    "Read-only inventory, diagnostics, compatibility checks, schema compare, recent objects, "
                    "QAS visibility, replication, serverless costs, and action history."
                )
            with risk_b:
                st.warning(
                    "Controlled Actions\n\n"
                    "Query cancellation, task suspend/resume, warehouse setting changes, and Cortex limit updates. "
                    "These remain guarded by typed confirmation and Snowflake privileges."
                )
            with risk_c:
                st.success(
                    "Readiness and Audit\n\n"
                    "Compatibility checks, data readiness, action queue routing, and "
                    "formula audit evidence stay available without exposing deployment plumbing."
                )
        if "dba_tools_group_selector" not in st.session_state and default_group in group_names:
            st.session_state["dba_tools_group_selector"] = default_group
        selected_group = render_workflow_selector(
            "DBA workflow",
            "dba_tools_group_selector",
            group_names,
            columns=3,
            show_label=True,
        )
        tool_options = DBA_TOOL_GROUPS[selected_group]
        selected_tool = st.selectbox(
            "Open specialist tool",
            tool_options,
            key=f"dba_tools_tool_selector_{selected_group}",
        )
        st.info("Alert history, email-ready delivery rows, routing, and suppression windows now live in the consolidated Alert Center.")
        if st.button("Open Alert Center", key="dba_tools_open_alert_center"):
            apply_navigation_state("Alert Center")
            st.rerun()

    st.divider()
    if not focus_tool_active:
        st.caption(
            "Focused mode renders one specialist tool at a time. Use the workflow hubs for daily operations; "
            "use this page when you need a specific admin utility."
        )

    renderer = DBA_TOOL_RENDERERS.get(selected_tool)
    if renderer is not None:
        renderer(session, company)
