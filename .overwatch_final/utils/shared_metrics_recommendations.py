"""Shared recommendation and advisor metric loaders."""

from __future__ import annotations

from .company_filter import (
    get_active_company,
    get_company_scope_key,
    get_db_filter_clause,
    get_global_filter_clause,
    get_wh_filter_clause,
)
from .compatibility import build_task_failure_summary_sql, filter_existing_columns
from .cost import build_clustering_cost_sql, build_idle_warehouse_sql
from .mart import (
    build_mart_recommendation_failed_tasks_sql,
    build_mart_recommendation_idle_sql,
    build_mart_recommendation_query_errors_sql,
    build_mart_recommendation_spill_sql,
    mart_object_name,
)
from .query import run_query
from .shared_metrics_cache import _company_column_filter, _empty_result, _load_or_reuse
from .shared_metrics_contracts import SharedMetricResult

def load_shared_recommendation_idle_warehouses(
    company: str | None = None,
    *,
    days: int = 7,
    min_idle_credits: float = 1.0,
    allow_live_fallback: bool = True,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load idle-warehouse advisor candidates once for recommendation surfaces."""

    company = company or get_active_company()
    days = max(1, int(days or 7))
    min_idle_credits = float(min_idle_credits or 0)

    def _loader() -> SharedMetricResult:
        mart_message = ""
        if days == 7 and min_idle_credits <= 1.0:
            try:
                df = run_query(
                    build_mart_recommendation_idle_sql(company),
                    ttl_key=get_company_scope_key("shared_rec_idle_mart"),
                    tier="historical",
                    section=section,
                )
                if not df.empty:
                    return SharedMetricResult(data=df, source="Fast recommendation summary", available=True)
                mart_message = "Idle warehouse mart returned no rows."
            except Exception as exc:
                mart_message = str(exc)
        else:
            mart_message = "Live scan required for non-default idle threshold or lookback."

        if not allow_live_fallback:
            return _empty_result("Fast recommendation summary", mart_message)

        try:
            df = run_query(
                build_idle_warehouse_sql(
                    days_back=days,
                    wh_filter=get_wh_filter_clause("warehouse_name"),
                    min_idle_credits=min_idle_credits,
                ),
                ttl_key=get_company_scope_key("shared_rec_idle_live", days, min_idle_credits),
                tier="historical",
                section=section,
            )
            return SharedMetricResult(
                data=df,
                source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE warehouse/query history",
                available=not df.empty,
                message="" if not df.empty else mart_message,
            )
        except Exception as exc:
            return _empty_result("Idle warehouse advisor", f"{mart_message} Live fallback unavailable: {exc}")

    return _load_or_reuse(
        "shared_rec_idle",
        (company, days, min_idle_credits, allow_live_fallback),
        _loader,
        force=force,
    )


def load_shared_recommendation_spill_warehouses(
    session: object,
    company: str | None = None,
    *,
    days: int = 7,
    min_remote_gb: float = 5.0,
    allow_live_fallback: bool = True,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load remote-spill advisor candidates once for recommendation surfaces."""

    company = company or get_active_company()
    days = max(1, int(days or 7))
    min_remote_gb = float(min_remote_gb or 0)

    def _loader() -> SharedMetricResult:
        mart_message = ""
        if days == 7 and min_remote_gb <= 5.0:
            try:
                df = run_query(
                    build_mart_recommendation_spill_sql(company),
                    ttl_key=get_company_scope_key("shared_rec_spill_mart"),
                    tier="historical",
                    section=section,
                )
                if not df.empty:
                    return SharedMetricResult(data=df, source="Fast recommendation summary", available=True)
                mart_message = "Remote spill mart returned no rows."
            except Exception as exc:
                mart_message = str(exc)
        else:
            mart_message = "Live scan required for non-default spill threshold or lookback."

        if not allow_live_fallback:
            return _empty_result("Fast recommendation summary", mart_message)

        try:
            qh_cols = set(filter_existing_columns(
                session,
                "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                ["WAREHOUSE_SIZE", "BYTES_SPILLED_TO_REMOTE_STORAGE"],
            ))
            if "BYTES_SPILLED_TO_REMOTE_STORAGE" not in qh_cols:
                return _empty_result("Remote spill advisor", "QUERY_HISTORY remote spill column is not available.")
            wh_size_expr = "MAX(warehouse_size)" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR"
            query_filters = get_global_filter_clause(
                date_col="start_time",
                wh_col="warehouse_name",
                user_col="user_name",
                role_col="role_name",
                db_col="database_name",
            )
            df = run_query(
                f"""
                SELECT warehouse_name, {wh_size_expr} AS warehouse_size,
                       ROUND(SUM(bytes_spilled_to_remote_storage)/POWER(1024,3), 2) AS remote_gb
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                  AND bytes_spilled_to_remote_storage > 0
                  AND warehouse_name IS NOT NULL
                  {query_filters}
                GROUP BY warehouse_name
                HAVING remote_gb > {min_remote_gb}
                ORDER BY remote_gb DESC
                LIMIT 10
                """,
                ttl_key=get_company_scope_key("shared_rec_spill_live", days, min_remote_gb),
                tier="historical",
                section=section,
            )
            return SharedMetricResult(
                data=df,
                source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                available=not df.empty,
                message="" if not df.empty else mart_message,
            )
        except Exception as exc:
            return _empty_result("Remote spill advisor", f"{mart_message} Live fallback unavailable: {exc}")

    return _load_or_reuse(
        "shared_rec_spill",
        (company, days, min_remote_gb, allow_live_fallback),
        _loader,
        force=force,
    )


def load_shared_recommendation_failed_tasks(
    session: object,
    company: str | None = None,
    *,
    days: int = 7,
    min_failures: int = 3,
    allow_live_fallback: bool = True,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load task-failure advisor candidates once for recommendation surfaces."""

    company = company or get_active_company()
    days = max(1, int(days or 7))
    min_failures = max(0, int(min_failures or 0))

    def _loader() -> SharedMetricResult:
        mart_message = ""
        if days == 7 and min_failures <= 3:
            try:
                df = run_query(
                    build_mart_recommendation_failed_tasks_sql(company),
                    ttl_key=get_company_scope_key("shared_rec_failed_tasks_mart"),
                    tier="historical",
                    section=section,
                )
                if not df.empty:
                    return SharedMetricResult(data=df, source="Fast recommendation summary", available=True)
                mart_message = "Failed task mart returned no rows."
            except Exception as exc:
                mart_message = str(exc)
        else:
            mart_message = "Live scan required for non-default task-failure threshold or lookback."

        if not allow_live_fallback:
            return _empty_result("Fast recommendation summary", mart_message)

        try:
            failed_task_sql = build_task_failure_summary_sql(
                session,
                f"scheduled_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())",
                limit=25,
                company=company,
            )
            df = run_query(
                f"""
                WITH failed_tasks AS ({failed_task_sql})
                SELECT *
                FROM failed_tasks
                WHERE failures > {min_failures}
                ORDER BY failures DESC
                LIMIT 5
                """,
                ttl_key=get_company_scope_key("shared_rec_failed_tasks_live", days, min_failures),
                tier="historical",
                section=section,
            )
            return SharedMetricResult(
                data=df,
                source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY",
                available=not df.empty,
                message="" if not df.empty else mart_message,
            )
        except Exception as exc:
            return _empty_result("Failed task advisor", f"{mart_message} Live fallback unavailable: {exc}")

    return _load_or_reuse(
        "shared_rec_failed_tasks",
        (company, days, min_failures, allow_live_fallback),
        _loader,
        force=force,
    )


def load_shared_recommendation_query_failures(
    company: str | None = None,
    *,
    days: int = 7,
    min_failures: int = 10,
    allow_live_fallback: bool = True,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load query-failure advisor candidates once for recommendation surfaces."""

    company = company or get_active_company()
    days = max(1, int(days or 7))
    min_failures = max(0, int(min_failures or 0))

    def _loader() -> SharedMetricResult:
        mart_message = ""
        if days == 7:
            try:
                df = run_query(
                    build_mart_recommendation_query_errors_sql(company, min_failures=min_failures),
                    ttl_key=get_company_scope_key("shared_rec_query_failures_mart", min_failures),
                    tier="historical",
                    section=section,
                )
                if not df.empty:
                    return SharedMetricResult(data=df, source="Fast recommendation summary", available=True)
                mart_message = "Query failure mart returned no rows."
            except Exception as exc:
                mart_message = str(exc)
        else:
            mart_message = "Live scan required for non-default query-failure lookback."

        if not allow_live_fallback:
            return _empty_result("Fast recommendation summary", mart_message)

        try:
            query_filters = get_global_filter_clause(
                date_col="start_time",
                wh_col="warehouse_name",
                user_col="user_name",
                role_col="role_name",
                db_col="database_name",
            )
            df = run_query(
                f"""
                SELECT warehouse_name, COUNT(*) AS failures
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                  AND UPPER(execution_status) = 'FAILED_WITH_ERROR'
                  AND warehouse_name IS NOT NULL
                  {query_filters}
                GROUP BY warehouse_name
                HAVING failures > {min_failures}
                ORDER BY failures DESC
                LIMIT 5
                """,
                ttl_key=get_company_scope_key("shared_rec_query_failures_live", days, min_failures),
                tier="historical",
                section=section,
            )
            return SharedMetricResult(
                data=df,
                source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                available=not df.empty,
                message="" if not df.empty else mart_message,
            )
        except Exception as exc:
            return _empty_result("Query failure advisor", f"{mart_message} Live fallback unavailable: {exc}")

    return _load_or_reuse(
        "shared_rec_query_failures",
        (company, days, min_failures, allow_live_fallback),
        _loader,
        force=force,
    )


def load_shared_recommendation_storage_retention(
    company: str | None = None,
    *,
    min_time_travel_tb: float = 0.25,
    min_time_travel_ratio: float = 0.25,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load time-travel-heavy database candidates once for recommendation surfaces."""

    company = company or get_active_company()
    min_time_travel_tb = float(min_time_travel_tb or 0)
    min_time_travel_ratio = float(min_time_travel_ratio or 0)

    def _loader() -> SharedMetricResult:
        try:
            df = run_query(
                f"""
                SELECT table_catalog AS database_name,
                       ROUND(SUM(COALESCE(active_bytes, 0)) / POWER(1024, 4), 3) AS active_tb,
                       ROUND(SUM(COALESCE(time_travel_bytes, 0)) / POWER(1024, 4), 3) AS time_travel_tb,
                       ROUND(SUM(COALESCE(failsafe_bytes, 0)) / POWER(1024, 4), 3) AS failsafe_tb
                FROM SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS
                WHERE (deleted IS NULL OR deleted = FALSE)
                  AND table_catalog IS NOT NULL
                  {get_db_filter_clause("table_catalog", company)}
                GROUP BY table_catalog
                HAVING time_travel_tb >= {min_time_travel_tb}
                   AND time_travel_tb >= active_tb * {min_time_travel_ratio}
                ORDER BY time_travel_tb DESC
                LIMIT 10
                """,
                ttl_key=get_company_scope_key(
                    "shared_rec_storage_retention",
                    min_time_travel_tb,
                    min_time_travel_ratio,
                ),
                tier="historical",
                section=section,
            )
            return SharedMetricResult(
                data=df,
                source="Live: SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS",
                available=not df.empty,
            )
        except Exception as exc:
            return _empty_result("Storage retention advisor", f"Live storage-retention scan unavailable: {exc}")

    return _load_or_reuse(
        "shared_rec_storage_retention",
        (company, min_time_travel_tb, min_time_travel_ratio),
        _loader,
        force=force,
    )


def load_shared_recommendation_clustering_cost(
    company: str | None = None,
    *,
    days: int = 7,
    credit_price: float = 0.0,
    top: int = 10,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load automatic clustering cost candidates once for recommendation surfaces."""

    company = company or get_active_company()
    days = max(1, int(days or 7))
    top = max(1, int(top or 10))
    credit_price = float(credit_price or 0)

    def _loader() -> SharedMetricResult:
        try:
            df = run_query(
                build_clustering_cost_sql(days, company=company, credit_price=credit_price or None, top=top),
                ttl_key=get_company_scope_key("shared_rec_clustering_cost", days, credit_price, top),
                tier="historical",
                section=section,
            )
            return SharedMetricResult(
                data=df,
                source="Live: SNOWFLAKE.ACCOUNT_USAGE.AUTOMATIC_CLUSTERING_HISTORY",
                available=not df.empty,
                effective_days=days,
            )
        except Exception as exc:
            return _empty_result("Clustering cost advisor", f"Live clustering-cost scan unavailable: {exc}")

    return _load_or_reuse("shared_rec_clustering_cost", (company, days, credit_price, top), _loader, force=force)


def load_shared_recommendation_repeated_queries(
    session: object,
    company: str | None = None,
    *,
    days: int = 7,
    min_runs: int = 50,
    min_total_exec_hours: float = 2.0,
    allow_live_fallback: bool = True,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load repeated expensive query patterns once for recommendation surfaces."""

    company = company or get_active_company()
    days = max(1, int(days or 7))
    min_runs = max(1, int(min_runs or 1))
    min_total_exec_hours = float(min_total_exec_hours or 0)

    def _loader() -> SharedMetricResult:
        mart_message = ""
        query_filters = get_global_filter_clause(
            date_col="start_time",
            wh_col="warehouse_name",
            user_col="user_name",
            role_col="role_name",
            db_col="database_name",
        )
        if days <= 30:
            try:
                table = mart_object_name("FACT_QUERY_DETAIL_RECENT")
                df = run_query(
                    f"""
                    SELECT query_hash,
                           COUNT(*) AS runs,
                           COUNT(DISTINCT user_name) AS user_count,
                           ROUND(SUM(COALESCE(total_elapsed_time, 0)) / 1000 / 3600, 2) AS total_exec_hours,
                           ROUND(SUM(COALESCE(bytes_scanned, 0)) / POWER(1024, 4), 2) AS tb_scanned,
                           SUBSTR(MAX(query_text), 1, 500) AS sample_query,
                           'QUERY_HASH' AS hash_column
                    FROM {table}
                    WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                      AND warehouse_name IS NOT NULL
                      AND UPPER(COALESCE(execution_status, '')) = 'SUCCESS'
                      AND query_hash IS NOT NULL
                      {_company_column_filter("company", company)}
                      {query_filters}
                    GROUP BY query_hash
                    HAVING runs >= {min_runs} OR total_exec_hours >= {min_total_exec_hours}
                    ORDER BY total_exec_hours DESC, runs DESC
                    LIMIT 10
                    """,
                    ttl_key=get_company_scope_key(
                        "shared_rec_repeated_queries_mart",
                        days,
                        min_runs,
                        min_total_exec_hours,
                    ),
                    tier="historical",
                    section=section,
                )
                if not df.empty:
                    return SharedMetricResult(
                        data=df,
                        source="Fast query-detail summary",
                        available=True,
                        effective_days=days,
                    )
                mart_message = "Repeated-query mart returned no rows."
            except Exception as exc:
                mart_message = str(exc)
        else:
            mart_message = "Live scan required for repeated-query lookbacks beyond retained query detail."

        if not allow_live_fallback:
            return _empty_result("Fast query-detail summary", mart_message, effective_days=days)

        try:
            qh_columns = set(filter_existing_columns(
                session,
                "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                ["QUERY_PARAMETERIZED_HASH", "QUERY_HASH"],
            ))
            hash_column = (
                "QUERY_PARAMETERIZED_HASH"
                if "QUERY_PARAMETERIZED_HASH" in qh_columns
                else "QUERY_HASH" if "QUERY_HASH" in qh_columns else ""
            )
            if not hash_column:
                return _empty_result(
                    "Repeated query advisor",
                    f"{mart_message} QUERY_HISTORY does not expose a query hash column.",
                    effective_days=days,
                )
            hash_ident = hash_column
            df = run_query(
                f"""
                SELECT {hash_ident} AS query_hash,
                       COUNT(*) AS runs,
                       COUNT(DISTINCT user_name) AS user_count,
                       ROUND(SUM(COALESCE(total_elapsed_time, 0)) / 1000 / 3600, 2) AS total_exec_hours,
                       ROUND(SUM(COALESCE(bytes_scanned, 0)) / POWER(1024, 4), 2) AS tb_scanned,
                       SUBSTR(MAX(query_text), 1, 500) AS sample_query,
                       '{hash_column}' AS hash_column
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                  AND warehouse_name IS NOT NULL
                  AND UPPER(COALESCE(execution_status, '')) = 'SUCCESS'
                  AND {hash_ident} IS NOT NULL
                  {query_filters}
                GROUP BY {hash_ident}
                HAVING runs >= {min_runs} OR total_exec_hours >= {min_total_exec_hours}
                ORDER BY total_exec_hours DESC, runs DESC
                LIMIT 10
                """,
                ttl_key=get_company_scope_key(
                    "shared_rec_repeated_queries_live",
                    days,
                    min_runs,
                    min_total_exec_hours,
                    hash_column,
                ),
                tier="historical",
                section=section,
            )
            return SharedMetricResult(
                data=df,
                source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                available=not df.empty,
                message="" if not df.empty else mart_message,
                effective_days=days,
            )
        except Exception as exc:
            return _empty_result("Repeated query advisor", f"{mart_message} Live fallback unavailable: {exc}")

    return _load_or_reuse(
        "shared_rec_repeated_queries",
        (company, days, min_runs, min_total_exec_hours, allow_live_fallback),
        _loader,
        force=force,
    )


def load_shared_duplicate_query_patterns(
    session: object,
    company: str | None = None,
    *,
    days: int = 7,
    min_executions: int = 5,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load duplicate/redundant query candidates once for advisor panels."""

    company = company or get_active_company()
    days = max(1, int(days or 7))
    min_executions = max(1, int(min_executions or 1))

    def _loader() -> SharedMetricResult:
        query_filters = get_global_filter_clause(
            date_col="start_time",
            wh_col="warehouse_name",
            user_col="user_name",
            role_col="role_name",
            db_col="database_name",
        )
        mart_message = ""
        if days <= 30:
            try:
                table = mart_object_name("FACT_QUERY_DETAIL_RECENT")
                df = run_query(
                    f"""
                    SELECT SUBSTR(query_text, 1, 200) AS query_sig,
                           COUNT(DISTINCT user_name) AS user_count,
                           COUNT(*) AS execution_count,
                           SUM(total_elapsed_time) / NULLIF(COUNT(*), 0) / 1000 AS avg_elapsed_sec,
                           SUM(total_elapsed_time) / 1000 AS total_wasted_sec,
                           0::FLOAT AS cloud_credits
                    FROM {table}
                    WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                      AND UPPER(COALESCE(execution_status, '')) = 'SUCCESS'
                      AND warehouse_name IS NOT NULL
                      AND query_text IS NOT NULL
                      {_company_column_filter("company", company)}
                      {query_filters}
                    GROUP BY query_sig
                    HAVING execution_count >= {min_executions}
                    ORDER BY execution_count DESC, total_wasted_sec DESC
                    LIMIT 100
                    """,
                    ttl_key=get_company_scope_key("shared_duplicate_queries_mart", days, min_executions),
                    tier="standard",
                    section=section,
                )
                if not df.empty:
                    return SharedMetricResult(
                        data=df,
                        source="Fast query-detail summary",
                        available=True,
                        effective_days=days,
                    )
                mart_message = "Duplicate-query mart returned no rows."
            except Exception as exc:
                mart_message = str(exc)
        else:
            mart_message = "Live scan required for duplicate-query lookbacks beyond retained query detail."

        try:
            qh_cols = set(filter_existing_columns(
                session,
                "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                ["CREDITS_USED_CLOUD_SERVICES"],
            ))
            cloud_expr = (
                "SUM(COALESCE(credits_used_cloud_services, 0))"
                if "CREDITS_USED_CLOUD_SERVICES" in qh_cols
                else "0"
            )
            df = run_query(
                f"""
                SELECT SUBSTR(query_text, 1, 200) AS query_sig,
                       COUNT(DISTINCT user_name) AS user_count,
                       COUNT(*) AS execution_count,
                       SUM(total_elapsed_time) / NULLIF(COUNT(*), 0) / 1000 AS avg_elapsed_sec,
                       SUM(total_elapsed_time) / 1000 AS total_wasted_sec,
                       {cloud_expr} AS cloud_credits
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                  AND UPPER(execution_status) = 'SUCCESS'
                  AND warehouse_name IS NOT NULL
                  {query_filters}
                GROUP BY query_sig
                HAVING COUNT(*) >= {min_executions}
                ORDER BY execution_count DESC
                LIMIT 100
                """,
                ttl_key=get_company_scope_key("shared_duplicate_queries_live", days, min_executions),
                tier="standard",
                section=section,
            )
            return SharedMetricResult(
                data=df,
                source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                available=not df.empty,
                message="" if not df.empty else mart_message,
                effective_days=days,
            )
        except Exception as exc:
            return _empty_result("Duplicate query advisor", f"{mart_message} Live fallback unavailable: {exc}")

    return _load_or_reuse("shared_duplicate_queries", (company, days, min_executions), _loader, force=force)


