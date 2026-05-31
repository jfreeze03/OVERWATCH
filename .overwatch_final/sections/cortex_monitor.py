# sections/cortex_monitor.py — AI & Cortex Code usage: users, trends, anomalies, predictive alerts
import streamlit as st
import pandas as pd
from utils.workflows import render_priority_dataframe, render_workflow_selector
from utils import (
    format_snowflake_error,
    get_active_company,
    get_db_filter_clause,
    get_session,
    safe_strip_tz,
    format_credits,
    metric_confidence_label,
    freshness_note,
    download_csv,
    get_user_filter_clause,
    filter_existing_columns,
    make_action_id,
    run_query,
    safe_float,
    safe_int,
    upsert_actions,
)
from config import DEFAULTS


AI_CREDIT_RATE = DEFAULTS["ai_credit_price"]  # $2.20/AI credit (Table 6(d))


CORTEX_VIEWS = (
    "Budget Control",
    "User Attribution",
    "Daily Trends",
    "Anomaly Detection",
    "Predictive Alerts",
)

CORTEX_VIEW_DETAILS = {
    "Budget Control": "Control score, projected spend, source split, exceptions, and proof SQL.",
    "User Attribution": "User/source chargeback, requests, AI credits, and cost-per-request spikes.",
    "Daily Trends": "Daily requests, active users, credits, rolling burn, and source split.",
    "Anomaly Detection": "Z-score detection for unusual user-level Cortex spend.",
    "Predictive Alerts": "Forward-looking budget warnings and alert SQL.",
}


def _cortex_cost_score(
    projected_cost: float,
    budget_usd: float,
    spike_users: int = 0,
    active_users: int = 0,
    heavy_users: int | None = None,
) -> int:
    if heavy_users is not None:
        spike_users = heavy_users
    budget = max(safe_float(budget_usd), 1.0)
    budget_pct = safe_float(projected_cost) / budget * 100
    spike_pct = safe_float(spike_users) / max(safe_int(active_users), 1) * 100
    penalty = min(max(budget_pct - 75, 0) * 0.9, 45) + min(spike_pct * 1.4, 35)
    return max(0, min(100, int(round(100 - penalty))))


def _cortex_cost_rating(score: int) -> str:
    if score >= 90:
        return "Controlled"
    if score >= 78:
        return "Watch"
    if score >= 65:
        return "Cost Risk"
    return "Spiral Risk"


def _cortex_action_for(signal: str) -> tuple[str, str]:
    signal = str(signal or "").upper()
    if "BUDGET" in signal:
        return (
            "Review Cortex Code budget, daily credit limit, and role/user access before usage scales further.",
            "-- Consider ALTER ACCOUNT SET CORTEX_CODE_DAILY_CREDIT_LIMIT = <daily_credit_limit>;",
        )
    if "SPIKE" in signal:
        return (
            "Review the user/request pattern, model/tool usage, and whether this is approved project demand.",
            "-- Review CORTEX_CODE usage history by user/source/date and confirm business owner.",
        )
    return (
        "Review Cortex Code users, request volume, and cost-per-request before expanding access.",
        "-- Audit Cortex usage views and SNOWFLAKE.CORTEX_USER grants.",
    )


def _build_cortex_control_markdown(
    company: str,
    days: int,
    score: int,
    budget_usd: float,
    summary_row: dict,
    exceptions: pd.DataFrame,
) -> str:
    projected_cost = safe_float(summary_row.get("PROJECTED_30D_COST"))
    lines = [
        f"# OVERWATCH Cortex Cost Control Brief - {company}",
        "",
        f"- Lookback: {days} days",
        f"- Control score: {score} ({_cortex_cost_rating(score)})",
        f"- Monthly budget: ${safe_float(budget_usd):,.2f}",
        f"- Projected 30-day cost: ${projected_cost:,.2f}",
        f"- Active users: {safe_int(summary_row.get('ACTIVE_USERS')):,}",
        f"- Total requests: {safe_int(summary_row.get('TOTAL_REQUESTS')):,}",
        f"- AI credits: {safe_float(summary_row.get('TOTAL_CREDITS')):,.4f}",
        "",
        "## DBA Narrative",
        (
            "Cortex Code usage can scale quietly because spend is driven by individual users and tools, "
            "not warehouses. Use this brief to find budget breach risk, unexpected users, and source-level "
            "growth before it becomes a month-end surprise."
        ),
        "",
        "## Top Cortex Exceptions",
    ]
    if exceptions is None or exceptions.empty:
        lines.append("- No Cortex cost exceptions found for the selected scope.")
    else:
        for _, row in exceptions.head(10).iterrows():
            lines.append(
                "- "
                f"{row.get('SEVERITY', 'Watch')} | {row.get('SIGNAL', 'Unknown')} | "
                f"{row.get('USER_NAME', '')} | {row.get('SOURCE', '')} | "
                f"${safe_float(row.get('PROJECTED_30D_COST')):,.2f} projected"
            )
    lines.extend([
        "",
        "## Evidence Limits",
        "- Cortex Code views are ACCOUNT_USAGE-backed and can lag.",
        "- User-level chargeback is exact for Cortex Code views when Snowflake exposes USER_ID usage records.",
        "- Budget breach projections assume recent daily average continues for 30 days.",
    ])
    return "\n".join(lines)


def _build_cortex_control_sql(days: int, budget_usd: float) -> tuple[str, str]:
    user_filter = get_user_filter_clause("u.NAME")
    budget_credits = safe_float(budget_usd) / max(AI_CREDIT_RATE, 0.01)
    base = f"""
        WITH combined AS (
            SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS, TOKENS, 'Snowsight' AS SOURCE
            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY
            WHERE USAGE_TIME >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
            UNION ALL
            SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS, TOKENS, 'CLI' AS SOURCE
            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY
            WHERE USAGE_TIME >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
        ),
        user_daily AS (
            SELECT
                u.NAME AS user_name,
                u.EMAIL AS email,
                c.SOURCE,
                c.USAGE_TIME::DATE AS usage_date,
                COUNT(*) AS requests,
                SUM(c.TOKEN_CREDITS) AS credits,
                SUM(c.TOKENS) AS tokens
            FROM combined c
            LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u ON c.USER_ID = u.USER_ID
            WHERE 1=1 {user_filter}
            GROUP BY u.NAME, u.EMAIL, c.SOURCE, c.USAGE_TIME::DATE
        ),
        user_rollup AS (
            SELECT
                user_name,
                email,
                SOURCE,
                COUNT(DISTINCT usage_date) AS active_days,
                SUM(requests) AS total_requests,
                SUM(credits) AS total_credits,
                SUM(tokens) AS total_tokens,
                SUM(credits) / NULLIF(SUM(requests), 0) AS credits_per_request,
                SUM(credits) / NULLIF(COUNT(DISTINCT usage_date), 0) AS avg_daily_credits,
                SUM(credits) / NULLIF(COUNT(DISTINCT usage_date), 0) * 30 AS projected_30d_credits,
                SUM(credits) / NULLIF(COUNT(DISTINCT usage_date), 0) * 30 * {AI_CREDIT_RATE} AS projected_30d_cost
            FROM user_daily
            GROUP BY user_name, email, SOURCE
        )
    """
    summary_sql = f"""
        {base}
        SELECT
            COUNT(DISTINCT user_name) AS active_users,
            SUM(total_requests) AS total_requests,
            SUM(total_credits) AS total_credits,
            SUM(total_tokens) AS total_tokens,
            SUM(total_credits) / NULLIF(SUM(total_requests), 0) AS credits_per_request,
            SUM(total_credits) / NULLIF({int(days)}, 0) * 30 AS projected_30d_credits,
            SUM(total_credits) / NULLIF({int(days)}, 0) * 30 * {AI_CREDIT_RATE} AS projected_30d_cost,
            SUM(IFF(projected_30d_credits > {budget_credits} * 0.25, 1, 0)) AS heavy_users
        FROM user_rollup
    """
    exceptions_sql = f"""
        {base}
        SELECT
            CASE
                WHEN projected_30d_credits > {budget_credits} THEN 'Critical'
                WHEN projected_30d_credits > {budget_credits} * 0.50 THEN 'High'
                WHEN credits_per_request > 0.10 THEN 'High'
                ELSE 'Medium'
            END AS severity,
            CASE
                WHEN projected_30d_credits > {budget_credits} THEN 'Budget Breach'
                WHEN projected_30d_credits > {budget_credits} * 0.50 THEN 'Budget Concentration'
                WHEN credits_per_request > 0.10 THEN 'Cost Per Request Spike'
                ELSE 'High Usage'
            END AS signal,
            user_name,
            email,
            SOURCE,
            active_days,
            total_requests,
            ROUND(total_credits, 6) AS total_credits,
            total_tokens,
            ROUND(credits_per_request, 6) AS credits_per_request,
            ROUND(avg_daily_credits, 6) AS avg_daily_credits,
            ROUND(projected_30d_credits, 6) AS projected_30d_credits,
            ROUND(projected_30d_cost, 2) AS projected_30d_cost
        FROM user_rollup
        WHERE projected_30d_credits > {budget_credits} * 0.25
           OR credits_per_request > 0.10
        ORDER BY
            CASE severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 ELSE 3 END,
            projected_30d_cost DESC
        LIMIT 100
    """
    return summary_sql, exceptions_sql


def _build_cortex_daily_sql(days: int) -> str:
    user_filter = get_user_filter_clause("u.NAME")
    return f"""
        WITH combined AS (
            SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS, TOKENS, 'Snowsight' AS SOURCE
            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY
            WHERE USAGE_TIME >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
            UNION ALL
            SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS, TOKENS, 'CLI' AS SOURCE
            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY
            WHERE USAGE_TIME >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
        )
        SELECT
            c.USAGE_TIME::DATE AS usage_date,
            c.SOURCE,
            COUNT(DISTINCT c.USER_ID) AS active_users,
            COUNT(*) AS total_requests,
            SUM(c.TOKEN_CREDITS) AS total_credits,
            SUM(c.TOKENS) AS total_tokens,
            ROUND(SUM(c.TOKEN_CREDITS) * {AI_CREDIT_RATE}, 2) AS cost_usd
        FROM combined c
        LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u ON c.USER_ID = u.USER_ID
        WHERE 1=1 {user_filter}
        GROUP BY c.USAGE_TIME::DATE, c.SOURCE
        ORDER BY usage_date, c.SOURCE
    """


def _build_cortex_ai_functions_daily_sql(
    days: int,
    include_user_filter: bool = True,
    include_query_id: bool = True,
) -> str:
    """Build optional live Cortex AI Functions usage SQL.

    Snowflake exposes this separately from Cortex Code usage. Some accounts or
    roles may not have the view or the USER_ID column, so callers decide which
    joins are safe before executing the query.
    """
    user_join = "LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u ON f.USER_ID = u.USER_ID" if include_user_filter else ""
    user_filter = get_user_filter_clause("u.NAME") if include_user_filter else ""
    request_expr = "COUNT(DISTINCT f.QUERY_ID)" if include_query_id else "COUNT(*)"
    return f"""
        SELECT
            f.START_TIME::DATE AS usage_date,
            'AI Functions' AS source,
            0 AS active_users,
            {request_expr} AS total_requests,
            SUM(COALESCE(f.CREDITS, 0)) AS total_credits,
            0 AS total_tokens,
            ROUND(SUM(COALESCE(f.CREDITS, 0)) * {AI_CREDIT_RATE}, 2) AS cost_usd
        FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AI_FUNCTIONS_USAGE_HISTORY f
        {user_join}
        WHERE f.START_TIME >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
          {user_filter}
        GROUP BY f.START_TIME::DATE
        ORDER BY usage_date
    """


def _queue_cortex_findings(session, exceptions: pd.DataFrame, budget_usd: float) -> int:
    if exceptions is None or exceptions.empty:
        return 0
    company = get_active_company()
    actions = []
    for _, row in exceptions.head(50).iterrows():
        signal = str(row.get("SIGNAL", "Cortex Usage"))
        user = str(row.get("USER_NAME") or "Unknown user")
        action_text, generated_sql = _cortex_action_for(signal)
        finding = (
            f"{signal}: {user} projected Cortex Code cost is "
            f"${safe_float(row.get('PROJECTED_30D_COST')):,.2f} against "
            f"${safe_float(budget_usd):,.2f} monthly budget."
        )
        actions.append({
            "Action ID": make_action_id("Cortex Cost", user, finding),
            "Source": "Cortex Monitor - Cost Control",
            "Category": "AI / Cortex Cost",
            "Severity": row.get("SEVERITY", "High"),
            "Entity Type": "User",
            "Entity": user,
            "Owner": "DBA / Platform Owner",
            "Finding": finding,
            "Action": action_text,
            "Estimated Monthly Savings": max(safe_float(row.get("PROJECTED_30D_COST")) - safe_float(budget_usd), 0),
            "Generated SQL Fix": generated_sql,
            "Proof Query": "Review CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY and CORTEX_CODE_CLI_USAGE_HISTORY by USER_ID.",
            "Company": company,
        })
    return upsert_actions(session, actions)


def _render_cortex_control_brief(session, company: str) -> None:
    with st.expander("Cortex Cost Control Brief", expanded=bool(st.session_state.get("exceptions_only_mode"))):
        c1, c2 = st.columns(2)
        with c1:
            days = st.slider("Cortex control lookback (days)", 7, 90, 30, key="cortex_control_days")
        with c2:
            budget_usd = st.number_input(
                "Monthly Cortex Code budget ($)",
                min_value=0.0,
                value=1000.0,
                step=100.0,
                key="cortex_control_budget_usd",
            )
        if st.button("Load Cortex Cost Control", key="cortex_control_load"):
            with st.spinner("Building Cortex cost control brief..."):
                try:
                    summary_sql, exceptions_sql = _build_cortex_control_sql(days, budget_usd)
                    daily_sql = _build_cortex_daily_sql(days)
                    summary = run_query(
                        summary_sql,
                        ttl_key=f"cortex_control_summary_{company}_{days}_{budget_usd}",
                        tier="historical",
                        section="Cost & Contract",
                    )
                    exceptions = run_query(
                        exceptions_sql,
                        ttl_key=f"cortex_control_exceptions_{company}_{days}_{budget_usd}",
                        tier="historical",
                        section="Cost & Contract",
                    )
                    daily = run_query(
                        daily_sql,
                        ttl_key=f"cortex_control_daily_{company}_{days}_{budget_usd}",
                        tier="historical",
                        section="Cost & Contract",
                    )
                    ai_functions = pd.DataFrame()
                    ai_functions_sql = ""
                    ai_note = ""
                    try:
                        ai_object = "SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AI_FUNCTIONS_USAGE_HISTORY"
                        ai_cols = set(filter_existing_columns(
                            session,
                            ai_object,
                            ["START_TIME", "CREDITS", "QUERY_ID", "USER_ID"],
                        ))
                        if {"START_TIME", "CREDITS"}.issubset(ai_cols):
                            ai_functions_sql = _build_cortex_ai_functions_daily_sql(
                                days,
                                include_user_filter="USER_ID" in ai_cols,
                                include_query_id="QUERY_ID" in ai_cols,
                            )
                            ai_functions = run_query(
                                ai_functions_sql,
                                ttl_key=f"cortex_control_ai_functions_{company}_{days}_{budget_usd}",
                                tier="historical",
                                section="Cost & Contract",
                            )
                        else:
                            ai_note = "Cortex AI Functions usage view is unavailable or missing required columns for this role/account."
                    except Exception as ai_exc:
                        ai_note = f"Cortex AI Functions usage unavailable: {format_snowflake_error(ai_exc)}"
                    st.session_state["cortex_control_summary"] = summary
                    st.session_state["cortex_control_exceptions"] = exceptions
                    st.session_state["cortex_control_daily"] = daily
                    st.session_state["cortex_control_ai_functions"] = ai_functions
                    st.session_state["cortex_control_ai_note"] = ai_note
                    st.session_state["cortex_control_sql"] = {
                        "summary": summary_sql,
                        "exceptions": exceptions_sql,
                        "daily": daily_sql,
                        "ai_functions": ai_functions_sql,
                    }
                except Exception as e:
                    st.warning(f"Cortex cost control unavailable: {format_snowflake_error(e)}")

        summary = st.session_state.get("cortex_control_summary")
        exceptions = st.session_state.get("cortex_control_exceptions")
        if summary is None or summary.empty:
            return
        row = summary.iloc[0].to_dict()
        daily = st.session_state.get("cortex_control_daily", pd.DataFrame())
        ai_functions = st.session_state.get("cortex_control_ai_functions", pd.DataFrame())
        ai_projected_cost = 0.0
        if ai_functions is not None and not ai_functions.empty:
            ai_days = max(safe_int(ai_functions["USAGE_DATE"].nunique() if "USAGE_DATE" in ai_functions.columns else 0), 1)
            ai_projected_cost = safe_float(ai_functions.get("COST_USD", pd.Series(dtype=float)).sum()) / ai_days * 30
        projected_cost = safe_float(row.get("PROJECTED_30D_COST")) + ai_projected_cost
        daily_budget = safe_float(budget_usd) / 30 if safe_float(budget_usd) > 0 else 0.0
        avg_daily_cost = projected_cost / 30 if projected_cost > 0 else 0.0
        score = _cortex_cost_score(
            projected_cost=projected_cost,
            budget_usd=budget_usd,
            spike_users=safe_int(row.get("HEAVY_USERS")),
            active_users=safe_int(row.get("ACTIVE_USERS")),
        )
        rating = _cortex_cost_rating(score)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Cortex Control Score", score, rating)
        c2.metric("Projected 30d Cost", f"${projected_cost:,.2f}")
        c3.metric("Active Users", f"{safe_int(row.get('ACTIVE_USERS')):,}")
        c4.metric("Requests", f"{safe_int(row.get('TOTAL_REQUESTS')):,}")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Daily Budget", f"${daily_budget:,.2f}")
        k2.metric("Avg Daily Burn", f"${avg_daily_cost:,.2f}", delta=f"{(avg_daily_cost - daily_budget):+,.2f} vs budget" if daily_budget else None)
        k3.metric("Code AI Credits", format_credits(safe_float(row.get("TOTAL_CREDITS")), AI_CREDIT_RATE))
        k4.metric("AI Function Projection", f"${ai_projected_cost:,.2f}")
        ai_note = st.session_state.get("cortex_control_ai_note", "")
        if ai_note:
            st.info(ai_note)
        if projected_cost > budget_usd:
            st.error("Cortex spend is projected over budget. Treat this as a cost-control incident.")
        elif score < 78:
            st.warning("Cortex usage is concentrating or trending hot. Review heavy users before expanding access.")
        else:
            st.success("Cortex Code spend is controlled for the selected budget and lookback.")

        if exceptions is not None and not exceptions.empty:
            st.subheader("Cortex Cost Exceptions")
            render_priority_dataframe(
                exceptions,
                title="Cortex cost exceptions to work first",
                priority_columns=[
                    "SEVERITY", "SIGNAL", "USER_NAME", "SOURCE",
                    "PROJECTED_30D_COST", "TOTAL_CREDITS", "TOTAL_REQUESTS",
                    "NEXT_ACTION", "PROOF_QUERY",
                ],
                sort_by=["PROJECTED_30D_COST", "TOTAL_CREDITS", "TOTAL_REQUESTS"],
                ascending=[False, False, False],
                raw_label="All Cortex cost exceptions",
            )
            if st.button("Save Cortex Findings to Action Queue", key="cortex_control_queue"):
                try:
                    saved = _queue_cortex_findings(session, exceptions, budget_usd)
                    st.success(f"Saved {saved} Cortex cost findings to the action queue.")
                except Exception as e:
                    st.error(f"Could not save to action queue: {format_snowflake_error(e)}")
                    st.info("Deploy the Action Queue table from `snowflake/OVERWATCH_MART_SETUP.sql`, then retry this save.")
        else:
            st.success("No Cortex cost exceptions found for this scope.")

        if daily is not None and not daily.empty:
            daily_frames = [daily.copy()]
            if ai_functions is not None and not ai_functions.empty:
                daily_frames.append(ai_functions.copy())
            daily = pd.concat(daily_frames, ignore_index=True)
            daily["USAGE_DATE"] = safe_strip_tz(daily["USAGE_DATE"])
            daily_rollup = (
                daily.groupby("USAGE_DATE", as_index=False)
                .agg(COST_USD=("COST_USD", "sum"), TOTAL_CREDITS=("TOTAL_CREDITS", "sum"), TOTAL_REQUESTS=("TOTAL_REQUESTS", "sum"))
                .sort_values("USAGE_DATE")
            )
            daily_rollup["ROLLING_7D_COST"] = daily_rollup["COST_USD"].rolling(7, min_periods=1).mean()
            st.subheader("Daily Cortex Burn")
            st.line_chart(daily_rollup.set_index("USAGE_DATE")[["COST_USD", "ROLLING_7D_COST"]])
            source_split = (
                daily.groupby("SOURCE", as_index=False)
                .agg(COST_USD=("COST_USD", "sum"), TOTAL_CREDITS=("TOTAL_CREDITS", "sum"), TOTAL_REQUESTS=("TOTAL_REQUESTS", "sum"))
                .sort_values("COST_USD", ascending=False)
            )
            st.subheader("Source Split")
            render_priority_dataframe(
                source_split,
                title="Cortex cost by source",
                priority_columns=["SOURCE", "COST_USD", "TOTAL_CREDITS", "TOTAL_REQUESTS"],
                sort_by=["COST_USD", "TOTAL_CREDITS"],
                ascending=[False, False],
                raw_label="All Cortex source rows",
            )

        st.download_button(
            "Download Cortex Cost Brief",
            _build_cortex_control_markdown(
                company,
                days,
                score,
                budget_usd,
                {**row, "PROJECTED_30D_COST": projected_cost},
                exceptions,
            ),
            file_name=f"overwatch_cortex_cost_{company.lower()}.md",
            mime="text/markdown",
            key="cortex_control_download",
        )
        with st.expander("Proof SQL"):
            sql_map = st.session_state.get("cortex_control_sql", {})
            st.code(sql_map.get("summary", ""), language="sql")
            st.code(sql_map.get("exceptions", ""), language="sql")
            st.code(sql_map.get("daily", ""), language="sql")
            if sql_map.get("ai_functions"):
                st.code(sql_map.get("ai_functions", ""), language="sql")


def render():
    session = get_session()
    company = get_active_company()

    if st.session_state.get("exceptions_only_mode") and "cortex_monitor_view" not in st.session_state:
        st.session_state["cortex_monitor_view"] = "Budget Control"

    st.header("AI & Cortex Monitor")
    st.caption(
        "Track Cortex Code usage, projected spend, user attribution, anomalies, and budget-control exceptions."
    )
    st.caption(
        "Live sources: Cortex Code Snowsight/CLI usage views; Budget Control also includes Cortex AI Functions when Snowflake exposes that view."
    )

    cortex_view = render_workflow_selector(
        "Cortex workflow",
        "cortex_monitor_view",
        CORTEX_VIEWS,
        CORTEX_VIEW_DETAILS,
        columns=3,
    )

    # ── CORTEX CODE USERS ─────────────────────────────────────────────────────
    if cortex_view == "Budget Control":
        _render_cortex_control_brief(session, company)
        if st.session_state.get("exceptions_only_mode"):
            st.stop()

    elif cortex_view == "User Attribution":
        st.header("Cortex Code User Breakdown")
        st.caption(
            "Cortex Code usage (Snowsight + CLI) by user. "
            f"AI Credits billed at **${AI_CREDIT_RATE}/credit** (Table 6(d) regional inference)."
        )

        cc_days = st.slider("Lookback (days)", 7, 90, 30, key="cc_days_users")
        if st.button("Load User Data", key="cc_users_load"):
            with st.spinner("Loading Cortex Code user data..."):
                try:
                    df_cc = run_query(f"""
                        WITH combined AS (
                            SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS, TOKENS, 'Snowsight' AS SOURCE
                            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY
                            WHERE USAGE_TIME >= DATEADD('day', -{cc_days}, CURRENT_TIMESTAMP())
                            UNION ALL
                            SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS, TOKENS, 'CLI' AS SOURCE
                            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY
                            WHERE USAGE_TIME >= DATEADD('day', -{cc_days}, CURRENT_TIMESTAMP())
                        )
                        SELECT u.NAME AS USER_NAME, u.EMAIL, c.SOURCE,
                               COUNT(*)                                   AS TOTAL_REQUESTS,
                               SUM(c.TOKEN_CREDITS)                       AS TOTAL_CREDITS,
                               SUM(c.TOKENS)                              AS TOTAL_TOKENS,
                               ROUND(SUM(c.TOKEN_CREDITS)/NULLIF(COUNT(*),0),6) AS CREDITS_PER_REQUEST,
                               MIN(c.USAGE_TIME)                          AS FIRST_USAGE,
                               MAX(c.USAGE_TIME)                          AS LAST_USAGE
                        FROM combined c
                        LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u ON c.USER_ID = u.USER_ID
                        WHERE 1=1 {get_user_filter_clause("u.NAME")}
                        GROUP BY u.NAME, u.EMAIL, c.SOURCE
                        ORDER BY TOTAL_CREDITS DESC
                    """, ttl_key=f"cortex_users_{company}_{cc_days}", tier="standard")
                    st.session_state["cm_cc_users_data"] = df_cc
                except Exception as e:
                    st.warning(f"Cortex Code data unavailable: {format_snowflake_error(e)}")
                    st.info("Ensure CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY is available in your account (requires Cortex features enabled).")

        if st.session_state.get("cm_cc_users_data") is not None and not st.session_state["cm_cc_users_data"].empty:
            df_cc = st.session_state["cm_cc_users_data"]
            total_credits = float(df_cc["TOTAL_CREDITS"].sum())

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Active Users",           df_cc["USER_NAME"].nunique())
            c2.metric("Total Requests",         f"{int(df_cc['TOTAL_REQUESTS'].sum()):,}")
            c3.metric("Total AI Credits",       f"{total_credits:.4f}")
            c4.metric(f"Est. Cost (${AI_CREDIT_RATE}/AI cr)", f"${total_credits * AI_CREDIT_RATE:,.2f}")
            st.caption(f"{metric_confidence_label('account-wide')} | {freshness_note('ACCOUNT_USAGE')}")

            # Cost column
            df_cc = df_cc.copy()
            df_cc["COST_USD"] = df_cc["TOTAL_CREDITS"].apply(lambda x: round(x * AI_CREDIT_RATE, 4))
            df_cc["COST_PER_REQUEST_USD"] = df_cc.apply(
                lambda row: round(safe_float(row.get("COST_USD")) / max(safe_int(row.get("TOTAL_REQUESTS")), 1), 6),
                axis=1,
            )

            # Cost by user chart
            st.subheader("Cost by User")
            st.caption(
                "Cortex-only cost attribution. Query/user drilldown is intentionally disabled here "
                "because query history does not expose Cortex Code cost by query."
            )
            user_agg = (
                df_cc.groupby("USER_NAME")["COST_USD"]
                .sum().reset_index()
                .sort_values("COST_USD", ascending=False)
                .head(20)
            )
            if not user_agg.empty:
                st.bar_chart(user_agg.set_index("USER_NAME")["COST_USD"], use_container_width=True)

            st.subheader("Full Breakdown")
            render_priority_dataframe(
                df_cc,
                title="Cortex users to review first",
                priority_columns=[
                    "USER_NAME",
                    "SOURCE",
                    "TOTAL_CREDITS",
                    "COST_USD",
                    "TOTAL_REQUESTS",
                    "TOTAL_TOKENS",
                    "COST_PER_REQUEST_USD",
                ],
                sort_by=["COST_USD", "TOTAL_CREDITS", "TOTAL_REQUESTS"],
                ascending=[False, False, False],
                raw_label="All Cortex user attribution rows",
                height=350,
                column_config={
                    "COST_USD": st.column_config.NumberColumn("Cost", format="$%.2f"),
                    "COST_PER_REQUEST_USD": st.column_config.NumberColumn("Cost/request", format="$%.4f"),
                    "TOTAL_CREDITS": st.column_config.NumberColumn("AI Credits", format="%.4f"),
                    "TOTAL_REQUESTS": st.column_config.NumberColumn("Requests", format="%d"),
                    "TOTAL_TOKENS": st.column_config.NumberColumn("Tokens", format="%d"),
                },
            )
            download_csv(df_cc, "cortex_code_users.csv")

            # Cost-per-request spike detection
            st.divider()
            st.subheader("Cost-per-Request Spike Detection (Last 7d vs Prior)")
            if st.button("Detect CPR Spikes", key="cc_spike_load"):
                try:
                    df_spike = run_query(f"""
                        WITH combined AS (
                            SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS, TOKENS
                            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY
                            WHERE USAGE_TIME >= DATEADD('day', -{cc_days}, CURRENT_TIMESTAMP())
                            UNION ALL
                            SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS, TOKENS
                            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY
                            WHERE USAGE_TIME >= DATEADD('day', -{cc_days}, CURRENT_TIMESTAMP())
                        ),
                        recent AS (
                            SELECT USER_ID, COUNT(*) AS requests, SUM(TOKEN_CREDITS) AS credits
                            FROM combined WHERE USAGE_TIME >= DATEADD('day',-7,CURRENT_TIMESTAMP())
                            GROUP BY USER_ID HAVING COUNT(*) >= 3
                        ),
                        prior AS (
                            SELECT USER_ID, COUNT(*) AS requests, SUM(TOKEN_CREDITS) AS credits
                            FROM combined WHERE USAGE_TIME < DATEADD('day',-7,CURRENT_TIMESTAMP())
                            GROUP BY USER_ID HAVING COUNT(*) >= 3
                        )
                        SELECT u.NAME AS USER_NAME,
                               p.requests    AS PRIOR_REQUESTS,
                               ROUND(p.credits/NULLIF(p.requests,0),6) AS PRIOR_CPR,
                               r.requests    AS RECENT_REQUESTS,
                               ROUND(r.credits/NULLIF(r.requests,0),6) AS RECENT_CPR,
                               ROUND((r.credits/NULLIF(r.requests,0))
                                     / NULLIF(p.credits/NULLIF(p.requests,0),0)*100-100, 1) AS PCT_CHANGE
                        FROM recent r JOIN prior p ON r.USER_ID = p.USER_ID
                        LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u ON r.USER_ID = u.USER_ID
                        WHERE 1=1 {get_user_filter_clause("u.NAME")}
                        ORDER BY PCT_CHANGE DESC
                    """, ttl_key=f"cortex_cpr_spikes_{company}_{cc_days}", tier="standard")
                    if not df_spike.empty:
                        spikes = df_spike[df_spike["PCT_CHANGE"] > 25] if "PCT_CHANGE" in df_spike.columns else df_spike
                        if not spikes.empty:
                            st.warning(f"{len(spikes)} user(s) with >25% cost-per-request increase vs prior period.")
                        render_priority_dataframe(
                            df_spike,
                            title="Cost-per-request spikes",
                            priority_columns=[
                                "USER_NAME",
                                "PCT_CHANGE",
                                "RECENT_CPR",
                                "PRIOR_CPR",
                                "RECENT_REQUESTS",
                                "PRIOR_REQUESTS",
                            ],
                            sort_by=["PCT_CHANGE", "RECENT_CPR"],
                            ascending=[False, False],
                            raw_label="All cost-per-request spike rows",
                        )
                        download_csv(df_spike, "cortex_cpr_spikes.csv")
                    else:
                        st.success("No cost-per-request spikes detected.")
                except Exception as e:
                    st.warning(f"Spike detection unavailable: {format_snowflake_error(e)}")

    # ── DAILY TRENDS ──────────────────────────────────────────────────────────
    elif cortex_view == "Daily Trends":
        st.header("Cortex Code Daily Trends")
        st.caption("Daily credits, request volume, and active users - Snowsight vs CLI split.")

        cc_trend_days = st.slider("Lookback (days)", 7, 90, 30, key="cc_trend_days")
        if st.button("Load Trends", key="cc_trends_load"):
            with st.spinner("Loading trends..."):
                try:
                    df_trend = run_query(f"""
                        WITH combined AS (
                            SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS, TOKENS, 'Snowsight' AS SOURCE
                            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY
                            WHERE USAGE_TIME >= DATEADD('day', -{cc_trend_days}, CURRENT_TIMESTAMP())
                            UNION ALL
                            SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS, TOKENS, 'CLI' AS SOURCE
                            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY
                            WHERE USAGE_TIME >= DATEADD('day', -{cc_trend_days}, CURRENT_TIMESTAMP())
                        )
                        SELECT c.USAGE_TIME::DATE AS USAGE_DATE,
                               SOURCE,
                               COUNT(DISTINCT c.USER_ID) AS ACTIVE_USERS,
                               COUNT(*)                AS TOTAL_REQUESTS,
                               SUM(TOKEN_CREDITS)      AS TOTAL_CREDITS
                        FROM combined c
                        LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u ON c.USER_ID = u.USER_ID
                        WHERE 1=1 {get_user_filter_clause("u.NAME")}
                        GROUP BY USAGE_DATE, SOURCE
                        ORDER BY USAGE_DATE
                    """, ttl_key=f"cortex_trends_{company}_{cc_trend_days}", tier="standard")
                    st.session_state["cm_cc_trends_data"] = df_trend
                except Exception as e:
                    st.warning(f"Trends unavailable: {format_snowflake_error(e)}")

        if st.session_state.get("cm_cc_trends_data") is not None and not st.session_state["cm_cc_trends_data"].empty:
            df_tr = st.session_state["cm_cc_trends_data"]
            df_tr["USAGE_DATE"] = safe_strip_tz(df_tr["USAGE_DATE"])

            daily = (
                df_tr.groupby("USAGE_DATE")
                .agg(TOTAL_CREDITS=("TOTAL_CREDITS","sum"),
                     TOTAL_REQUESTS=("TOTAL_REQUESTS","sum"),
                     ACTIVE_USERS=("ACTIVE_USERS","sum"))
                .reset_index()
            )

            col_t1, col_t2 = st.columns(2)
            with col_t1:
                st.caption("Daily AI Credits")
                st.line_chart(daily.set_index("USAGE_DATE")["TOTAL_CREDITS"])
            with col_t2:
                st.caption("Daily Active Users")
                st.line_chart(daily.set_index("USAGE_DATE")["ACTIVE_USERS"])

            st.caption("Daily Requests")
            st.bar_chart(daily.set_index("USAGE_DATE")["TOTAL_REQUESTS"])

            source_agg = df_tr.groupby("SOURCE").agg(
                TOTAL_CREDITS=("TOTAL_CREDITS","sum"),
                TOTAL_REQUESTS=("TOTAL_REQUESTS","sum")
            ).reset_index()
            st.caption("Snowsight vs CLI")
            render_priority_dataframe(
                source_agg,
                title="Snowsight vs CLI source split",
                priority_columns=["SOURCE", "TOTAL_CREDITS", "TOTAL_REQUESTS"],
                sort_by=["TOTAL_CREDITS", "TOTAL_REQUESTS"],
                ascending=[False, False],
                raw_label="All Cortex trend source rows",
            )

            # 7-day rolling average overlay
            daily["ROLLING_7D"] = daily["TOTAL_CREDITS"].rolling(7, min_periods=1).mean()
            st.caption("Credits + 7-day Rolling Avg")
            st.line_chart(daily.set_index("USAGE_DATE")[["TOTAL_CREDITS","ROLLING_7D"]])

            download_csv(df_tr, "cortex_trends.csv")

    # ── ANOMALY DETECTION ─────────────────────────────────────────────────────
    elif cortex_view == "Anomaly Detection":
        st.header("Cortex Code Anomaly Detection")
        st.caption("Z-score based anomaly detection on daily per-user Cortex spend.")

        cc_anom_days = st.slider("Detection window (days)", 14, 90, 30, key="cc_anom_days")
        if st.button("Detect Anomalies", key="cc_anom_load"):
            with st.spinner("Running anomaly detection..."):
                try:
                    df_anom = run_query(f"""
                        WITH combined AS (
                            SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS
                            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY
                            WHERE USAGE_TIME >= DATEADD('day', -{cc_anom_days}, CURRENT_TIMESTAMP())
                            UNION ALL
                            SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS
                            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY
                            WHERE USAGE_TIME >= DATEADD('day', -{cc_anom_days}, CURRENT_TIMESTAMP())
                        ),
                        daily AS (
                            SELECT USER_ID,
                                   USAGE_TIME::DATE AS USAGE_DATE,
                                   COUNT(*)         AS REQUESTS,
                                   SUM(TOKEN_CREDITS) AS CREDITS,
                                   ROUND(SUM(TOKEN_CREDITS)/COUNT(*),6) AS CREDITS_PER_REQ
                            FROM combined GROUP BY USER_ID, USAGE_DATE
                        ),
                        with_stats AS (
                            SELECT d.*,
                                AVG(d.CREDITS) OVER (
                                    PARTITION BY d.USER_ID
                                    ORDER BY d.USAGE_DATE
                                    ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING
                                ) AS AVG_7D,
                                STDDEV(d.CREDITS) OVER (
                                    PARTITION BY d.USER_ID
                                    ORDER BY d.USAGE_DATE
                                    ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING
                                ) AS STD_7D
                            FROM daily d
                        )
                        SELECT u.NAME AS USER_NAME,
                               s.USAGE_DATE, s.REQUESTS, s.CREDITS, s.CREDITS_PER_REQ,
                               ROUND(s.AVG_7D, 6) AS ROLLING_AVG,
                               ROUND(CASE WHEN s.STD_7D > 0
                                          THEN (s.CREDITS - s.AVG_7D) / s.STD_7D END, 2) AS ZSCORE,
                               CASE
                                   WHEN COALESCE((s.CREDITS-s.AVG_7D)/NULLIF(s.STD_7D,0), 0) > 2
                                      THEN 'SPEND SPIKE'
                                   WHEN COALESCE((s.CREDITS-s.AVG_7D)/NULLIF(s.STD_7D,0), 0) > 1.5
                                      THEN 'ELEVATED'
                                   ELSE NULL
                               END AS ANOMALY_FLAG
                        FROM with_stats s
                        LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u ON s.USER_ID = u.USER_ID
                        WHERE s.AVG_7D IS NOT NULL
                          {get_user_filter_clause("u.NAME")}
                        ORDER BY s.USAGE_DATE DESC, s.CREDITS DESC
                    """, ttl_key=f"cortex_anomalies_{company}_{cc_anom_days}", tier="standard")
                    st.session_state["cm_cc_anom_data"] = df_anom
                except Exception as e:
                    st.warning(f"Anomaly detection unavailable: {format_snowflake_error(e)}")

        if st.session_state.get("cm_cc_anom_data") is not None and not st.session_state["cm_cc_anom_data"].empty:
            df_an = st.session_state["cm_cc_anom_data"]
            flagged = df_an[df_an.get("ANOMALY_FLAG", pd.Series()).notna()] if "ANOMALY_FLAG" in df_an.columns else pd.DataFrame()
            spikes  = df_an[df_an.get("ANOMALY_FLAG", pd.Series()).eq("SPEND SPIKE")] if "ANOMALY_FLAG" in df_an.columns else pd.DataFrame()

            c1, c2, c3 = st.columns(3)
            c1.metric("Days Analyzed",    len(df_an["USAGE_DATE"].unique()) if "USAGE_DATE" in df_an.columns else 0)
            c2.metric("Anomalous Days",   len(flagged), delta_color="inverse")
            c3.metric("Spend Spikes",  len(spikes),  delta_color="inverse")

            if not flagged.empty:
                st.warning(f"{len(flagged)} anomalous Cortex Code usage day(s) detected.")
                render_priority_dataframe(
                    flagged,
                    title="Cortex anomalies to investigate first",
                    priority_columns=[
                        "USER_NAME",
                        "ANOMALY_FLAG",
                        "USAGE_DATE",
                        "CREDITS",
                        "ROLLING_AVG",
                        "ZSCORE",
                        "REQUESTS",
                        "CREDITS_PER_REQ",
                    ],
                    sort_by=["ANOMALY_FLAG", "ZSCORE", "CREDITS"],
                    ascending=[True, False, False],
                    raw_label="All Cortex anomaly rows",
                )

            with st.expander("Full anomaly evidence", expanded=False):
                render_priority_dataframe(
                    df_an,
                    title="Cortex anomaly evidence",
                    priority_columns=[
                        "USER_NAME",
                        "USAGE_DATE",
                        "CREDITS",
                        "ROLLING_AVG",
                        "ZSCORE",
                        "REQUESTS",
                        "CREDITS_PER_REQ",
                        "ANOMALY_FLAG",
                    ],
                    sort_by=["ZSCORE", "CREDITS"],
                    ascending=[False, False],
                    raw_label="All anomaly evidence rows",
                    max_rows=50,
                )

            download_csv(df_an, "cortex_anomalies.csv")
        elif st.session_state.get("cm_cc_anom_data") is not None:
            st.success("No anomalies detected in the analysis window.")

    # ── PREDICTIVE ALERTS ─────────────────────────────────────────────────────
    elif cortex_view == "Predictive Alerts":
        st.header("Predictive Cortex AI Cost Alerts")
        st.caption(
            "Projects Cortex Code spend at current trajectory. "
            "Flags accounts on course to exceed configurable monthly budget."
        )

        monthly_ai_budget = st.number_input(
            "Monthly AI credit budget", min_value=0.0, value=500.0, step=50.0, key="ai_budget"
        )

        if st.button("Run Predictive Analysis", key="cc_pred_load"):
            try:
                df_pred = run_query(f"""
                    WITH combined AS (
                        SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS
                        FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY
                        WHERE USAGE_TIME >= DATEADD('month',-1,CURRENT_TIMESTAMP())
                        UNION ALL
                        SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS
                        FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY
                        WHERE USAGE_TIME >= DATEADD('month',-1,CURRENT_TIMESTAMP())
                    )
                    SELECT c.USAGE_TIME::DATE AS USAGE_DATE, SUM(c.TOKEN_CREDITS) AS DAILY_CREDITS
                    FROM combined c
                    LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u ON c.USER_ID = u.USER_ID
                    WHERE 1=1 {get_user_filter_clause("u.NAME", company)}
                    GROUP BY c.USAGE_TIME::DATE
                    ORDER BY c.USAGE_TIME::DATE
                """, ttl_key=f"cortex_predictive_{company}", tier="standard")
                st.session_state["cm_cc_pred_data"] = df_pred
            except Exception as e:
                st.warning(f"Projection data unavailable: {format_snowflake_error(e)}")

        if st.session_state.get("cm_cc_pred_data") is not None and not st.session_state["cm_cc_pred_data"].empty:
            df_p = st.session_state["cm_cc_pred_data"].copy()
            df_p["USAGE_DATE"] = pd.to_datetime(df_p["USAGE_DATE"])
            full_window = pd.DataFrame({
                "USAGE_DATE": pd.date_range(
                    pd.Timestamp.today().normalize() - pd.Timedelta(days=29),
                    pd.Timestamp.today().normalize(),
                    freq="D",
                )
            })
            df_p = full_window.merge(df_p, on="USAGE_DATE", how="left")
            df_p["DAILY_CREDITS"] = pd.to_numeric(df_p["DAILY_CREDITS"], errors="coerce").fillna(0)
            avg_daily = float(df_p["DAILY_CREDITS"].mean())
            days_in_month = 30
            projected_month = avg_daily * days_in_month
            projected_cost  = projected_month * AI_CREDIT_RATE

            c1, c2, c3 = st.columns(3)
            c1.metric("Avg Daily AI Credits", f"{avg_daily:.4f}")
            c2.metric("Projected 30-day Credits", f"{projected_month:.4f}")
            c3.metric("Projected 30-day Cost",    f"${projected_cost:,.2f}")
            st.caption(f"{metric_confidence_label('projection')} | {freshness_note('ACCOUNT_USAGE')}")

            if projected_month > monthly_ai_budget:
                overage = projected_month - monthly_ai_budget
                st.error(
                    f"On track to exceed budget by {overage:.2f} AI credits "
                    f"(${overage * AI_CREDIT_RATE:,.2f})**. "
                    f"Consider setting user-level quotas or reviewing heavy users."
                )
            else:
                headroom = monthly_ai_budget - projected_month
                st.success(
                    f"Projected spend ({projected_month:.2f} credits) is within budget. "
                    f"Headroom: {headroom:.2f} credits."
                )

            st.caption("Daily Credit Trend (last 30 days)")
            df_p["USAGE_DATE"] = safe_strip_tz(df_p["USAGE_DATE"])
            st.line_chart(df_p.set_index("USAGE_DATE")["DAILY_CREDITS"])

            # MV Refresh History tab extra (bonus)
            st.divider()
            st.subheader("🔄 Materialized View Refresh History")
            if st.button("Load MV Refresh History", key="mv_refresh_load"):
                try:
                    mv_object = "SNOWFLAKE.ACCOUNT_USAGE.MATERIALIZED_VIEW_REFRESH_HISTORY"
                    mv_cols = set(filter_existing_columns(
                        session,
                        mv_object,
                        [
                            "DATABASE_NAME", "SCHEMA_NAME", "NAME", "CREDITS_USED",
                            "BYTES_WRITTEN", "ROWS_INSERTED", "REFRESH_START_TIME",
                            "REFRESH_END_TIME",
                        ],
                    ))
                    if "REFRESH_START_TIME" not in mv_cols:
                        raise ValueError("MATERIALIZED_VIEW_REFRESH_HISTORY does not expose REFRESH_START_TIME.")

                    def _mv_expr(col: str, fallback: str, alias: str) -> str:
                        return f"{col.lower()} AS {alias}" if col in mv_cols else f"{fallback} AS {alias}"

                    refresh_end_raw = "refresh_end_time" if "REFRESH_END_TIME" in mv_cols else "CURRENT_TIMESTAMP()"
                    mv_db_filter = (
                        get_db_filter_clause("database_name", company)
                        if "DATABASE_NAME" in mv_cols else ""
                    )
                    df_mv = run_query(f"""
                        SELECT {_mv_expr("DATABASE_NAME", "NULL::VARCHAR", "database_name")},
                               {_mv_expr("SCHEMA_NAME", "NULL::VARCHAR", "schema_name")},
                               {_mv_expr("NAME", "NULL::VARCHAR", "mv_name")},
                               {_mv_expr("CREDITS_USED", "0::FLOAT", "credits_used")},
                               {_mv_expr("BYTES_WRITTEN", "0::NUMBER", "bytes_written")},
                               {_mv_expr("ROWS_INSERTED", "0::NUMBER", "rows_inserted")},
                               refresh_start_time,
                               {_mv_expr("REFRESH_END_TIME", "NULL::TIMESTAMP_NTZ", "refresh_end_time")},
                               DATEDIFF('second', refresh_start_time, {refresh_end_raw}) AS duration_sec
                        FROM {mv_object}
                        WHERE refresh_start_time >= DATEADD('day',-7,CURRENT_TIMESTAMP())
                          {mv_db_filter}
                        ORDER BY credits_used DESC LIMIT 100
                    """, ttl_key=f"cortex_mv_refresh_{company}", tier="standard")
                    if not df_mv.empty:
                        c1, c2 = st.columns(2)
                        c1.metric("MV Refreshes (7d)", len(df_mv))
                        c2.metric("Total Credits",     format_credits(df_mv["CREDITS_USED"].sum()))
                        render_priority_dataframe(
                            df_mv,
                            title="Materialized view refreshes by cost",
                            priority_columns=[
                                "DATABASE_NAME",
                                "SCHEMA_NAME",
                                "MV_NAME",
                                "CREDITS_USED",
                                "DURATION_SEC",
                                "BYTES_WRITTEN",
                                "ROWS_INSERTED",
                                "REFRESH_START_TIME",
                            ],
                            sort_by=["CREDITS_USED", "DURATION_SEC", "BYTES_WRITTEN"],
                            ascending=[False, False, False],
                            raw_label="All materialized view refresh rows",
                        )
                        download_csv(df_mv, "mv_refresh_history.csv")
                    else:
                        st.info("No materialized view refresh activity in the last 7 days.")
                except Exception as e:
                    st.warning(f"MV refresh history unavailable: {format_snowflake_error(e)}")
