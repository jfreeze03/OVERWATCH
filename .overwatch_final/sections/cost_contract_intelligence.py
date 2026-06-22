"""Cost & Contract cost-intelligence dataframe builders.

This module owns board construction for Cost & Contract diagnostics.  It may
read already-loaded Streamlit session frames, but it does not render UI, run
Snowflake SQL, or mutate session state; ``cost_contract.py`` remains the
workflow/render shell and re-exports these helpers for compatibility.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from sections.cost_contract_advisor import _cost_action_mask, _open_cost_action_frame
from sections.cost_contract_dataframes import _has_columns, _loaded_rows, _top_loaded_cost_driver
from utils.cost import credits_to_dollars
from utils.primitives import safe_float, safe_int


def _loaded_cortex_state() -> tuple[float, int]:
    summary = st.session_state.get("cortex_control_summary")
    exceptions = st.session_state.get("cortex_control_exceptions")
    projected = 0.0
    if isinstance(summary, pd.DataFrame) and not summary.empty:
        projected = safe_float(summary.iloc[0].get("PROJECTED_30D_COST", 0))
    exception_count = len(exceptions) if isinstance(exceptions, pd.DataFrame) and not exceptions.empty else 0
    return projected, exception_count


def _state_frame(state: dict, key: str) -> pd.DataFrame:
    value = state.get(key)
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _source_state(frame: pd.DataFrame | None, error: str = "", *, empty_state: str = "No Rows") -> str:
    if str(error or "").strip():
        return "Unavailable"
    if isinstance(frame, pd.DataFrame) and not frame.empty:
        return "Ready"
    return empty_state


def _add_source_health_row(
    rows: list[dict],
    source: str,
    scope: str,
    state: str,
    rows_loaded: int,
    evidence: str,
    next_action: str,
    freshness: str,
) -> None:
    rows.append({
        "SOURCE": source,
        "SCOPE": scope,
        "STATE": state,
        "ROWS_LOADED": safe_int(rows_loaded),
        "FRESHNESS": freshness,
        "EVIDENCE": evidence,
        "NEXT_ACTION": next_action,
    })


def _build_cost_source_health_board(
    *,
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
    attribution: pd.DataFrame,
    service_lens: pd.DataFrame,
    state: dict | None = None,
) -> tuple[dict, pd.DataFrame]:
    """Build a compact source-health panel for official and OVERWATCH cost telemetry."""
    state = state or st.session_state
    rows: list[dict] = []
    cockpit_error = str(state.get("cost_contract_cockpit_error", "") or "")
    run_error = str(state.get("cost_contract_run_rate_error", "") or "")
    attribution_error = str(state.get("cost_contract_attribution_error", "") or "")
    service_error = str(state.get("cost_contract_service_lens_error", "") or "")

    _add_source_health_row(
        rows,
        "Warehouse metering",
        "Exact warehouse spend",
        _source_state(cockpit, cockpit_error, empty_state="Load Needed"),
        _loaded_rows(cockpit),
        "Current/prior movement loaded from fast warehouse metering summary or live Account Usage."
        if _loaded_rows(cockpit) else "Warehouse movement is available after Cost Cockpit refresh.",
        "Refresh cost detail before explaining usage movement.",
        "ACCOUNT_USAGE warehouse metering latency applies; summary refresh is preferred.",
    )
    _add_source_health_row(
        rows,
        "Run-rate and YOY",
        "Complete-day trend",
        _source_state(run_rate, run_error, empty_state="Load Needed"),
        _loaded_rows(run_rate),
        "7d, 30d, and prior-year complete-day windows are ready." if _loaded_rows(run_rate) else "Complete-day trend context is available after Cost Cockpit refresh.",
        "Use complete-day trend before declaring spikes or savings.",
        "Uses the fast summary first, then bounded live warehouse metering fallback.",
    )
    _add_source_health_row(
        rows,
        "Query attribution gap",
        "Execution-only query cost",
        _source_state(attribution, attribution_error, empty_state="No Rows"),
        _loaded_rows(attribution),
        "Warehouse credits have been reconciled to query-attributed or allocated execution cost."
        if _loaded_rows(attribution) else "No query attribution reconciliation rows loaded.",
        "Review idle/unallocated gap before routing query follow-up.",
        "QUERY_ATTRIBUTION_HISTORY can lag and excludes idle/serverless/AI costs.",
    )
    _add_source_health_row(
        rows,
        "Account service lens",
        "Warehouse, AI, serverless, storage, network",
        _source_state(service_lens, service_error, empty_state="No Rows"),
        _loaded_rows(service_lens),
        "Official account service cost rows are available." if _loaded_rows(service_lens) else "No service-type rows loaded.",
        "Separate warehouse resource-monitor signals from AI/serverless spend signals.",
        str(state.get("cost_contract_service_lens_source") or "SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY"),
    )
    _add_source_health_row(
        rows,
        "Action queue telemetry",
        "Cost action closure",
        "Ready" if _loaded_rows(queue) else "No Rows",
        _loaded_rows(queue),
        "Action queue telemetry is loaded." if _loaded_rows(queue) else "No cost action rows loaded for this role.",
        "Review open cost actions and later telemetry before treating optimizations as complete.",
        "OVERWATCH summary and action telemetry; no direct Snowflake billing scan.",
    )

    board = pd.DataFrame(rows)
    if board.empty:
        return {"score": 0, "ready": 0, "review": 0, "unavailable": 0}, board
    state_series = board["STATE"].fillna("").astype(str)
    unavailable = int(state_series.eq("Unavailable").sum())
    load_needed = int(state_series.eq("Load Needed").sum())
    review = int(state_series.isin(["On Demand", "No Rows"]).sum())
    ready = int(state_series.eq("Ready").sum())
    score = max(0, min(100, 100 - unavailable * 18 - load_needed * 12 - review * 4))
    board["_STATE_RANK"] = state_series.map({
        "Unavailable": 0,
        "Load Needed": 1,
        "On Demand": 2,
        "No Rows": 3,
        "Ready": 4,
    }).fillna(9)
    return {
        "score": int(score),
        "ready": ready,
        "review": review + load_needed,
        "unavailable": unavailable,
    }, board.sort_values(["_STATE_RANK", "SOURCE"]).drop(columns=["_STATE_RANK"], errors="ignore").reset_index(drop=True)


def _build_service_cost_lens_summary(service_lens: pd.DataFrame) -> dict:
    if service_lens is None or getattr(service_lens, "empty", True):
        return {
            "total_credits": 0.0,
            "non_warehouse_credits": 0.0,
            "ai_credits": 0.0,
            "serverless_credits": 0.0,
            "top_service": "No rows",
            "top_moving_service": "No movement",
            "top_moving_delta": 0.0,
            "categories": 0,
        }
    credits = pd.to_numeric(service_lens.get("CREDITS_BILLED", pd.Series(dtype=float)), errors="coerce").fillna(0)
    deltas = pd.to_numeric(service_lens.get("CREDIT_DELTA", pd.Series(dtype=float)), errors="coerce").fillna(0)
    category = service_lens.get("SERVICE_CATEGORY", pd.Series(dtype=str)).fillna("").astype(str)
    service = service_lens.get("SERVICE_TYPE", pd.Series(dtype=str)).fillna("").astype(str)
    total = safe_float(credits.sum())
    non_warehouse = safe_float(credits[~category.eq("Warehouse")].sum())
    ai = safe_float(credits[category.eq("AI / Cortex")].sum())
    serverless = safe_float(credits[category.eq("Serverless / Managed Compute")].sum())
    top_service = "No rows"
    if len(service_lens):
        top_service = str(service_lens.assign(_CREDITS=credits).sort_values("_CREDITS", ascending=False).iloc[0].get("SERVICE_TYPE") or "Unknown")
    top_moving_service = "No movement"
    top_moving_delta = 0.0
    if len(service_lens) and deltas.abs().sum() > 0:
        mover = service_lens.assign(_ABS_DELTA=deltas.abs()).sort_values("_ABS_DELTA", ascending=False).iloc[0]
        top_moving_service = str(mover.get("SERVICE_TYPE") or "Unknown")
        top_moving_delta = safe_float(mover.get("CREDIT_DELTA"))
    return {
        "total_credits": total,
        "non_warehouse_credits": non_warehouse,
        "ai_credits": ai,
        "serverless_credits": serverless,
        "top_service": top_service,
        "top_moving_service": top_moving_service,
        "top_moving_delta": top_moving_delta,
        "categories": int(category.nunique()),
    }


def _add_coverage_row(rows: list[dict], control: str, state: str, evidence: str, action: str, owner: str = "DBA / Cost owner") -> None:
    rows.append({
        "CONTROL": control,
        "STATE": state,
        "EVIDENCE": evidence,
        "NEXT_ACTION": action,
        "OWNER": owner,
    })


def _build_cost_control_coverage_board(
    *,
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
    state: dict | None = None,
) -> tuple[dict, pd.DataFrame]:
    state = state or st.session_state
    rows: list[dict] = []
    explorer = _state_frame(state, "df_cost_explorer_detail")
    chargeback = _state_frame(state, "df_chargeback")
    cortex_projection, cortex_exceptions = _loaded_cortex_state()

    _add_coverage_row(
        rows,
        "Exact warehouse metering",
        "Ready" if _has_columns(cockpit, ["CURRENT_CREDITS", "PRIOR_CREDITS"]) else "Load Needed",
        "Cockpit has exact current/prior warehouse credits." if _has_columns(cockpit, ["CURRENT_CREDITS", "PRIOR_CREDITS"]) else "Exact warehouse movement is available after Cost Cockpit refresh.",
        "Refresh cost detail before explaining any usage movement.",
    )
    _add_coverage_row(
        rows,
        "7-day average and YOY",
        "Ready" if _has_columns(run_rate, ["AVG_DAILY_7D", "YOY_7D_PCT", "YOY_30D_PCT"]) else "Load Needed",
        "Run-rate lens has complete-day 7d average and prior-year comparison." if _has_columns(run_rate, ["AVG_DAILY_7D", "YOY_7D_PCT", "YOY_30D_PCT"]) else "Run-rate and YOY trend context is available after refresh.",
        "Refresh cost detail to populate complete-day run-rate and YOY telemetry.",
    )
    _add_coverage_row(
        rows,
        "Company and environment split",
        "Ready" if _has_columns(chargeback, ["COMPANY", "ENVIRONMENT"]) or _has_columns(explorer, ["COMPANY", "ENVIRONMENT_ROLLUP"]) else "Review",
        "Chargeback/Cost Explorer includes company and environment dimensions." if _has_columns(chargeback, ["COMPANY", "ENVIRONMENT"]) or _has_columns(explorer, ["COMPANY", "ENVIRONMENT_ROLLUP"]) else "Company/environment attribution is available after refresh.",
        "Load Cost Explorer or Chargeback before defending ALFA/Trexis or PROD/DEV allocation.",
    )
    _add_coverage_row(
        rows,
        "Trexis role/user boundary",
        "Ready" if _has_columns(explorer, ["ROLE_NAME", "USER_NAME"]) else "Review",
        (
            "User-scoped views can apply TRXS role/user monikers when role and user dimensions are loaded."
            if _has_columns(explorer, ["ROLE_NAME", "USER_NAME"]) else
            "Trexis user segregation is available after role/user Cost Explorer detail is loaded."
        ),
        "Use role/user detail for Cortex and user-driven cost reviews; keep account-wide service totals as reconciliation context.",
    )
    _add_coverage_row(
        rows,
        "Database and DEV rollup",
        "Ready" if _has_columns(chargeback, ["DATABASE_NAME"]) or _has_columns(explorer, ["DATABASE_NAME"]) else "Review",
        "Database-attributed cost is visible and labeled Allocated / Estimated." if _has_columns(chargeback, ["DATABASE_NAME"]) or _has_columns(explorer, ["DATABASE_NAME"]) else "Database-level attribution has not been loaded.",
        "Use Chargeback for PROD, DEV_ALL, and individual DEV database cost views.",
    )
    _add_coverage_row(
        rows,
        "Role, user, and department drivers",
        "Ready" if _has_columns(explorer, ["ROLE_NAME", "USER_NAME", "DEPARTMENT"]) else "Review",
        "Cost Explorer detail includes role, user, and department dimensions." if _has_columns(explorer, ["ROLE_NAME", "USER_NAME", "DEPARTMENT"]) else "Role/user/department cost drivers are available after refresh.",
        "Load Cost Explorer and sort by estimated cost before assigning optimization work.",
    )

    open_cost_queue = pd.DataFrame()
    if isinstance(queue, pd.DataFrame) and not queue.empty:
        category = queue.get("CATEGORY", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
        status = queue.get("STATUS", pd.Series(["New"] * len(queue), index=queue.index)).fillna("New").astype(str).str.title()
        open_cost_queue = queue[category.str.contains("COST|CHARGEBACK|CORTEX", na=False) & ~status.isin(["Fixed", "Ignored"])]
    owner_source = open_cost_queue.get("OWNER_SOURCE", pd.Series(dtype=str)).fillna("").astype(str).str.strip() if not open_cost_queue.empty else pd.Series(dtype=str)
    owner_ready = int(owner_source.ne("").sum()) if not owner_source.empty else 0
    _add_coverage_row(
        rows,
        "Owned cost action queue",
        "Ready" if not open_cost_queue.empty and owner_ready == len(open_cost_queue) else "Review" if not open_cost_queue.empty else "No Rows",
        f"{len(open_cost_queue):,} open cost action(s); {owner_ready:,} have route-source telemetry.",
        "Route cost findings through the action queue with route, due date, impact status, and closure telemetry.",
    )
    _add_coverage_row(
        rows,
        "Cortex cost guardrail",
        "Ready" if cortex_projection > 0 or cortex_exceptions > 0 else "No Rows",
        f"Projected Cortex spend ${cortex_projection:,.0f}/30d with {cortex_exceptions:,} exception(s).",
        "Open Cortex Spend when projection or exception count is non-zero.",
    )
    _add_coverage_row(
        rows,
        "Shared-cost disclosure",
        "Ready",
        "Warehouse totals are exact; user/query/database chargeback is explicitly labeled Allocated / Estimated.",
        "Keep shared warehouse and no-database-context costs out of exact PROD/DEV claims until tag telemetry exists.",
    )

    board = pd.DataFrame(rows)
    if board.empty:
        return {"score": 0, "ready": 0, "review": 0, "load_needed": 0}, board
    load_needed = int(board["STATE"].eq("Load Needed").sum())
    review = int(board["STATE"].eq("Review").sum())
    ready = int(board["STATE"].isin(["Ready", "No Rows"]).sum())
    score = max(0, min(100, 100 - load_needed * 12 - review * 6))
    board["_STATE_RANK"] = board["STATE"].map({"Load Needed": 0, "Review": 1, "No Rows": 2, "Ready": 3}).fillna(9)
    return {
        "score": int(score),
        "ready": ready,
        "review": review,
        "load_needed": load_needed,
    }, board.sort_values(["_STATE_RANK", "CONTROL"]).drop(columns=["_STATE_RANK"], errors="ignore")


def _build_cost_allocation_trust_board(
    *,
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
    state: dict | None = None,
) -> tuple[dict, pd.DataFrame]:
    """Classify cost telemetry as exact, allocated/estimated, or not yet defensible."""
    state = state or st.session_state
    rows: list[dict] = []
    explorer = _state_frame(state, "df_cost_explorer_detail")
    chargeback = _state_frame(state, "df_chargeback")

    def add(control: str, trust: str, evidence: str, action: str, owner: str = "DBA / Cost owner") -> None:
        rows.append({
            "CONTROL": control,
            "TRUST_STATE": trust,
            "EVIDENCE": evidence,
            "NEXT_ACTION": action,
            "OWNER": owner,
        })

    exact_loaded = _has_columns(cockpit, ["CURRENT_CREDITS", "PRIOR_CREDITS"])
    run_rate_loaded = _has_columns(run_rate, ["AVG_DAILY_7D", "YOY_7D_PCT", "YOY_30D_PCT"])
    add(
        "Contract and warehouse totals",
        "Exact" if exact_loaded and run_rate_loaded else "Load Needed",
        "Warehouse metering and complete-day run-rate/YOY are loaded." if exact_loaded and run_rate_loaded else "Exact warehouse totals or complete-day run-rate telemetry is missing.",
        "Refresh cost detail before defending run-rate pace, 7-day average, or YOY movement.",
    )

    company_env_loaded = _has_columns(chargeback, ["COMPANY", "ENVIRONMENT"]) or _has_columns(explorer, ["COMPANY", "ENVIRONMENT_ROLLUP"])
    add(
        "Company and environment view",
        "Allocated/Estimated" if company_env_loaded else "Review",
        "Company/environment split is present; database-attributed cost remains allocated where warehouse usage is shared." if company_env_loaded else "Company/environment allocation is available after refresh.",
        "Load Cost Explorer or Chargeback before explaining ALFA/Trexis or PROD/DEV cost movement.",
    )
    add(
        "Trexis role/user boundary",
        "Allocated/Estimated" if _has_columns(explorer, ["ROLE_NAME", "USER_NAME"]) else "Review",
        (
            "Role/user cost rows are available; Trexis users can be separated by TRXS role membership and TRXS user monikers where telemetry exposes them."
            if _has_columns(explorer, ["ROLE_NAME", "USER_NAME"]) else
            "Role/user cost rows are available after Cost Explorer refresh."
        ),
        "Use this for user-driven cost and Cortex review; do not split account-wide Snowflake services without an allocation basis.",
    )

    db_loaded = _has_columns(chargeback, ["DATABASE_NAME"]) or _has_columns(explorer, ["DATABASE_NAME"])
    allocation_confidence = pd.Series(dtype=str)
    if _has_columns(chargeback, ["ALLOCATION_CONFIDENCE"]):
        allocation_confidence = chargeback["ALLOCATION_CONFIDENCE"].fillna("").astype(str)
    elif _has_columns(explorer, ["ALLOCATION_CONFIDENCE"]):
        allocation_confidence = explorer["ALLOCATION_CONFIDENCE"].fillna("").astype(str)
    estimated_rows = int(allocation_confidence.str.contains("ESTIMATED|ALLOCATED|SHARED", case=False, regex=True).sum()) if len(allocation_confidence) else 0
    add(
        "Database attribution",
        "Allocated/Estimated" if db_loaded else "Review",
        (
            f"Database drilldown loaded; {estimated_rows:,} row(s) explicitly carry allocated/shared/estimated measurement."
            if db_loaded else "Database attribution is available after refresh."
        ),
        "Use database views for chargeback directionally; do not present shared warehouse database spend as exact.",
    )

    human_driver_loaded = _has_columns(explorer, ["ROLE_NAME", "USER_NAME", "DEPARTMENT"])
    add(
        "Role, user, department drivers",
        "Allocated/Estimated" if human_driver_loaded else "Review",
        "Human and department cost drivers are available for prioritization." if human_driver_loaded else "Role/user/department drilldown is available after refresh.",
        "Load Cost Explorer before assigning optimization work to teams or departments.",
    )

    no_database_rows = 0
    for frame in (chargeback, explorer):
        if _has_columns(frame, ["DATABASE_NAME"]):
            no_database_rows += int(frame["DATABASE_NAME"].fillna("").astype(str).str.strip().eq("").sum())
    add(
        "Shared and no-database spend",
        "Allocated/Estimated" if no_database_rows else "Ready" if db_loaded else "Review",
        (
            f"{no_database_rows:,} loaded row(s) have no database context and must stay outside exact PROD/DEV claims."
            if no_database_rows else "No loaded database-attribution rows are missing database context." if db_loaded else "Database-attribution rows are available after refresh."
        ),
        "Keep no-database, login-only, and shared-service spend labeled allocated/estimated until tag telemetry exists.",
    )

    open_cost_queue = pd.DataFrame()
    if isinstance(queue, pd.DataFrame) and not queue.empty:
        category = queue.get("CATEGORY", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
        status = queue.get("STATUS", pd.Series(["New"] * len(queue), index=queue.index)).fillna("New").astype(str).str.title()
        open_cost_queue = queue[category.str.contains("COST|CHARGEBACK|CORTEX", na=False) & ~status.isin(["Fixed", "Ignored"])].copy()
    owner_ready = 0
    verification_ready = 0
    if not open_cost_queue.empty:
        owner_ready = int(open_cost_queue.get("OWNER_SOURCE", pd.Series(dtype=str)).fillna("").astype(str).str.strip().ne("").sum())
        verification_ready = int(
            open_cost_queue.get("VERIFICATION_STATUS", pd.Series(dtype=str)).fillna("").astype(str).str.upper().str.contains("VERIFIED|PASSED|COMPLETE", regex=True).sum()
        )
    add(
        "Optimization closure trust",
        "Ready" if not open_cost_queue.empty and owner_ready == len(open_cost_queue) and verification_ready > 0 else "Review" if not open_cost_queue.empty else "No Rows",
        f"{len(open_cost_queue):,} open cost action(s); {owner_ready:,} routed; {verification_ready:,} measured/completed.",
        "Treat impact as directional until the next complete usage window confirms movement.",
    )

    board = pd.DataFrame(rows)
    if board.empty:
        return {"score": 0, "exact": 0, "estimated": 0, "review": 0, "load_needed": 0}, board
    exact = int(board["TRUST_STATE"].isin(["Exact", "Ready", "No Rows"]).sum())
    estimated = int(board["TRUST_STATE"].eq("Allocated/Estimated").sum())
    review = int(board["TRUST_STATE"].eq("Review").sum())
    load_needed = int(board["TRUST_STATE"].eq("Load Needed").sum())
    score = max(0, min(100, 100 - load_needed * 14 - review * 7 - estimated * 2))
    board["_TRUST_RANK"] = board["TRUST_STATE"].map({
        "Load Needed": 0,
        "Review": 1,
        "Allocated/Estimated": 2,
        "No Rows": 3,
        "Ready": 4,
        "Exact": 5,
    }).fillna(9)
    return {
        "score": int(score),
        "exact": exact,
        "estimated": estimated,
        "review": review,
        "load_needed": load_needed,
    }, board.sort_values(["_TRUST_RANK", "CONTROL"]).drop(columns=["_TRUST_RANK"], errors="ignore").reset_index(drop=True)


def _build_cost_drilldown_command_map(
    *,
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
    state: dict | None = None,
) -> tuple[dict, pd.DataFrame]:
    """Expose which cost drilldowns are defensible from already-loaded data."""
    state = state or st.session_state
    explorer = _state_frame(state, "df_cost_explorer_detail")
    chargeback = _state_frame(state, "df_chargeback")
    cortex_projection, cortex_exceptions = _loaded_cortex_state()

    rows: list[dict] = []

    def loaded_rows(*frames: pd.DataFrame) -> int:
        return sum(len(frame) for frame in frames if isinstance(frame, pd.DataFrame) and not frame.empty)

    def add(
        grain: str,
        state_value: str,
        trust: str,
        rows_loaded: int,
        metric: str,
        next_action: str,
        workflow: str,
        rank: int,
    ) -> None:
        rows.append({
            "COMMAND_PRIORITY": f"P{rank}",
            "DRILLDOWN": grain,
            "STATE": state_value,
            "TRUST": trust,
            "ROWS_LOADED": rows_loaded,
            "PRIMARY_METRIC": metric,
            "NEXT_ACTION": next_action,
            "WORKFLOW": workflow,
            "_RANK": rank,
        })

    current_credits = safe_float(cockpit.iloc[0].get("CURRENT_CREDITS")) if isinstance(cockpit, pd.DataFrame) and not cockpit.empty else 0.0
    prior_credits = safe_float(cockpit.iloc[0].get("PRIOR_CREDITS")) if isinstance(cockpit, pd.DataFrame) and not cockpit.empty else 0.0
    top_wh = str(cockpit.iloc[0].get("TOP_INCREASE_WAREHOUSE") or "") if isinstance(cockpit, pd.DataFrame) and not cockpit.empty else ""
    exact_loaded = _has_columns(cockpit, ["CURRENT_CREDITS", "PRIOR_CREDITS"])
    add(
        "Warehouse usage movement",
        "Ready" if exact_loaded else "Load Needed",
        "Exact",
        loaded_rows(cockpit),
        f"{current_credits:,.2f} current credits; {prior_credits:,.2f} prior credits",
        f"Explain top warehouse movement first{f': {top_wh}' if top_wh else ''}.",
        "Cost by Warehouse",
        0 if exact_loaded else 1,
    )

    run_loaded = _has_columns(run_rate, ["AVG_DAILY_7D", "YOY_7D_PCT", "YOY_30D_PCT"])
    add(
        "7-day average and YOY pace",
        "Ready" if run_loaded else "Load Needed",
        "Exact",
        loaded_rows(run_rate),
        (
            f"7d avg {safe_float(run_rate.iloc[0].get('AVG_DAILY_7D')):,.2f} credits; "
            f"YOY7 {safe_float(run_rate.iloc[0].get('YOY_7D_PCT')):+.1f}%"
            if run_loaded and not run_rate.empty else "No run-rate telemetry loaded"
        ),
        "Use complete-day 7d average and YOY before calling a spike real.",
        "Burn Rate & Forecast",
        0 if run_loaded else 1,
    )

    company_loaded = _has_columns(chargeback, ["COMPANY", "ENVIRONMENT"]) or _has_columns(explorer, ["COMPANY", "ENVIRONMENT_ROLLUP"])
    add(
        "Company and environment",
        "Ready" if company_loaded else "Review",
        "Allocated/Estimated",
        loaded_rows(chargeback, explorer),
        "ALFA/Trexis plus PROD/DEV split" if company_loaded else "No company/environment rows loaded",
        "Use this for chargeback direction; keep shared warehouse disclosure visible.",
        "Chargeback / Company Split",
        2 if company_loaded else 3,
    )

    db_loaded = _has_columns(chargeback, ["DATABASE_NAME"]) or _has_columns(explorer, ["DATABASE_NAME"])
    no_db_rows = 0
    for frame in (chargeback, explorer):
        if _has_columns(frame, ["DATABASE_NAME"]):
            no_db_rows += int(frame["DATABASE_NAME"].fillna("").astype(str).str.strip().eq("").sum())
    add(
        "Database, DEV rollup, no-database spend",
        "Ready" if db_loaded else "Review",
        "Allocated/Estimated",
        loaded_rows(chargeback, explorer),
        f"{no_db_rows:,} no-database row(s)" if db_loaded else "Database rows are available after refresh",
        "Show PROD, DEV_ALL, individual DEV databases, and keep no-database spend out of exact claims.",
        "Chargeback / Company Split",
        2 if db_loaded else 3,
    )

    human_loaded = _has_columns(explorer, ["ROLE_NAME", "USER_NAME", "DEPARTMENT"])
    add(
        "Role, user, department",
        "Ready" if human_loaded else "Review",
        "Allocated/Estimated",
        loaded_rows(explorer),
        "Role/user/department drivers ready" if human_loaded else "Human driver rows are available after refresh",
        "Sort by estimated dollars before assigning work to a department or user.",
        "Cost by User / Role",
        2 if human_loaded else 3,
    )

    open_cost_queue = pd.DataFrame()
    if isinstance(queue, pd.DataFrame) and not queue.empty:
        mask = _cost_action_mask(queue)
        open_cost_queue = queue[mask].copy()
    verified = 0
    if not open_cost_queue.empty:
        verified = int(
            open_cost_queue.get("VERIFICATION_STATUS", pd.Series(dtype=str)).fillna("").astype(str).str.upper().str.contains(
                "VERIFIED|PASSED|COMPLETE",
                regex=True,
            ).sum()
        )
    add(
        "Optimization closure status",
        "Ready" if not open_cost_queue.empty and verified else "Review" if not open_cost_queue.empty else "No Rows",
        "Measured after change",
        len(open_cost_queue),
        f"{verified:,} measured/completed action(s)",
        "Treat impact as directional until the next complete usage window confirms movement.",
        "Cost Recommendations",
        2 if verified else 3,
    )

    add(
        "Cortex Spend",
        "Ready" if cortex_projection > 0 or cortex_exceptions > 0 else "No Rows",
        "Allocated/Estimated",
        cortex_exceptions,
        f"${cortex_projection:,.0f}/30d projection; {cortex_exceptions:,} exception(s)",
        "Review first/last usage, user attribution, and projected token-credit spend.",
        "Cost by User / Role",
        2 if cortex_projection > 0 or cortex_exceptions > 0 else 4,
    )

    board = pd.DataFrame(rows)
    if board.empty:
        return {"ready": 0, "review": 0, "load_needed": 0, "estimated": 0}, board
    ready = int(board["STATE"].isin(["Ready", "No Rows"]).sum())
    review = int(board["STATE"].eq("Review").sum())
    load_needed = int(board["STATE"].eq("Load Needed").sum())
    estimated = int(board["TRUST"].eq("Allocated/Estimated").sum())
    return {
        "ready": ready,
        "review": review,
        "load_needed": load_needed,
        "estimated": estimated,
    }, board.sort_values(["_RANK", "DRILLDOWN"]).drop(columns=["_RANK"], errors="ignore").reset_index(drop=True)


def _build_cost_decomposition_board(
    *,
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
    state: dict | None = None,
) -> tuple[dict, pd.DataFrame]:
    """Summarize the highest-value cost decomposition paths already visible in the session."""
    state = state or st.session_state
    explorer = _state_frame(state, "df_cost_explorer_detail")
    chargeback = _state_frame(state, "df_chargeback")
    rows: list[dict] = []

    def add(driver: str, status: str, trust: str, evidence: str, next_action: str) -> None:
        rows.append({
            "DRIVER": driver,
            "STATUS": status,
            "TRUST": trust,
            "EVIDENCE": evidence,
            "NEXT_ACTION": next_action,
        })

    exact_loaded = _has_columns(cockpit, ["CURRENT_CREDITS", "PRIOR_CREDITS"])
    run_loaded = _has_columns(run_rate, ["AVG_DAILY_7D", "YOY_7D_PCT", "YOY_30D_PCT"])
    company_loaded = _has_columns(chargeback, ["COMPANY", "ENVIRONMENT"]) or _has_columns(explorer, ["COMPANY", "ENVIRONMENT_ROLLUP"])
    db_loaded = _has_columns(chargeback, ["DATABASE_NAME"]) or _has_columns(explorer, ["DATABASE_NAME"])
    human_loaded = _has_columns(explorer, ["ROLE_NAME", "USER_NAME", "DEPARTMENT"])

    open_cost_queue = pd.DataFrame()
    if isinstance(queue, pd.DataFrame) and not queue.empty:
        open_cost_queue = queue[_cost_action_mask(queue)].copy()

    if exact_loaded:
        current_credits = safe_float(cockpit.iloc[0].get("CURRENT_CREDITS"))
        prior_credits = safe_float(cockpit.iloc[0].get("PRIOR_CREDITS"))
        delta = current_credits - prior_credits
        add(
            "Warehouse movement",
            "Ready",
            "Exact",
            f"Current credits {current_credits:,.2f} vs prior {prior_credits:,.2f} ({delta:+,.2f}).",
            "Start with the warehouse that moved most before blaming user, query, or database behavior.",
        )
    else:
        add(
            "Warehouse movement",
            "Load Needed",
            "Review",
            "Exact warehouse metering is available after refresh.",
            "Load the Cost Control Cockpit before explaining usage movement.",
        )

    if run_loaded:
        avg_7d = safe_float(run_rate.iloc[0].get("AVG_DAILY_7D"))
        yoy_7d_pct = safe_float(run_rate.iloc[0].get("YOY_7D_PCT"))
        yoy_30d_pct = safe_float(run_rate.iloc[0].get("YOY_30D_PCT"))
        add(
            "7-day average and YOY",
            "Ready",
            "Exact",
            f"7d avg {avg_7d:,.2f} credits/day; YOY 7d {yoy_7d_pct:+.1f}%; YOY 30d {yoy_30d_pct:+.1f}%.",
            "Use complete-day average and YOY before calling a spike or dip real.",
        )
    else:
        add(
            "7-day average and YOY",
            "Load Needed",
            "Review",
            "Run-rate trend context is available after refresh.",
            "Reload the run-rate lens before making trend claims.",
        )

    add(
        "Company and environment split",
        "Ready" if company_loaded else "Review",
        "Allocated/Estimated",
        "Company/environment split is present." if company_loaded else "Company/environment attribution is available after refresh.",
        "Use this for ALFA/Trexis and PROD/DEV direction, not as exact allocation.",
    )
    add(
        "Database, DEV rollup, no-database spend",
        "Ready" if db_loaded else "Review",
        "Allocated/Estimated",
        "Database-attributed rows are present." if db_loaded else "Database attribution is available after refresh.",
        "Show PROD, DEV_ALL, individual DEV databases, and keep shared/no-db spend labeled allocated or estimated.",
    )
    add(
        "Role, user, department drivers",
        "Ready" if human_loaded else "Review",
        "Allocated/Estimated",
        "Role, user, and department dimensions are available." if human_loaded else "Human driver rows are available after refresh.",
        "Sort by estimated dollars before assigning optimization work.",
    )
    add(
        "Open cost action queue",
        "Ready" if not open_cost_queue.empty else "No Rows",
        "Measured after change" if not open_cost_queue.empty else "No Rows",
        f"{len(open_cost_queue):,} open cost action(s)." if not open_cost_queue.empty else "No cost actions are loaded.",
        "Use the queue to close savings with route, status, and post-period measurement.",
    )

    board = pd.DataFrame(rows)
    if board.empty:
        return {"score": 0, "ready": 0, "review": 0}, board
    ready = int(board["STATUS"].eq("Ready").sum())
    review = int(board["STATUS"].eq("Review").sum()) + int(board["STATUS"].eq("Load Needed").sum())
    exact = int(board["TRUST"].eq("Exact").sum())
    score = max(0, min(100, 100 - review * 12 - max(0, exact - 2) * 1))
    board["_RANK"] = board["STATUS"].map({"Load Needed": 0, "Review": 1, "Ready": 2, "No Rows": 3}).fillna(9)
    return {
        "score": int(score),
        "ready": ready,
        "review": review,
    }, board.sort_values(["_RANK", "DRIVER"]).drop(columns=["_RANK"], errors="ignore").reset_index(drop=True)


def _cost_command_severity_rank(value: object) -> int:
    return {"Critical": 0, "High": 1, "Medium": 2, "Watch": 3, "Info": 4}.get(str(value or "Info"), 9)


def _first_frame_value(frame: pd.DataFrame | None, column: str, default: object = "") -> object:
    if frame is None or getattr(frame, "empty", True) or column not in frame.columns:
        return default
    return frame.iloc[0].get(column, default)


def _build_cost_spike_root_cause_board(
    *,
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
    credit_price: float,
    state: dict | None = None,
) -> tuple[dict, pd.DataFrame]:
    state = state or st.session_state
    explorer = _state_frame(state, "df_cost_explorer_detail")
    chargeback = _state_frame(state, "df_chargeback")
    current_credits = safe_float(_first_frame_value(cockpit, "CURRENT_CREDITS", 0))
    prior_credits = safe_float(_first_frame_value(cockpit, "PRIOR_CREDITS", 0))
    top_wh = str(_first_frame_value(cockpit, "TOP_INCREASE_WAREHOUSE", "On demand") or "On demand")
    top_delta = safe_float(_first_frame_value(cockpit, "TOP_INCREASE_CREDITS", 0))
    delta_pct = ((current_credits - prior_credits) / prior_credits * 100) if prior_credits > 0 else 0.0
    avg_7d = safe_float(_first_frame_value(run_rate, "AVG_DAILY_7D", 0))
    avg_30d = safe_float(_first_frame_value(run_rate, "AVG_DAILY_30D", 0))
    pct_vs_30d = _first_frame_value(run_rate, "PCT_VS_30D_AVG", None)
    pct_vs_30d_float = safe_float(pct_vs_30d) if pct_vs_30d is not None and not pd.isna(pct_vs_30d) else 0.0
    yoy_7d = _first_frame_value(run_rate, "YOY_7D_PCT", None)
    yoy_7d_float = safe_float(yoy_7d) if yoy_7d is not None and not pd.isna(yoy_7d) else 0.0
    open_cost_queue = _open_cost_action_frame(queue)
    cortex_projection, cortex_exceptions = _loaded_cortex_state()

    rows: list[dict] = []

    def add(
        severity: str,
        driver: str,
        entity: str,
        signal: str,
        evidence: str,
        confidence: str,
        trust: str,
        next_action: str,
        proof: str,
        route: str,
        value: float,
        rank: int,
    ) -> None:
        rows.append({
            "SEVERITY": severity,
            "DRIVER": driver,
            "ENTITY": entity,
            "ROOT_CAUSE_SIGNAL": signal,
            "EVIDENCE": evidence,
            "CONFIDENCE": confidence,
            "TRUST": trust,
            "NEXT_ACTION": next_action,
            "PROOF_REQUIRED": proof,
            "ROUTE": route,
            "VALUE_AT_RISK_USD": round(safe_float(value), 2),
            "_RANK": rank,
        })

    movement_severity = "Critical" if delta_pct >= 50 and top_delta > 0 else "High" if top_delta > 0 or delta_pct >= 20 else "Info"
    add(
        movement_severity,
        "Warehouse movement",
        top_wh,
        "Top warehouse delta",
        f"{top_wh}: {top_delta:+,.2f} credits; window ${credits_to_dollars(current_credits, credit_price):,.0f} vs prior ${credits_to_dollars(prior_credits, credit_price):,.0f} ({delta_pct:+.1f}%).",
        "High" if top_delta > 0 else "Medium",
        "Exact warehouse metering",
        "Start here. Confirm owner demand, task/query mix, size/auto-suspend changes, and monitor coverage for this warehouse.",
        "WAREHOUSE_METERING_HISTORY current/prior window and top delta.",
        "Cost & Contract > Cost by Warehouse",
        max(credits_to_dollars(top_delta, credit_price), credits_to_dollars(current_credits - prior_credits, credit_price), 0),
        0,
    )
    trend_severity = "High" if pct_vs_30d_float >= 20 or yoy_7d_float >= 25 else "Medium" if pct_vs_30d_float >= 10 or yoy_7d_float >= 15 else "Info"
    add(
        trend_severity,
        "Complete-day trend",
        top_wh,
        "7d / 30d / YOY baseline",
        f"7d avg {avg_7d:,.2f} cr/day vs 30d {avg_30d:,.2f}; 7d vs 30d {pct_vs_30d_float:+.1f}%; YOY7 {yoy_7d_float:+.1f}%.",
        "High" if _has_columns(run_rate, ["AVG_DAILY_7D", "AVG_DAILY_30D"]) else "Low",
        "Exact when run-rate lens loaded",
        "Do not escalate from same-day partial metering; use complete-day trend to decide whether this is a real spike.",
        "Cost run-rate lens with complete-day 7d, 30d, and prior-year rows.",
        "Cost & Contract > Burn Rate & Forecast",
        credits_to_dollars(abs(top_delta), credit_price),
        1,
    )

    company_driver = _top_loaded_cost_driver(chargeback if not chargeback.empty else explorer, ["COMPANY", "ENVIRONMENT", "ENVIRONMENT_ROLLUP"], credit_price=credit_price)
    add(
        "Medium" if company_driver["entity"] else "Watch",
        "Company / environment attribution",
        company_driver["entity"] or "On demand",
        "Chargeback direction",
        (
            f"Top {company_driver['dimension']} is {company_driver['entity']} at ${company_driver['value_usd']:,.0f} across {company_driver['rows']:,} row(s)."
            if company_driver["entity"] else "Company/environment cost attribution is available after refresh."
        ),
        "Medium" if company_driver["entity"] else "Low",
        "Allocated / Estimated",
        "Use ALFA/Trexis and PROD/DEV attribution to assign ownership, but keep shared warehouse disclosure attached.",
        "Cost Explorer or Chargeback rows with company/environment dimensions and allocation measurement.",
        "Cost & Contract > Chargeback / Company Split",
        company_driver["value_usd"],
        2,
    )

    db_driver = _top_loaded_cost_driver(chargeback if not chargeback.empty else explorer, ["DATABASE_NAME", "ENVIRONMENT", "ENVIRONMENT_ROLLUP"], credit_price=credit_price)
    add(
        "Medium" if db_driver["entity"] else "Watch",
        "Database / DEV rollup",
        db_driver["entity"] or "On demand",
        "Database-attributed cost candidate",
        (
            f"Top {db_driver['dimension']} is {db_driver['entity']} at ${db_driver['value_usd']:,.0f} across {db_driver['rows']:,} row(s)."
            if db_driver["entity"] else "Database-level attribution is available after refresh."
        ),
        "Medium" if db_driver["entity"] else "Low",
        "Allocated / Estimated",
        "Drill into PROD, DEV_ALL, and individual DEV database views before assigning database ownership.",
        "Query allocation, tags, and no-database/shared allocation measurement.",
        "Cost & Contract > Chargeback / Company Split",
        db_driver["value_usd"],
        3,
    )

    human_driver = _top_loaded_cost_driver(explorer, ["ROLE_NAME", "USER_NAME", "DEPARTMENT"], credit_price=credit_price)
    add(
        "Medium" if human_driver["entity"] else "Watch",
        "Role / user / department",
        human_driver["entity"] or "On demand",
        "Human ownership candidate",
        (
            f"Top {human_driver['dimension']} is {human_driver['entity']} at ${human_driver['value_usd']:,.0f} across {human_driver['rows']:,} row(s)."
            if human_driver["entity"] else "Role, user, and department drilldown is available after refresh."
        ),
        "Medium" if human_driver["entity"] else "Low",
        "Allocated / Estimated",
        "Assign optimization work only after the cost row has role/user/department telemetry and route context.",
        "Cost Explorer detail with role, user, department, query count, and allocation measurement.",
        "Cost & Contract > Cost by User / Role",
        human_driver["value_usd"],
        4,
    )

    savings = (
        safe_float(pd.to_numeric(open_cost_queue.get("EST_MONTHLY_SAVINGS", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        if not open_cost_queue.empty else 0.0
    )
    add(
        "High" if savings > 0 else "Info",
        "Open savings queue",
        f"{len(open_cost_queue):,} open cost action(s)",
        "Existing remediation candidates",
        f"${savings:,.0f}/mo estimated savings loaded; keep savings estimated until measured.",
        "Medium" if not open_cost_queue.empty else "Low",
        "Measured after change",
        "Work measured actions first; reject fixed rows without post-period measurement.",
        "OVERWATCH_ACTION_QUEUE route, ticket, baseline/current values, and scheduled status.",
        "Cost & Contract > Cost Recommendations",
        savings,
        5,
    )
    add(
        "High" if cortex_projection > 0 or cortex_exceptions > 0 else "Info",
        "AI / Cortex usage",
        "Cortex",
        "AI spend or quota candidate",
        f"Projection ${cortex_projection:,.0f}/30d; {cortex_exceptions:,} exception(s).",
        "Medium" if cortex_projection > 0 or cortex_exceptions > 0 else "Low",
        "Allocated / Estimated",
        "Use Cost by User / Role for spend ownership, then open Cortex Spend under Advanced Cost Tools only when model-level evidence is needed.",
        "Cortex usage history, user attribution, shared AI spend threshold, and per-user quota action rows.",
        "Cost & Contract > Cost by User / Role",
        cortex_projection,
        6,
    )

    board = pd.DataFrame(rows)
    if board.empty:
        return {"score": 0, "critical_high": 0, "top_driver": "No loaded root-cause telemetry"}, board
    board["_SEVERITY_RANK"] = board["SEVERITY"].apply(_cost_command_severity_rank)
    board = board.sort_values(["_SEVERITY_RANK", "VALUE_AT_RISK_USD", "_RANK"], ascending=[True, False, True])
    critical_high = int(board["SEVERITY"].isin(["Critical", "High"]).sum())
    candidate = int(board["CONFIDENCE"].isin(["Low", "Medium"]).sum())
    score = max(0, min(100, 100 - critical_high * 10 - candidate * 4))
    top = board.iloc[0]
    return {
        "score": int(score),
        "critical_high": critical_high,
        "candidate": candidate,
        "top_driver": str(top.get("DRIVER") or "Cost root cause"),
        "top_entity": str(top.get("ENTITY") or "Unknown"),
        "top_action": str(top.get("NEXT_ACTION") or "Open Cost & Contract drilldown."),
    }, board.drop(columns=["_SEVERITY_RANK", "_RANK"], errors="ignore").reset_index(drop=True)


def _build_change_cost_correlation_board(
    *,
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    state: dict | None = None,
) -> tuple[dict, pd.DataFrame]:
    state = state or st.session_state
    changes = _state_frame(state, "change_drift_exceptions")
    operability = _state_frame(state, "change_control_operability_fact")
    current_credits = safe_float(_first_frame_value(cockpit, "CURRENT_CREDITS", 0))
    prior_credits = safe_float(_first_frame_value(cockpit, "PRIOR_CREDITS", 0))
    top_wh = str(_first_frame_value(cockpit, "TOP_INCREASE_WAREHOUSE", "") or "").strip()
    top_delta = safe_float(_first_frame_value(cockpit, "TOP_INCREASE_CREDITS", 0))
    pct_vs_30d = _first_frame_value(run_rate, "PCT_VS_30D_AVG", None)
    pct_vs_30d_float = safe_float(pct_vs_30d) if pct_vs_30d is not None and not pd.isna(pct_vs_30d) else 0.0
    spike_signal = top_delta > 0 or current_credits > prior_credits or pct_vs_30d_float >= 10
    rows: list[dict] = []

    def add(
        severity: str,
        correlation: str,
        entity: str,
        cost_signal: str,
        change_signal: str,
        evidence: str,
        next_action: str,
        proof: str,
        route: str,
        rank: int,
    ) -> None:
        rows.append({
            "SEVERITY": severity,
            "CORRELATION": correlation,
            "ENTITY": entity,
            "COST_SIGNAL": cost_signal,
            "CHANGE_SIGNAL": change_signal,
            "EVIDENCE": evidence,
            "NEXT_ACTION": next_action,
            "PROOF_REQUIRED": proof,
            "ROUTE": route,
            "_RANK": rank,
        })

    if changes.empty:
        add(
            "Medium" if spike_signal else "Watch",
            "Change correlation pending",
            top_wh or "Cost scope",
            f"Top warehouse delta {top_delta:+,.2f} credits; 7d vs 30d {pct_vs_30d_float:+.1f}%.",
            "No Security Monitoring change exceptions are ready for this scope.",
            "Cost movement cannot be cleared of change-correlation risk until Security Monitoring is reviewed for the same scope.",
            "Refresh Security Monitoring change telemetry, then compare warehouse, query, task/procedure, grant, and policy events to the cost spike.",
            "Security Monitoring change exceptions plus Cost Cockpit/run-rate telemetry for the same company/environment window.",
            "Security Monitoring > Object and access changes",
            0,
        )
    else:
        view = changes.copy()
        text_cols = []
        for column in ["ENTITY", "WAREHOUSE_NAME", "QUERY_ID", "FINDING_TYPE", "QUERY_TAG", "USER_NAME", "ROLE_NAME"]:
            if column in view.columns:
                text_cols.append(column)
        combined = view[text_cols].fillna("").astype(str).agg(" | ".join, axis=1) if text_cols else pd.Series([""] * len(view), index=view.index)
        top_matches = combined.str.upper().str.contains(str(top_wh).upper(), na=False) if top_wh else pd.Series([False] * len(view), index=view.index)
        finding = view.get("FINDING_TYPE", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str)
        severity = view.get("SEVERITY", pd.Series(["Medium"] * len(view), index=view.index)).fillna("Medium").astype(str)
        high_rows = int(severity.str.upper().isin(["CRITICAL", "HIGH"]).sum())
        warehouse_changes = int((finding.str.contains("WAREHOUSE|TASK|PROCEDURE|DRIFT", case=False, regex=True) | top_matches).sum())
        access_ai_changes = int(finding.str.contains("GRANT|ROLE|POLICY|TAG|AI|CORTEX", case=False, regex=True).sum())
        matched_rows = int(top_matches.sum())
        latest = view.iloc[0]
        matched_entity = str(latest.get("ENTITY") or latest.get("WAREHOUSE_NAME") or top_wh or "Snowflake account")
        add(
            "High" if matched_rows and spike_signal else "Medium" if warehouse_changes and spike_signal else "Info",
            "Top warehouse change proximity",
            top_wh or matched_entity,
            f"Top warehouse delta {top_delta:+,.2f} credits; 7d vs 30d {pct_vs_30d_float:+.1f}%.",
            f"{matched_rows:,} row(s) mention the top warehouse; {warehouse_changes:,} warehouse/task/procedure/drift row(s) loaded.",
            "A cost spike near warehouse/task/procedure drift must be treated as a root-cause candidate until query/change telemetry clears it.",
            "Review query_id, actor, warehouse settings, task/procedure runtime, and rollback status before tuning cost controls.",
            "Change exception query_id, WAREHOUSE_METERING_HISTORY, QUERY_HISTORY, task/procedure history, and post-change telemetry.",
            "Security Monitoring > Controlled DBA actions",
            0,
        )
        add(
            "High" if high_rows and spike_signal else "Medium" if high_rows else "Info",
            "High-risk change near cost movement",
            matched_entity,
            f"Cost movement active={spike_signal}; top warehouse {top_wh or 'On demand'}.",
            f"{high_rows:,} Critical/High change exception(s) loaded.",
            "High-severity object/access/policy changes near cost movement require a bill explanation, not just a cost chart.",
            "Record change ticket, query_id, actor, object, and blast-radius telemetry on the cost incident.",
            "Object-change telemetry, object/access change rows, and Cost & Contract root-cause board.",
            "Security Monitoring > Object and access changes",
            1,
        )
        add(
            "Medium" if access_ai_changes else "Info",
            "AI/access policy cost route",
            "AI / access control",
            "Cortex spend movement may be user-access driven.",
            f"{access_ai_changes:,} grant/role/policy/tag/AI-related change row(s) loaded.",
            "AI spend jumps can be caused by access expansion, tag mistakes, or policy changes as much as workload growth.",
            "Compare Cortex first/last usage to access and tag changes before enforcing per-user quotas.",
            "Cortex usage history, Security Monitoring grants/policy rows, and tag assignments.",
            "Cost & Contract > Cost by User / Role",
            2,
        )

    if not operability.empty:
        blocked = int(pd.to_numeric(operability.get("ROUTE_BLOCKED", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        closure = int(pd.to_numeric(operability.get("CLOSURE_BLOCKED", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        add(
            "High" if blocked + closure > 0 and spike_signal else "Info",
            "Object-change telemetry blocker",
            "Object-change summary",
            f"Cost movement active={spike_signal}.",
            f"{blocked:,} route blocker(s); {closure:,} closure blocker(s).",
            "Do not mark a cost incident resolved while related object-change telemetry is still blocked.",
            "Work object-change blockers before declaring the cost spike explained or resolved.",
            "FACT_CHANGE_CONTROL_OPERABILITY_DAILY with route and telemetry blocker counts.",
            "Security Monitoring > Object and access changes",
            3,
        )

    board = pd.DataFrame(rows)
    if board.empty:
        return {"score": 0, "high": 0, "top_correlation": "No change/cost telemetry"}, board
    board["_SEVERITY_RANK"] = board["SEVERITY"].apply(_cost_command_severity_rank)
    board = board.sort_values(["_SEVERITY_RANK", "_RANK"], ascending=[True, True])
    high = int(board["SEVERITY"].isin(["Critical", "High"]).sum())
    medium = int(board["SEVERITY"].eq("Medium").sum())
    score = max(0, min(100, 100 - high * 16 - medium * 7))
    top = board.iloc[0]
    return {
        "score": int(score),
        "high": high,
        "medium": medium,
        "top_correlation": str(top.get("CORRELATION") or "Change/cost correlation"),
        "top_entity": str(top.get("ENTITY") or "Unknown"),
        "top_action": str(top.get("NEXT_ACTION") or "Load Security Monitoring and compare to Cost & Contract."),
    }, board.drop(columns=["_SEVERITY_RANK", "_RANK"], errors="ignore").reset_index(drop=True)
