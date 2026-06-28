# utils/workflows.py - helpers for DBA workflow hub navigation
from __future__ import annotations

import hashlib
import html
import inspect
import re
from contextlib import contextmanager
from importlib import import_module
from collections.abc import Mapping, Sequence

import streamlit as st

from .cost import freshness_note, get_credit_price, metric_confidence_label
from .section_guidance import defer_section_note, defer_source_note


WORKFLOWS_VERSION = "2026-06-09-load-status-guard-v1"
CONTEXT_PRIORITY_COLUMNS = ("ENVIRONMENT", "DATABASE_NAME", "SCHEMA_NAME")
_CREDIT_COST_COMPANION_LIMIT = 10
STATUS_DISPLAY_COLUMNS = (
    "STATE",
    "STATUS",
    "READINESS",
    "CONTROL_STATE",
    "AUDIT_READINESS",
    "CLOSURE_READINESS",
    "VERIFICATION_STATUS",
    "POST_CHANGE_VERIFICATION_STATUS",
    "RECOVERY_AUDIT_STATE",
    "RECOVERY_SLA_STATE",
    "APPROVAL_STATE",
    "OWNER_APPROVAL_STATUS",
)
_EXACT_STATUS_DISPLAY_LABELS = {
    "Not Loaded": "Load on demand",
    "Refresh Needed": "Refresh available",
}
_DISPLAY_TEXT_REPLACEMENTS = (
    (r"\bSource\s+Health\b", "Data Health"),
    (r"\bsource\s+health\b", "data health"),
    (r"\bsource status\b", "data status"),
    (r"\bsource readiness\b", "data health"),
    (r"\bsource confidence\b", "measurement confidence"),
    (r"\bsource evidence\b", "data telemetry"),
    (r"\bsource proof\b", "input basis"),
    (r"\bsource-specific\b", "input-specific"),
    (r"\bsource surface\(s\)\b", "data input(s)"),
    (r"\bsource surfaces\b", "data inputs"),
    (r"\bsource-state\b", "data-state"),
    (r"\bsource state\b", "data state"),
    (r"\bsource\(s\)", "input(s)"),
    (r"\bsources\b", "inputs"),
    (r"\bSources\b", "Inputs"),
    (r"\bOVERWATCH mart\b", "fast summary"),
    (r"\bmart contract\b", "data health"),
    (r"\bMart Contract\b", "Data Health"),
    (r"\bmart\b", "fast summary"),
    (r"\bMart\b", "Fast Summary"),
    (r"\bGenerated SQL Fix\b", "Proposed action"),
    (r"\bGenerated SQL\b", "Proposed action"),
    (r"\bSQL preview\b", "action preview"),
    (r"\bSQL Preview\b", "Action Preview"),
    (r"\bDDL\b", "object change"),
    (r"\bDCL\b", "access change"),
    (r"\bOwner Approval Status\b", "Telemetry Status"),
    (r"\bOwner Approval Note\b", "Status Note"),
    (r"\bOwner Approval By\b", "Status By"),
    (r"\bOwner Approval At\b", "Status At"),
    (r"\bOwner Approval\b", "Status"),
    (r"\bowner\s+approval\b", "status"),
    (r"\bVerification Status\b", "Telemetry Status"),
    (r"\bVerification Note\b", "Status Note"),
    (r"\bVerification By\b", "Status By"),
    (r"\bVerification At\b", "Status At"),
    (r"\bVerification Query\b", "Telemetry Query"),
    (r"\bProof Query\b", "Telemetry Query"),
    (r"\bApproval Required\b", "Review"),
    (r"\bApproval Needed\b", "Review"),
    (r"\bVerification Required\b", "Telemetry Pending"),
    (r"\bVerification Needed\b", "Telemetry Pending"),
    (r"\bApproval Route Ready\b", "Route Ready"),
    (r"\bapproval required\b", "review pending"),
    (r"\bverification required\b", "telemetry pending"),
    (r"\bverification needed\b", "telemetry pending"),
    (r"\bapproval proof\b", "telemetry"),
    (r"\bapproval evidence\b", "telemetry"),
    (r"\bverification proof\b", "telemetry"),
    (r"\bverification evidence\b", "telemetry"),
    (r"\bClosure Evidence\b", "Closure Status"),
    (r"\bclosure evidence\b", "closure status"),
    (r"\bEvidence Blocked\b", "Telemetry Pending"),
    (r"\bEvidence Missing\b", "Data Missing"),
    (r"\bProof Required\b", "Telemetry Basis"),
    (r"\bData Readiness\b", "Data Health"),
    (r"\bdata readiness\b", "data health"),
    (r"\bReadiness\b", "Status"),
    (r"\breadiness\b", "status"),
    (r"\bArchitecture Review\b", "Monitoring Review"),
    (r"\barchitecture review\b", "monitoring review"),
    (r"\bArchitecture\b", "Monitoring"),
    (r"\barchitecture\b", "monitoring"),
    (r"\bclosure proof\b", "closure status"),
    (r"\bproof query\b", "telemetry query"),
    (r"\bProof\b", "Telemetry"),
    (r"\bEvidence\b", "Telemetry"),
    (r"\bproof\b", "telemetry"),
    (r"\bevidence\b", "telemetry"),
    (r"\bapproved changes\b", "reviewed changes"),
    (r"\bapproved action\b", "reviewed action"),
    (r"\bapproved\b", "reviewed"),
    (r"\bapproval\b", "review"),
    (r"\bIAM / Security Owner\b", "IAM / Security Route"),
    (r"\bSecurity Owner / Data Stewardship Lead\b", "Security / Data Stewardship Route"),
    (r"\bSecurity Owner / Data Stewardship\b", "Security / Data Stewardship Route"),
    (r"\bSecurity Owner / DBA Lead\b", "Security / DBA Route"),
    (r"\bDBA Lead / Security Owner\b", "DBA / Security Route"),
    (r"\bData Owner / Security Owner\b", "Data / Security Route"),
    (r"\bData Owner / DBA Lead\b", "Data Route / DBA Lead"),
    (r"\bDBA / Data Owner\b", "DBA / Data Route"),
    (r"\bDBA Change Owner\b", "DBA Change Route"),
    (r"\bSecurity Owner\b", "Security Route"),
    (r"\bData Owner\b", "Data Route"),
    (r"\bPlatform Owner\b", "Platform Route"),
    (r"\bOVERWATCH Platform Owner\b", "OVERWATCH Platform Route"),
    (r"\bBI Platform Owner\b", "BI Platform Route"),
    (r"\bDevelopment Platform Owner\b", "Development Platform Route"),
    (r"\bGovernance\b", "Monitoring"),
    (r"\bgovernance\b", "monitoring"),
    (r"\bOwner Route\b", "Escalation Route"),
    (r"\bOwner route\b", "Escalation route"),
    (r"\bowner route\b", "escalation route"),
    (r"\bOwner Source\b", "Route Basis"),
    (r"\bOwner Evidence\b", "Route Basis"),
    (r"\bOwner actions\b", "Routed actions"),
    (r"\bOwners\b", "Routes"),
    (r"\bNeeds Owner\b", "Needs route"),
    (r"\bowning workflow\b", "drilldown workflow"),
    (r"\bOwner\b", "Route"),
    (r"\bowner\b", "route"),
    (r"\bVerification\b", "Telemetry"),
    (r"\bverification\b", "telemetry"),
    (r"\bReview Group\b", "Escalation"),
    (r"\bReview Group\b", "escalation"),
    (r"\bApprover\b", "Reviewer"),
    (r"\bapprover\b", "reviewer"),
    (r"\bSecurity Monitoring\b", "Security Monitoring"),
)


def _clean_operator_display_value(value):
    if value is None:
        return value
    try:
        import pandas as pd

        if pd.isna(value):
            return value
    except Exception:
        pass
    if not isinstance(value, str):
        return value
    cleaned = value
    for pattern, new in _DISPLAY_TEXT_REPLACEMENTS:
        cleaned = re.sub(pattern, new, cleaned)
    return cleaned


def _render_operator_bold(value: object) -> None:
    text = str(_clean_operator_display_value(value) or "").strip()
    if text:
        st.html(
            f'<div style="line-height:1.45;margin:.15rem 0;">'
            f"<strong>{html.escape(text)}</strong></div>"
        )


def clean_operator_display_text(df):
    """Return a display-only dataframe with implementation terms softened."""
    if df is None or getattr(df, "empty", True):
        return df
    frame = df.copy()
    frame = frame.rename(columns={
        "SOURCE": "INPUT",
        "OWNER": "ROUTE",
        "OWNER_EMAIL": "ROUTE_EMAIL",
        "OWNER_SOURCE": "ROUTE_BASIS",
        "OWNER_EVIDENCE": "ROUTE_EVIDENCE",
        "Owner": "Route",
        "Owner Email": "Route Email",
        "Owner Source": "Route Basis",
        "Owner Evidence": "Route Basis",
        "Owner Route": "Escalation Route",
        "EVIDENCE": "TELEMETRY",
        "EVIDENCE_REQUIRED": "TELEMETRY_BASIS",
        "COMMAND_EVIDENCE_REQUIRED": "TELEMETRY_BASIS",
        "Evidence": "Telemetry",
        "Evidence Packet": "Telemetry Summary",
        "Evidence Package": "Telemetry Package",
        "Evidence Required": "Telemetry Basis",
        "PROOF_BLOCKS": "TELEMETRY_BLOCKS",
        "PROOF_REQUIRED": "TELEMETRY_BASIS",
        "Proof Blocks": "Telemetry Blocks",
        "Proof Required": "Telemetry Basis",
        "Proof Query": "Telemetry Query",
        "SOURCE_ISSUES": "DATA_ISSUES",
        "FIXED_WITHOUT_VERIFICATION": "CLOSED_PENDING_TELEMETRY",
        "VERIFICATION_QUERY_GAP_ROWS": "TELEMETRY_QUERY_GAP_ROWS",
        "VERIFICATION_STATUS": "TELEMETRY_STATUS",
        "VERIFICATION_QUERY": "TELEMETRY_QUERY",
        "VERIFICATION_RESULT": "TELEMETRY_RESULT",
        "VERIFICATION_NOTES": "STATUS_NOTES",
        "Verification Query Gap Rows": "Telemetry Query Gap Rows",
        "Verification Status": "Telemetry Status",
        "Verification Query": "Telemetry Query",
        "Verification Result": "Telemetry Result",
        "Verification Notes": "Status Notes",
        "OWNER_APPROVAL_STATUS": "TELEMETRY_STATUS",
        "OWNER_APPROVAL_STATE": "TELEMETRY_STATE",
        "OWNER_APPROVAL_NOTE": "STATUS_NOTE",
        "OWNER_APPROVAL_BY": "STATUS_BY",
        "OWNER_APPROVAL_AT": "STATUS_AT",
        "OWNER_APPROVAL_GAP_ROWS": "TELEMETRY_GAP_ROWS",
        "Owner Approval Status": "Telemetry Status",
        "Owner Approval State": "Telemetry State",
        "Owner Approval Note": "Status Note",
        "Owner Approval By": "Status By",
        "Owner Approval At": "Status At",
        "Owner Approval Gap Rows": "Telemetry Gap Rows",
        "PROOF_QUERY": "TELEMETRY_QUERY",
        "RECOVERY_EVIDENCE": "RECOVERY_STATUS",
        "Recovery Evidence": "Recovery Status",
        "APPROVAL_GROUP": "REVIEW_GROUP",
        "APPROVAL_REQUIRED": "REVIEW_REQUIRED",
        "APPROVAL_STATE": "REVIEW_STATE",
        "APPROVAL_ROUTE_READY": "ROUTE_READY",
        "APPROVAL_REQUIRED_ROWS": "REVIEW_REQUIRED_ROWS",
        "APPROVAL_BLOCKS": "REVIEW_BLOCKS",
        "APPROVER_GAP_ROWS": "REVIEWER_GAP_ROWS",
        "APPROVAL_GATE": "REVIEW_GATE",
        "Approval Group": "Review Group",
        "Approval Required": "Review Required",
        "Approval State": "Review State",
        "Approval Route Ready": "Route Ready",
        "Approval Required Rows": "Review Required Rows",
        "Approval Blocks": "Review Blocks",
        "Approver Gap Rows": "Reviewer Gap Rows",
        "Approval Gate": "Review Gate",
        "MANUAL_SQL_STATE": "ACTION_SQL_STATE",
        "MANUAL_ACTION_SQL": "ACTION_SQL",
        "Manual SQL State": "Action SQL State",
        "Manual Action SQL": "Action SQL",
        "AUDIT_EVIDENCE_REQUIRED": "AUDIT_TELEMETRY_REQUIRED",
        "APPROVER": "REVIEWER",
        "Approver": "Reviewer",
        "OWNER_GAP_ROWS": "ROUTE_GAP_ROWS",
        "Owner Gap Rows": "Route Gap Rows",
        "SOURCE_CONFIDENCE": "MEASUREMENT_BASIS",
        "SOURCE_STATUS": "DATA_STATUS",
        "Source Confidence": "Measurement Basis",
        "Source Status": "Data Status",
    })
    object_columns = frame.select_dtypes(include=["object", "string"]).columns
    for column in object_columns:
        frame[column] = frame[column].map(_clean_operator_display_value)
    return frame


def prioritize_context_columns(
    df,
    *,
    leading_columns: Sequence[str] = (),
    context_columns: Sequence[str] = CONTEXT_PRIORITY_COLUMNS,
):
    """Keep scope columns visible before wide operational evidence."""
    if df is None or getattr(df, "empty", True):
        return df
    leading = [column for column in leading_columns if column in df.columns]
    context = [
        column for column in context_columns
        if column in df.columns and column not in leading
    ]
    if not leading and not context:
        return df
    ordered = leading + context
    return df[ordered + [column for column in df.columns if column not in ordered]]


def _credit_metric_column(column: str) -> bool:
    upper = str(column or "").upper()
    if "CREDIT" not in upper:
        return False
    if any(token in upper for token in (
        "PRICE", "RATE", "PCT", "PERCENT", "COST", "USD", "DOLLAR",
        "PER_CREDIT", "CREDIT_TYPE", "METHOD", "SCORE", "RANK",
    )):
        return False
    return True


def add_cost_companion_columns(df, *, credit_price: float | None = None, max_columns: int = _CREDIT_COST_COMPANION_LIMIT):
    """Add cost-dollar companions for obvious credit metrics in display tables."""
    if df is None or getattr(df, "empty", True):
        return df
    frame = df.copy()
    try:
        import pandas as pd
    except Exception:
        return frame
    try:
        price = float(get_credit_price() if credit_price is None else credit_price)
    except Exception:
        return frame
    added = 0
    for column in list(frame.columns):
        if added >= int(max_columns or _CREDIT_COST_COMPANION_LIMIT):
            break
        if not _credit_metric_column(str(column)):
            continue
        cost_column = f"{str(column).upper()}_COST_USD"
        if cost_column in frame.columns:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        if values.notna().sum() == 0:
            continue
        if "RATE_USD" in frame.columns:
            rates = pd.to_numeric(frame["RATE_USD"], errors="coerce").fillna(price)
            cost_values = (values.fillna(0) * rates).round(2)
        else:
            cost_values = (values.fillna(0) * price).round(2)
        insert_at = min(len(frame.columns), list(frame.columns).index(column) + 1)
        frame.insert(insert_at, cost_column, cost_values)
        added += 1
    return frame


def _operator_status_label(value, column: str = ""):
    if value is None:
        return value
    text = str(value).strip()
    if not text:
        return value
    if text in _EXACT_STATUS_DISPLAY_LABELS:
        return _EXACT_STATUS_DISPLAY_LABELS[text]
    if text == "Pending":
        column_upper = str(column or "").upper()
        if "VERIFICATION" in column_upper:
            return "Awaiting telemetry"
        if "APPROVAL" in column_upper:
            return "Awaiting review"
        return "Awaiting action"
    if text.lower().endswith(" pending"):
        return _clean_operator_display_value(f"{text[:-8].rstrip()} Needed")
    return value


def apply_operator_status_labels(df, *, columns: Sequence[str] = STATUS_DISPLAY_COLUMNS):
    """Use calm operator-facing labels for display-only status/readiness tables."""
    if df is None or getattr(df, "empty", True):
        return df
    frame = df.copy()
    status_columns = {
        column
        for column in frame.columns
        if any(token in str(column).upper() for token in columns)
    }
    for column in status_columns:
        frame[column] = frame[column].map(lambda value: _operator_status_label(value, str(column)))
    return frame


def coerce_workflow_state(key: str, workflows: Sequence[str]) -> str:
    """Return a valid workflow selection for a session-state key."""
    if not workflows:
        raise ValueError("workflows must contain at least one entry")
    selected = st.session_state.get(key, workflows[0])
    if selected not in workflows:
        selected = workflows[0]
        st.session_state[key] = selected
    return str(selected)


def workflow_selector_groups(
    selected: str,
    workflows: Sequence[str],
    *,
    collapse_after: int | None = None,
) -> tuple[list[str], list[str]]:
    """Split workflow buttons into visible and collapsed groups without hiding the selected view."""
    items = list(workflows)
    if collapse_after is None or collapse_after <= 0 or collapse_after >= len(items):
        return items, []
    selected_text = str(selected)
    visible = list(items[: max(1, int(collapse_after))])
    if selected_text in items and selected_text not in visible:
        visible = [selected_text] + [item for item in visible if item != selected_text]
        visible = visible[: max(1, int(collapse_after))]
    hidden = [item for item in items if item not in visible]
    return visible, hidden


def _render_workflow_button_rows(
    *,
    key: str,
    workflows: Sequence[str],
    selected: str,
    columns: int,
    labels: Mapping[str, str],
    key_suffix: str = "",
) -> None:
    items = list(workflows)
    for start in range(0, len(items), columns):
        row = items[start:start + columns]
        cols = st.columns(len(row))
        for col, workflow in zip(cols, row):
            with col:
                is_selected = workflow == selected
                suffix = f"_{key_suffix}" if key_suffix else ""
                if st.button(
                    labels.get(workflow, workflow),
                    key=f"{key}{suffix}_{start}_{workflow}",
                    type="primary" if is_selected else "secondary",
                    width="stretch",
                ):
                    st.session_state[key] = workflow
                    st.rerun()


def _render_selector_context(
    *,
    label: str,
    selected: str,
    details: Mapping[str, str],
    labels: Mapping[str, str],
) -> None:
    """Render the selected workflow's operating context when one is provided."""
    detail = str(details.get(selected) or "").strip()
    selected_label = str(labels.get(selected, selected))
    if not detail and not selected_label:
        return
    eyebrow = html.escape(str(label or "Selected workflow"))
    title = html.escape(str(_clean_operator_display_value(selected_label) or selected_label))
    body = html.escape(str(_clean_operator_display_value(detail) or detail))
    detail_markup = f'<div class="ow-workflow-context-detail">{body}</div>' if body else ""
    st.html(
        '<div class="ow-workflow-context" role="note">'
        f'<div class="ow-workflow-context-kicker">{eyebrow}</div>'
        f'<div class="ow-workflow-context-title">{title}</div>'
        f"{detail_markup}"
        '</div>'
    )


def render_workflow_selector(
    label: str,
    key: str,
    workflows: Sequence[str],
    details: Mapping[str, str] | None = None,
    *,
    columns: int = 4,
    show_label: bool = False,
    labels: Mapping[str, str] | None = None,
    compact_details: bool = False,
    collapse_after: int | None = None,
    collapsed_label: str = "More workflows",
) -> str:
    """Render a compact workflow launcher that honors deep-link state."""
    selected = coerce_workflow_state(key, workflows)
    details = details or {}
    labels = labels or {}
    if label and show_label:
        st.caption(label)
    items = list(workflows)
    columns = max(1, min(int(columns or 4), 5))
    visible_items, hidden_items = workflow_selector_groups(selected, items, collapse_after=collapse_after)
    if compact_details:
        _render_selector_context(label=label, selected=selected, details=details, labels=labels)
    _render_workflow_button_rows(
        key=key,
        workflows=visible_items,
        selected=selected,
        columns=columns,
        labels=labels,
    )
    if hidden_items:
        with st.expander(collapsed_label, expanded=False):
            _render_workflow_button_rows(
                key=key,
                workflows=hidden_items,
                selected=selected,
                columns=columns,
                labels=labels,
                key_suffix="collapsed",
            )
    return str(st.session_state.get(key, selected))


def render_mode_selector(
    label: str,
    key: str,
    modes: Sequence[str],
    *,
    default: str | None = None,
    label_visibility: str = "collapsed",
    details: Mapping[str, str] | None = None,
    labels: Mapping[str, str] | None = None,
    columns: int = 4,
) -> str:
    """Render a compact mode selector that honors deep-link state."""
    if not modes:
        raise ValueError("modes must contain at least one entry")
    options = list(modes)
    fallback = default if default in options else options[0]
    selected = st.session_state.get(key, fallback)
    if selected not in options:
        selected = fallback
        st.session_state[key] = selected

    details = details or {}
    labels = labels or {}
    if details:
        columns = max(1, min(int(columns or 4), 5))
        for start in range(0, len(options), columns):
            row = options[start:start + columns]
            cols = st.columns(len(row))
            for col, mode in zip(cols, row):
                with col:
                    is_selected = mode == selected
                    if st.button(
                        labels.get(mode, mode),
                        key=f"{key}_{start}_{mode}",
                        type="primary" if is_selected else "secondary",
                        width="stretch",
                    ):
                        st.session_state[key] = mode
                        st.rerun()
        return str(st.session_state.get(key, selected))

    segmented = getattr(st, "segmented_control", None)
    widget_has_state = key in st.session_state
    if callable(segmented):
        segmented_kwargs = {
            "selection_mode": "single",
            "key": key,
            "label_visibility": label_visibility,
            "width": "stretch",
        }
        if not widget_has_state:
            segmented_kwargs["default"] = selected
        value = segmented(
            label,
            options,
            **segmented_kwargs,
        )
    else:
        selectbox_kwargs = {
            "key": key,
            "label_visibility": label_visibility,
        }
        if not widget_has_state:
            selectbox_kwargs["index"] = options.index(selected)
        value = st.selectbox(
            label,
            options,
            **selectbox_kwargs,
        )
    if value not in options:
        return str(selected)
    return str(value)


@contextmanager
def render_load_status(label: str, complete_label: str | None = None, *, expanded: bool = False):
    """Show consistent lightweight feedback around explicit evidence loads."""
    complete = complete_label or f"{label} complete"
    try:
        status_cm = st.status(label, expanded=expanded)
    except Exception:
        with st.spinner(label):
            yield None
        return

    with status_cm as status:
        try:
            yield status
        except Exception:
            status.update(label=f"{label} did not complete", state="error", expanded=True)
            raise
        else:
            status.update(label=complete, state="complete", expanded=False)


def migrate_legacy_workflow_state(
    legacy_key: str,
    target_key: str,
    mapping: Mapping[str, str],
    *,
    remove_legacy: bool = True,
) -> None:
    """Move one old workflow key into a consolidated workflow state key."""
    if remove_legacy:
        legacy_value = st.session_state.pop(legacy_key, None)
    else:
        legacy_value = st.session_state.get(legacy_key)
    mapped = mapping.get(str(legacy_value or ""))
    if mapped:
        st.session_state[target_key] = mapped


def render_workflow_module(workflow: str, workflow_modules: Mapping[str, str]) -> None:
    """Import and render only the specialist module selected by a workflow hub."""
    module_name = workflow_modules.get(str(workflow))
    if not module_name:
        st.warning(f"No module registered for workflow: {workflow}")
        return
    module = import_module(module_name)
    render = getattr(module, "render", None)
    if not callable(render):
        st.warning(f"Workflow module has no render() function: {module_name}")
        return
    render()


def render_workflow_guide(summary: str, rows: Sequence[tuple[str, str]]) -> None:
    """Collect DBA decision-guide text for the bottom notes area."""
    defer_section_note(summary)
    for trigger, action in rows:
        defer_section_note(f"{trigger}: {action}")


def render_operator_briefing(
    rows: Sequence[tuple[str, str]],
    *,
    title: str = "Operating notes",
    columns: int = 4,
) -> None:
    """Collect operating brief text for the bottom notes area."""
    if not rows:
        return
    for label, detail in rows:
        defer_section_note(f"{label}: {detail}")


def add_signal_routes(
    df,
    route_rules: Mapping[str, tuple[str, str]],
    *,
    signal_col: str = "SIGNAL",
    workflow_col: str = "NEXT_WORKFLOW",
    action_col: str = "NEXT_ACTION",
    default_workflow: str = "Investigate",
    default_action: str = "Open the source row, validate evidence, then route to the owning DBA workflow.",
):
    """Add consistent next-workflow and next-action columns to an exception dataframe."""
    if df is None or getattr(df, "empty", True):
        return df
    routed = df.copy()

    def _route(signal: object, index: int) -> str:
        workflow, action = route_rules.get(str(signal), (default_workflow, default_action))
        return workflow if index == 0 else action

    routed[workflow_col] = routed.get(signal_col, "").apply(lambda value: _route(value, 0))
    routed[action_col] = routed.get(signal_col, "").apply(lambda value: _route(value, 1))
    return routed


def render_priority_dataframe(
    df,
    *,
    title: str = "Priority view",
    priority_columns: Sequence[str] | None = None,
    sort_by: Sequence[str] | None = None,
    ascending: Sequence[bool] | bool = False,
    max_rows: int = 25,
    raw_label: str = "Full detail",
    height: int | None = None,
    column_config: Mapping | None = None,
) -> None:
    """Show the actionable subset first, with raw detail hidden behind an expander."""
    if df is None or getattr(df, "empty", True):
        return

    view = df.copy()
    hidden_ui_columns = {
        "Generated SQL Fix",
        "GENERATED_SQL_FIX",
        "Generated SQL",
        "GENERATED_SQL",
        "SQL",
        "SQL_TEXT",
        "SQL_PREVIEW",
        "SQL_PACKAGE",
        "QUERY_PREVIEW",
        "Proof Query",
        "PROOF_QUERY",
        "Verification Query",
        "VERIFICATION_QUERY",
        "Telemetry Query",
        "TELEMETRY_QUERY",
        "DDL_STATEMENT",
        "DDL Statement",
        "DDL_REVIEW_SQL",
        "DDL Review SQL",
        "GENERATED_DDL",
        "Generated DDL",
        "ROLLBACK_SQL",
        "Rollback SQL",
        "CHANGE_SQL",
        "Change SQL",
        "PRECHECK_SQL",
        "Precheck SQL",
        "APPROVAL_GROUP",
        "Approval Group",
        "OWNER",
        "Owner",
        "OWNER_NAME",
        "Owner Name",
        "OWNER_EMAIL",
        "Owner Email",
        "APPROVER",
        "Approver",
        "APPROVAL_STATE",
        "Approval State",
        "APPROVAL_REQUIRED",
        "Approval Required",
        "OWNER_APPROVAL_STATUS",
        "Owner Approval Status",
        "OWNER_APPROVAL_STATE",
        "Owner Approval State",
        "OWNER_APPROVAL_NOTE",
        "Owner Approval Note",
        "OWNER_APPROVAL_BY",
        "Owner Approval By",
        "OWNER_APPROVAL_AT",
        "Owner Approval At",
        "OWNER_ROUTE_READY",
        "Owner Route Ready",
        "OWNER_ROUTE_STATE",
        "Owner Route State",
        "OWNER_SOURCE",
        "Owner Source",
        "OWNER_EVIDENCE",
        "Owner Evidence",
        "NEXT_OWNER_ACTION",
        "Next Owner Action",
    }

    def _is_hidden_ui_column(column: object) -> bool:
        text = str(column or "")
        upper = text.upper()
        return (
            text in hidden_ui_columns
            or "SQL" in upper
            or "DDL" in upper
            or "DCL" in upper
            or "PROOF" in upper
            or "EVIDENCE" in upper
            or "VERIFY" in upper
            or "VERIFICATION" in upper
            or "APPROVAL" in upper
            or "READINESS" in upper
            or "MANUAL" in upper
            or "OWNER" in upper
            or "INTERNAL" in upper
            or "OWNER APPROVAL" in upper
            or "SCORE" in upper
            or upper == "WEIGHT"
            or upper.endswith("_WEIGHT")
            or upper.endswith(" WEIGHT")
        )
    if sort_by:
        available_sort = [column for column in sort_by if column in view.columns]
        severity_rank_cols: list[str] = []
        severity_rank_indices: list[int] = []
        severity_rank = {
            "CRITICAL": 0,
            "HIGH": 1,
            "MEDIUM": 2,
            "WATCH": 3,
            "LOW": 4,
            "INFO": 5,
        }
        for idx, column in enumerate(list(available_sort)):
            if str(column).upper() == "SEVERITY":
                rank_col = f"_OVERWATCH_SEVERITY_RANK_{idx}"
                view[rank_col] = view[column].astype(str).str.upper().map(severity_rank).fillna(9)
                available_sort[idx] = rank_col
                severity_rank_cols.append(rank_col)
                severity_rank_indices.append(idx)
        if available_sort:
            sort_ascending: Sequence[bool] | bool
            if isinstance(ascending, Sequence) and not isinstance(ascending, (str, bytes)):
                sort_ascending = list(ascending)[: len(available_sort)]
                if len(sort_ascending) < len(available_sort):
                    sort_ascending = list(sort_ascending) + [False] * (len(available_sort) - len(sort_ascending))
            else:
                sort_ascending = [bool(ascending)] * len(available_sort)
            for idx in severity_rank_indices:
                if idx < len(sort_ascending):
                    sort_ascending[idx] = True
            view = view.sort_values(available_sort, ascending=sort_ascending)
        if severity_rank_cols:
            view = view.drop(columns=severity_rank_cols, errors="ignore")

    view = view.drop(columns=[column for column in view.columns if _is_hidden_ui_column(column)], errors="ignore")

    if priority_columns:
        priority = [column for column in priority_columns if column in view.columns]
        context_columns = [
            column for column in CONTEXT_PRIORITY_COLUMNS
            if column in view.columns and column not in priority
        ]
        columns = context_columns + priority
        if columns:
            view = view[columns]
    view = prioritize_context_columns(view)
    view = add_cost_companion_columns(view)
    display_view = clean_operator_display_text(apply_operator_status_labels(view))

    visible_rows = min(len(view), int(max_rows or 25))
    display_title = _clean_operator_display_value(str(title or "Priority view"))
    display_raw_label = _clean_operator_display_value(str(raw_label or "Full detail"))
    _render_operator_bold(display_title)
    st.caption(f"Showing {visible_rows:,} of {len(df):,}")
    dataframe_kwargs = {
        "use_container_width": True,
        "hide_index": True,
    }
    if height is not None:
        dataframe_kwargs["height"] = height
    default_column_config = {
        "CONFIDENCE": st.column_config.TextColumn("Measurement Basis"),
        "ALLOCATION_CONFIDENCE": st.column_config.TextColumn("Allocation Measurement"),
        "SCOPE_CONFIDENCE": st.column_config.TextColumn("Scope Basis"),
        "SOURCE_CONFIDENCE": st.column_config.TextColumn("Measurement Basis"),
    }
    active_column_config = {
        column: config
        for column, config in default_column_config.items()
        if column in view.columns
    }
    if column_config:
        active_column_config.update(column_config)
    if active_column_config:
        dataframe_kwargs["column_config"] = active_column_config
    st.dataframe(display_view.head(max_rows), **dataframe_kwargs)
    if len(df) > max_rows:
        with st.expander(f"{display_raw_label} ({len(df):,} rows)", expanded=False):
            st.caption(
                "Full detail is loaded only when requested so page navigation stays fast."
            )
            frame = inspect.currentframe()
            caller = frame.f_back if frame is not None else None
            key_basis = "|".join([
                str(getattr(getattr(caller, "f_code", None), "co_filename", "")),
                str(getattr(caller, "f_lineno", "")),
                str(title),
                str(raw_label),
            ])
            button_key = f"ow_raw_detail_{hashlib.sha1(key_basis.encode('utf-8', errors='ignore')).hexdigest()[:12]}"
            if st.button("Show full detail", key=button_key):
                raw_kwargs = {"use_container_width": True, "hide_index": True}
                if active_column_config:
                    raw_kwargs["column_config"] = active_column_config
                raw_view = df.drop(columns=[column for column in df.columns if _is_hidden_ui_column(column)], errors="ignore")
                st.dataframe(
                    clean_operator_display_text(apply_operator_status_labels(
                        add_cost_companion_columns(prioritize_context_columns(raw_view))
                    )),
                    **raw_kwargs,
                )


def render_signal_confidence(
    *,
    source: str = "ACCOUNT_USAGE",
    confidence: str = "allocated",
    scope_note: str = "",
) -> None:
    """Collect consistent source/freshness notes for workflow hubs."""
    parts = [
        freshness_note(source),
        metric_confidence_label(confidence),
    ]
    if scope_note:
        parts.append(scope_note)
    defer_source_note(*parts)
