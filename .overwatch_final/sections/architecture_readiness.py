# sections/architecture_readiness.py - Snowflake architecture control-plane checks
from __future__ import annotations

import re

import pandas as pd
import streamlit as st

from config import ARCHITECTURE_OBJECTIVES, THRESHOLDS
from utils import (
    download_csv,
    filter_existing_columns,
    format_snowflake_error,
    freshness_note,
    get_active_company,
    get_active_environment,
    get_global_filter_clause,
    get_session,
    load_owner_directory,
    load_warehouse_inventory,
    metric_confidence_label,
    resolve_owner_context,
    run_query,
    safe_float,
    safe_int,
    sql_literal,
    show_to_df,
    upsert_actions,
)
from utils.workflows import render_operator_briefing, render_priority_dataframe
from utils.futures_governance import (
    build_forward_platform_control_register,
    build_platform_futures_evidence_ddl,
    build_platform_futures_board,
    load_agent_mcp_inventory,
    load_ai_usage_guardrails,
    load_horizon_semantic_readiness,
    load_openflow_operations,
)


ARCHITECTURE_READINESS_PANES = (
    "Workload Isolation",
    "Clustering Strategy",
    "Cache Optimization",
    "Objectives & Owners",
    "DR Readiness",
    "AI & Platform Futures",
    "Forward Watchlist",
)

ARCHITECTURE_SCOPE_FILTER_KEYS = (
    "global_warehouse",
    "global_user",
    "global_role",
    "global_database",
    "global_start_date",
    "global_end_date",
)


def _quote_ident(value: object) -> str:
    text = str(value or "").strip()
    return '"' + text.replace('"', '""') + '"'


def _table_fqn(row: pd.Series) -> str:
    return ".".join([
        _quote_ident(row.get("TABLE_CATALOG")),
        _quote_ident(row.get("TABLE_SCHEMA")),
        _quote_ident(row.get("TABLE_NAME")),
    ])


def _severity_rank(value: object) -> int:
    order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}
    return order.get(str(value or "Info"), 4)


def _scope_value(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value).strip()


def _architecture_scope_meta(
    company: str,
    environment: str,
    surface: str,
    days: int | None = None,
    row_limit: int | None = None,
    state: dict | None = None,
) -> dict:
    state = state if state is not None else st.session_state
    meta = {
        "company": _scope_value(company),
        "environment": _scope_value(environment),
        "surface": _scope_value(surface),
    }
    if days is not None:
        meta["days"] = int(days)
    if row_limit is not None:
        meta["row_limit"] = int(row_limit)
    for key in ARCHITECTURE_SCOPE_FILTER_KEYS:
        meta[key] = _scope_value(state.get(key))
    return meta


def _architecture_meta_matches(meta: dict | None, expected: dict | None) -> bool:
    if not isinstance(meta, dict) or not isinstance(expected, dict):
        return False
    for key, expected_value in expected.items():
        actual = meta.get(key)
        if key in {"days", "row_limit"}:
            try:
                if int(actual) != int(expected_value):
                    return False
            except Exception:
                return False
        elif _scope_value(actual) != _scope_value(expected_value):
            return False
    return True


def _wildcard_match(pattern: object, value: object) -> tuple[bool, int]:
    pat = str(pattern or "*").strip().upper().replace("%", "*")
    val = str(value or "").strip().upper()
    if not val:
        return False, 0
    if pat in {"*", ""}:
        return True, 1
    if pat == val:
        return True, 100
    regex = "^" + re.escape(pat).replace("\\*", ".*") + "$"
    if re.match(regex, val):
        return True, 45
    needle = pat.replace("*", "")
    if needle and needle in val:
        return True, 20
    return False, 0


def _architecture_objectives_frame(company: str = "ALL") -> pd.DataFrame:
    rows = []
    company_upper = str(company or "ALL").upper()
    for item in ARCHITECTURE_OBJECTIVES:
        row = {str(key).upper(): value for key, value in item.items()}
        row_company = str(row.get("COMPANY") or "ALL").upper()
        if company_upper != "ALL" and row_company not in {company_upper, "ALL"}:
            continue
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    expected = [
        "COMPANY", "ENTITY_TYPE", "ENTITY_PATTERN", "EXPECTED_ENVIRONMENT",
        "WORKLOAD_CLASS", "SERVICE_TIER", "OWNER", "APPROVAL_GROUP",
        "RPO_MINUTES", "RTO_MINUTES", "ISOLATION_POLICY", "CACHE_POLICY",
        "CLUSTERING_POLICY", "DR_POLICY", "MATCH_PRIORITY",
    ]
    for col in expected:
        if col not in frame.columns:
            frame[col] = ""
    return frame[expected]


def _best_architecture_objective(
    entity: object,
    entity_type: str,
    company: str = "ALL",
    objectives: pd.DataFrame | None = None,
) -> dict:
    frame = objectives if objectives is not None else _architecture_objectives_frame(company)
    if frame is None or frame.empty:
        return {}
    entity_type_upper = str(entity_type or "").upper()
    best: dict | None = None
    best_score = -1
    for _, row in frame.fillna("").iterrows():
        row_type = str(row.get("ENTITY_TYPE") or "").upper()
        if row_type not in {entity_type_upper, "ARCHITECTURE"}:
            continue
        matched, match_score = _wildcard_match(row.get("ENTITY_PATTERN"), entity)
        if not matched:
            continue
        priority = safe_int(row.get("MATCH_PRIORITY"))
        type_score = 100 if row_type == entity_type_upper else 20
        score = priority + type_score + match_score
        if score > best_score:
            best_score = score
            best = row.to_dict()
    return best or {}


def _architecture_verification_sql(
    entity: object,
    entity_type: str,
    category: str,
    days: int = 30,
) -> str:
    entity_sql = sql_literal(entity, 500)
    days = max(1, min(int(days or 30), 90))
    entity_type_upper = str(entity_type or "").upper()
    category_upper = str(category or "").upper()
    if entity_type_upper == "DATABASE":
        return f"""SELECT database_name, warehouse_name, COUNT(*) AS query_count,
       SUM(COALESCE(queued_overload_time, 0)) / 1000 AS queued_sec,
       SUM(COALESCE(bytes_spilled_to_remote_storage, 0)) / POWER(1024, 3) AS remote_spill_gb,
       MAX(start_time) AS last_seen
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
  AND database_name = {entity_sql}
GROUP BY database_name, warehouse_name
ORDER BY query_count DESC;"""
    if entity_type_upper == "WAREHOUSE" and "CACHE" in category_upper:
        return f"""SELECT warehouse_name, COUNT(*) AS query_count,
       ROUND(SUM(bytes_scanned * percentage_scanned_from_cache) / NULLIF(SUM(bytes_scanned), 0), 2) AS cache_pct,
       SUM(bytes_scanned) / POWER(1024, 3) AS gb_scanned,
       MAX(start_time) AS last_seen
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
  AND warehouse_name = {entity_sql}
  AND bytes_scanned > 0
GROUP BY warehouse_name;"""
    if entity_type_upper == "WAREHOUSE":
        return f"""SELECT warehouse_name, COUNT(*) AS query_count,
       SUM(COALESCE(queued_overload_time, 0)) / 1000 AS queued_sec,
       SUM(COALESCE(bytes_spilled_to_remote_storage, 0)) / POWER(1024, 3) AS remote_spill_gb,
       MAX(start_time) AS last_seen
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
  AND warehouse_name = {entity_sql}
GROUP BY warehouse_name;"""
    if entity_type_upper == "DR_GROUP":
        return """SHOW FAILOVER GROUPS;
SHOW REPLICATION GROUPS;
SELECT replication_group_name, phase_name, start_time, end_time, credits_used, error
FROM SNOWFLAKE.ACCOUNT_USAGE.REPLICATION_GROUP_USAGE_HISTORY
ORDER BY start_time DESC
LIMIT 100;"""
    return str(entity or "")


def _architecture_sla_hours(tier: object) -> float:
    tier_text = str(tier or "").upper()
    if "TIER 0" in tier_text:
        return 24.0
    if "TIER 1" in tier_text:
        return 72.0
    return 168.0


def _enrich_architecture_context(
    frame: pd.DataFrame,
    *,
    entity_col: str,
    entity_type: str,
    category: str,
    company: str,
    environment: str,
    objective_entity_col: str | None = None,
    objective_entity_type: str | None = None,
    directory: pd.DataFrame | None = None,
    objectives: pd.DataFrame | None = None,
    days: int = 30,
) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame() if frame is None else frame
    view = frame.copy()
    view.columns = [str(col).upper() for col in view.columns]
    entity_col = str(entity_col or "ENTITY").upper()
    objective_entity_col = str(objective_entity_col or entity_col).upper()
    objective_entity_type = str(objective_entity_type or entity_type or "ARCHITECTURE").upper()
    objectives = objectives if objectives is not None else _architecture_objectives_frame(company)
    if directory is None:
        directory = load_owner_directory("Architecture Readiness")

    rows = []
    for _, row in view.iterrows():
        entity = row.get(entity_col) or row.get("ENTITY") or row.get("GROUP_NAME") or "Architecture scope"
        objective_entity = row.get(objective_entity_col) or entity
        objective = _best_architecture_objective(
            objective_entity,
            objective_entity_type,
            company=company,
            objectives=objectives,
        )
        owner_seed = objective.get("OWNER") or "DBA / Platform Architecture"
        context = resolve_owner_context(
            row,
            directory=directory,
            entity=entity,
            entity_type=objective_entity_type,
            owner=owner_seed,
            category=category,
            alert_type="Architecture Readiness",
        )
        objective_source = (
            f"ARCHITECTURE_OBJECTIVES:{objective.get('ENTITY_TYPE', objective_entity_type)}:"
            f"{objective.get('ENTITY_PATTERN', '*')}"
            if objective
            else "ARCHITECTURE_OBJECTIVES:missing"
        )
        severity = str(row.get("SEVERITY") or "Medium")
        service_tier = objective.get("SERVICE_TIER") or "Tier 2"
        approval_required = severity in {"Critical", "High", "Medium"} or "TIER 0" in str(service_tier).upper()
        expected_env = objective.get("EXPECTED_ENVIRONMENT") or "ALL"
        rpo = objective.get("RPO_MINUTES", "")
        rto = objective.get("RTO_MINUTES", "")
        verification_query = row.get("VERIFICATION_QUERY") or row.get("PROOF_SQL") or _architecture_verification_sql(
            entity,
            objective_entity_type,
            category,
            days=days,
        )
        readiness = "Ready to Queue"
        if not context.get("OWNER_EMAIL") or not context.get("APPROVAL_GROUP"):
            readiness = "Owner Route Gap"
        elif objective_source.endswith(":*") or "missing" in objective_source:
            readiness = "Objective Needs Specific Owner"
        rows.append({
            "ENTITY_NAME": entity,
            "OWNER": context.get("OWNER") or owner_seed,
            "OWNER_EMAIL": context.get("OWNER_EMAIL", ""),
            "ONCALL_PRIMARY": context.get("ONCALL_PRIMARY", ""),
            "ONCALL_SECONDARY": context.get("ONCALL_SECONDARY", ""),
            "APPROVAL_GROUP": context.get("APPROVAL_GROUP") or objective.get("APPROVAL_GROUP", ""),
            "ESCALATION_TARGET": context.get("ESCALATION_TARGET", ""),
            "OWNER_SOURCE": context.get("OWNER_SOURCE", ""),
            "OWNER_EVIDENCE": context.get("OWNER_EVIDENCE", ""),
            "WORKLOAD_CLASS": objective.get("WORKLOAD_CLASS", "Unregistered architecture scope"),
            "SERVICE_TIER": service_tier,
            "EXPECTED_ENVIRONMENT": expected_env,
            "RPO_MINUTES": rpo,
            "RTO_MINUTES": rto,
            "ISOLATION_POLICY": objective.get("ISOLATION_POLICY", ""),
            "CACHE_POLICY": objective.get("CACHE_POLICY", ""),
            "CLUSTERING_POLICY": objective.get("CLUSTERING_POLICY", ""),
            "DR_POLICY": objective.get("DR_POLICY", ""),
            "OBJECTIVE_SOURCE": objective_source,
            "OBJECTIVE_EVIDENCE": (
                f"workload={objective.get('WORKLOAD_CLASS', 'unregistered')}; "
                f"tier={service_tier}; env={expected_env}; rpo={rpo}; rto={rto}"
            ),
            "APPROVAL_REQUIRED": "Yes" if approval_required else "No",
            "APPROVER": context.get("APPROVAL_GROUP") or objective.get("APPROVAL_GROUP", "DBA Lead"),
            "QUEUE_READINESS": readiness,
            "ARCHITECTURE_DECISION_NOTE": (
                f"{category}: {severity}; {objective.get('WORKLOAD_CLASS', 'unregistered')} "
                f"({service_tier}); RPO {rpo}m / RTO {rto}m; approval={'required' if approval_required else 'not required'}."
            ),
            "VERIFICATION_QUERY": verification_query,
            "RECOVERY_SLA_TARGET_HOURS": _architecture_sla_hours(service_tier),
        })
    enriched = pd.concat([view.reset_index(drop=True), pd.DataFrame(rows)], axis=1)
    return enriched


def _architecture_source_health_rows(
    state: dict,
    company: str,
    environment: str,
) -> pd.DataFrame:
    definitions = [
        {
            "surface": "Workload isolation",
            "frame_key": "arch_iso_df",
            "meta_key": "arch_iso_meta",
            "days_key": "arch_iso_days",
            "limit_key": "arch_iso_limit",
            "source": "Live ACCOUNT_USAGE.QUERY_HISTORY",
            "confidence": "Delayed Snowflake metadata",
        },
        {
            "surface": "Clustering strategy",
            "frame_key": "arch_cluster_df",
            "meta_key": "arch_cluster_meta",
            "limit_key": "arch_cluster_limit",
            "source": "Live ACCOUNT_USAGE.TABLES plus selected proof SQL",
            "confidence": "Manual validation required",
        },
        {
            "surface": "Cache optimization",
            "frame_key": "arch_cache_df",
            "meta_key": "arch_cache_meta",
            "days_key": "arch_cache_days",
            "limit_key": "arch_cache_limit",
            "source": "Live ACCOUNT_USAGE.QUERY_HISTORY + warehouse inventory",
            "confidence": "Delayed Snowflake metadata",
        },
        {
            "surface": "DR readiness",
            "frame_key": "arch_dr_readiness",
            "meta_key": "arch_dr_meta",
            "days_key": "arch_dr_days",
            "source": "SHOW failover/replication groups + replication usage history",
            "confidence": "Manual and delayed metadata",
        },
        {
            "surface": "Architecture objectives",
            "frame_key": "arch_objectives_df",
            "meta_key": "arch_objectives_meta",
            "source": "Config architecture objective register",
            "confidence": "Manual objective register",
        },
        {
            "surface": "AI agent and MCP inventory",
            "frame_key": "arch_ai_inventory",
            "meta_key": "arch_ai_inventory_meta",
            "source": "SHOW AGENTS IN ACCOUNT + SHOW MCP SERVERS IN ACCOUNT",
            "confidence": "Live metadata through cached SHOW statements",
        },
        {
            "surface": "AI usage guardrails",
            "frame_key": "arch_ai_usage",
            "meta_key": "arch_ai_usage_meta",
            "days_key": "arch_ai_usage_days",
            "limit_key": "arch_ai_usage_limit",
            "source": "ACCOUNT_USAGE Cortex Agent and Snowflake Intelligence usage history",
            "confidence": "Delayed Snowflake AI usage metadata",
        },
        {
            "surface": "Openflow operations",
            "frame_key": "arch_openflow_usage",
            "meta_key": "arch_openflow_meta",
            "days_key": "arch_openflow_days",
            "limit_key": "arch_openflow_limit",
            "source": "ACCOUNT_USAGE.OPENFLOW_USAGE_HISTORY",
            "confidence": "Delayed Snowflake Openflow usage metadata",
        },
        {
            "surface": "Horizon and semantic trust",
            "frame_key": "arch_horizon_readiness",
            "meta_key": "arch_horizon_meta",
            "source": "LIMIT 0 probes of governance, semantic, Trust Center, and AI change history views",
            "confidence": "Capability visibility and privilege readiness",
        },
        {
            "surface": "Forward platform controls",
            "frame_key": "arch_forward_controls",
            "meta_key": "arch_forward_controls_meta",
            "source": "Config forward-platform control register",
            "confidence": "Manual DBA governance register",
        },
    ]
    rows = []
    for item in definitions:
        frame = state.get(item["frame_key"])
        days = state.get(item.get("days_key"), None)
        row_limit = state.get(item.get("limit_key"), None)
        expected_meta = _architecture_scope_meta(
            company,
            environment,
            item["surface"],
            days=days,
            row_limit=row_limit,
            state=state,
        )
        loaded = isinstance(frame, pd.DataFrame)
        if not loaded:
            status = "Not Loaded"
        elif not _architecture_meta_matches(state.get(item["meta_key"]), expected_meta):
            status = "Stale"
        elif frame.empty:
            status = "No Rows"
        else:
            status = "Loaded"
        rank = {
            "Stale": 0,
            "Loaded": 1,
            "No Rows": 2,
            "Not Loaded": 3,
        }.get(status, 9)
        rows.append({
            "SURFACE": item["surface"],
            "STATE": status,
            "STATE_RANK": rank,
            "SOURCE": item["source"],
            "CONFIDENCE": item["confidence"],
            "ROWS": len(frame) if loaded else 0,
            "SCOPE": f"{company} / {environment}",
            "NEXT_ACTION": (
                "Reload this evidence after changing filters."
                if status == "Stale"
                else "Load only when this architecture surface is part of the current review."
                if status == "Not Loaded"
                else "Use this evidence with owner, objective, and approval context."
            ),
        })
    return pd.DataFrame(rows).sort_values(["STATE_RANK", "SURFACE"])


def _failure_expr(cols: set[str], alias: str = "q") -> str:
    if "ERROR_CODE" in cols:
        return f"{alias}.error_code IS NOT NULL"
    return f"UPPER({alias}.execution_status) = 'FAILED_WITH_ERROR'"


def _load_workload_isolation(session, days: int, row_limit: int) -> pd.DataFrame:
    company = get_active_company()
    environment = get_active_environment()
    cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        [
            "ERROR_CODE",
            "QUEUED_OVERLOAD_TIME",
            "BYTES_SPILLED_TO_REMOTE_STORAGE",
            "BYTES_SCANNED",
        ],
    ))
    failed_pred = _failure_expr(cols, "q")
    queue_expr = "SUM(q.queued_overload_time)/1000" if "QUEUED_OVERLOAD_TIME" in cols else "0::FLOAT"
    spill_expr = (
        "SUM(q.bytes_spilled_to_remote_storage)/POWER(1024,3)"
        if "BYTES_SPILLED_TO_REMOTE_STORAGE" in cols
        else "0::FLOAT"
    )
    scanned_expr = "SUM(q.bytes_scanned)/POWER(1024,3)" if "BYTES_SCANNED" in cols else "0::FLOAT"
    filters = get_global_filter_clause(
        date_col="q.start_time",
        wh_col="q.warehouse_name",
        user_col="q.user_name",
        role_col="q.role_name",
        db_col="q.database_name",
    )
    df = run_query(f"""
        SELECT
            COALESCE(q.database_name, 'NO_DATABASE') AS database_name,
            q.warehouse_name,
            COUNT(*) AS query_count,
            COUNT(DISTINCT q.user_name) AS users,
            COUNT(DISTINCT q.role_name) AS roles,
            SUM(IFF({failed_pred}, 1, 0)) AS failed_queries,
            ROUND(AVG(q.total_elapsed_time)/1000, 2) AS avg_elapsed_sec,
            ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY q.total_elapsed_time)/1000, 2) AS p95_elapsed_sec,
            ROUND({queue_expr}, 2) AS queued_sec,
            ROUND({spill_expr}, 2) AS remote_spill_gb,
            ROUND({scanned_expr}, 2) AS gb_scanned,
            MAX(q.start_time) AS last_seen
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          AND q.database_name IS NOT NULL
          {filters}
        GROUP BY database_name, q.warehouse_name
        ORDER BY query_count DESC
        LIMIT {int(row_limit)}
    """, ttl_key=f"arch_isolation_{company}_{days}_{row_limit}", tier="historical", section="Architecture Readiness")
    if df.empty:
        return df

    db_wh_count = df.groupby("DATABASE_NAME")["WAREHOUSE_NAME"].nunique().to_dict()
    wh_db_count = df.groupby("WAREHOUSE_NAME")["DATABASE_NAME"].nunique().to_dict()
    df["DATABASE_WAREHOUSES"] = df["DATABASE_NAME"].map(db_wh_count).fillna(0).astype(int)
    df["WAREHOUSE_DATABASES"] = df["WAREHOUSE_NAME"].map(wh_db_count).fillna(0).astype(int)

    def classify(row: pd.Series) -> pd.Series:
        queued = safe_float(row.get("QUEUED_SEC"))
        spill = safe_float(row.get("REMOTE_SPILL_GB"))
        failures = safe_int(row.get("FAILED_QUERIES"))
        wh_dbs = safe_int(row.get("WAREHOUSE_DATABASES"))
        db_whs = safe_int(row.get("DATABASE_WAREHOUSES"))
        signals = []
        if wh_dbs >= 4:
            signals.append("warehouse serves many databases")
        if db_whs >= 3:
            signals.append("database spans many warehouses")
        if queued > 60:
            signals.append("queue pressure")
        if spill > 1:
            signals.append("remote spill")
        if failures > 0:
            signals.append("query failures")
        if queued > 300 or (wh_dbs >= 5 and (spill > 5 or failures >= 10)):
            severity = "High"
            decision = "Isolate"
            action = "Move this database workload to a dedicated or more narrowly shared warehouse before tuning size."
        elif wh_dbs >= 4 and (queued > 60 or spill > 1):
            severity = "High"
            decision = "Isolate"
            action = "Separate noisy database traffic from shared warehouse consumers, then remeasure queue and spill."
        elif db_whs >= 3:
            severity = "Medium"
            decision = "Standardize"
            action = "Pick the intended warehouse route for this database and clean up cross-warehouse client defaults."
        elif queued > 60 or spill > 1 or failures:
            severity = "Medium"
            decision = "Tune"
            action = "Keep isolation but tune query shape, warehouse settings, or owner routing for this workload."
        else:
            severity = "Low"
            decision = "Keep"
            action = "No isolation move from this evidence; watch trend before changing routing."
        return pd.Series({
            "SEVERITY": severity,
            "ISOLATION_DECISION": decision,
            "FINDING": ", ".join(signals) if signals else "No material isolation signal",
            "DBA_ACTION": action,
            "PROOF_SQL": (
                "SELECT database_name, warehouse_name, COUNT(*) query_count "
                "FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY "
                f"WHERE start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP()) "
                "GROUP BY database_name, warehouse_name ORDER BY query_count DESC;"
            ),
        })

    annotated = pd.concat([df, df.apply(classify, axis=1)], axis=1)
    annotated = _enrich_architecture_context(
        annotated,
        entity_col="DATABASE_NAME",
        entity_type="DATABASE",
        category="Workload Isolation",
        company=company,
        environment=environment,
        directory=load_owner_directory("Architecture Readiness"),
        days=days,
    )
    annotated["_SEVERITY_RANK"] = annotated["SEVERITY"].apply(_severity_rank)
    return annotated.sort_values(
        ["_SEVERITY_RANK", "QUEUED_SEC", "REMOTE_SPILL_GB", "QUERY_COUNT"],
        ascending=[True, False, False, False],
    ).drop(columns=["_SEVERITY_RANK"])


def _load_clustering_strategy(session, min_gb: float, row_limit: int) -> pd.DataFrame:
    company = get_active_company()
    environment = get_active_environment()
    cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.TABLES",
        [
            "TABLE_CATALOG",
            "TABLE_SCHEMA",
            "TABLE_NAME",
            "TABLE_TYPE",
            "ROW_COUNT",
            "BYTES",
            "CLUSTERING_KEY",
            "AUTO_CLUSTERING_ON",
            "LAST_ALTERED",
            "DELETED",
        ],
    ))
    if not {"TABLE_CATALOG", "TABLE_SCHEMA", "TABLE_NAME"}.issubset(cols):
        return pd.DataFrame()
    bytes_expr = "bytes/POWER(1024,3)" if "BYTES" in cols else "0::FLOAT"
    rows_expr = "row_count" if "ROW_COUNT" in cols else "0::NUMBER"
    cluster_expr = "COALESCE(TO_VARCHAR(clustering_key), '')" if "CLUSTERING_KEY" in cols else "''"
    auto_expr = "COALESCE(TO_VARCHAR(auto_clustering_on), 'UNKNOWN')" if "AUTO_CLUSTERING_ON" in cols else "'UNKNOWN'"
    last_expr = "last_altered" if "LAST_ALTERED" in cols else "NULL::TIMESTAMP_NTZ"
    deleted_pred = "AND deleted IS NULL" if "DELETED" in cols else ""
    table_type_pred = "AND table_type = 'BASE TABLE'" if "TABLE_TYPE" in cols else ""
    filters = get_global_filter_clause(
        date_col="",
        wh_col="",
        user_col="",
        role_col="",
        db_col="table_catalog",
    )
    df = run_query(f"""
        SELECT
            table_catalog,
            table_schema,
            table_name,
            {rows_expr} AS row_count,
            ROUND({bytes_expr}, 2) AS table_gb,
            {cluster_expr} AS clustering_key,
            {auto_expr} AS auto_clustering_on,
            {last_expr} AS last_altered
        FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES
        WHERE table_catalog IS NOT NULL
          AND table_schema IS NOT NULL
          AND table_name IS NOT NULL
          {deleted_pred}
          {table_type_pred}
          {filters}
          AND {bytes_expr} >= {float(min_gb)}
        ORDER BY {bytes_expr} DESC
        LIMIT {int(row_limit)}
    """, ttl_key=f"arch_clustering_{company}_{min_gb}_{row_limit}", tier="historical", section="Architecture Readiness")
    if df.empty:
        return df

    def classify(row: pd.Series) -> pd.Series:
        gb = safe_float(row.get("TABLE_GB"))
        rows = safe_float(row.get("ROW_COUNT"))
        key = str(row.get("CLUSTERING_KEY") or "").strip()
        auto = str(row.get("AUTO_CLUSTERING_ON") or "UNKNOWN").upper()
        fqn = _table_fqn(row)
        if gb >= 100 and not key:
            severity = "High"
            decision = "Validate clustering candidate"
            action = "Check query predicates and clustering depth for this table before adding a key."
        elif gb >= 25 and rows >= 10000000 and not key:
            severity = "Medium"
            decision = "Review predicate pattern"
            action = "Confirm repeated selective filters first; do not cluster just because the table is large."
        elif key and auto in {"OFF", "FALSE", "NO"}:
            severity = "Medium"
            decision = "Review suspended clustering"
            action = "Verify whether reclustering was intentionally suspended after a clone or cost event."
        elif key:
            severity = "Low"
            decision = "Monitor clustering cost"
            action = "Track automatic clustering cost and depth trend; avoid changing keys without ROI proof."
        else:
            severity = "Info"
            decision = "No immediate clustering action"
            action = "Do not cluster from size alone; use query predicate evidence first."
        proof_sql = (
            f"SELECT SYSTEM$CLUSTERING_INFORMATION('{fqn}') AS clustering_info;\n"
            f"SELECT SYSTEM$CLUSTERING_DEPTH('{fqn}') AS clustering_depth;"
        )
        return pd.Series({
            "SEVERITY": severity,
            "CLUSTERING_DECISION": decision,
            "FINDING": decision,
            "DBA_ACTION": action,
            "PROOF_SQL": proof_sql,
        })

    annotated = pd.concat([df, df.apply(classify, axis=1)], axis=1)
    annotated["ENTITY"] = annotated.apply(_table_fqn, axis=1)
    annotated = _enrich_architecture_context(
        annotated,
        entity_col="ENTITY",
        entity_type="TABLE",
        objective_entity_col="TABLE_CATALOG",
        objective_entity_type="DATABASE",
        category="Clustering Strategy",
        company=company,
        environment=environment,
        directory=load_owner_directory("Architecture Readiness"),
    )
    annotated["_SEVERITY_RANK"] = annotated["SEVERITY"].apply(_severity_rank)
    return annotated.sort_values(
        ["_SEVERITY_RANK", "TABLE_GB", "ROW_COUNT"],
        ascending=[True, False, False],
    ).drop(columns=["_SEVERITY_RANK"])


def _load_cache_optimization(session, days: int, row_limit: int) -> pd.DataFrame:
    company = get_active_company()
    environment = get_active_environment()
    cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        [
            "BYTES_SCANNED",
            "PERCENTAGE_SCANNED_FROM_CACHE",
            "QUERY_HASH",
            "QUERY_PARAMETERIZED_HASH",
        ],
    ))
    if "BYTES_SCANNED" not in cols:
        return pd.DataFrame()
    cache_expr = (
        "SUM(q.bytes_scanned * q.percentage_scanned_from_cache) / NULLIF(SUM(q.bytes_scanned), 0)"
        if "PERCENTAGE_SCANNED_FROM_CACHE" in cols
        else "NULL::FLOAT"
    )
    hash_expr = (
        "COALESCE(TO_VARCHAR(q.query_parameterized_hash), TO_VARCHAR(q.query_hash), q.query_text)"
        if "QUERY_PARAMETERIZED_HASH" in cols and "QUERY_HASH" in cols
        else ("COALESCE(TO_VARCHAR(q.query_hash), q.query_text)" if "QUERY_HASH" in cols else "q.query_text")
    )
    filters = get_global_filter_clause(
        date_col="q.start_time",
        wh_col="q.warehouse_name",
        user_col="q.user_name",
        role_col="q.role_name",
        db_col="q.database_name",
    )
    df = run_query(f"""
        SELECT
            q.warehouse_name,
            COALESCE(q.database_name, 'NO_DATABASE') AS top_database,
            COUNT(*) AS query_count,
            COUNT(DISTINCT {hash_expr}) AS query_families,
            ROUND(SUM(q.bytes_scanned)/POWER(1024,3), 2) AS gb_scanned,
            ROUND({cache_expr}, 2) AS warehouse_cache_pct,
            ROUND(AVG(q.total_elapsed_time)/1000, 2) AS avg_elapsed_sec,
            MAX(q.start_time) AS last_seen
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          AND q.bytes_scanned > 0
          {filters}
        GROUP BY q.warehouse_name, COALESCE(q.database_name, 'NO_DATABASE')
        ORDER BY gb_scanned DESC
        LIMIT {int(row_limit)}
    """, ttl_key=f"arch_cache_{company}_{days}_{row_limit}", tier="historical", section="Architecture Readiness")
    if df.empty:
        return df

    wh_inventory = load_warehouse_inventory(session, company)
    if not wh_inventory.empty and "NAME" in wh_inventory.columns:
        wh_settings = wh_inventory[["NAME", "AUTO_SUSPEND", "AUTO_RESUME", "WAREHOUSE_SIZE", "MIN_CLUSTER_COUNT", "MAX_CLUSTER_COUNT"]].copy()
        wh_settings = wh_settings.rename(columns={"NAME": "WAREHOUSE_NAME"})
        df = df.merge(wh_settings, on="WAREHOUSE_NAME", how="left")
    else:
        for col in ["AUTO_SUSPEND", "AUTO_RESUME", "WAREHOUSE_SIZE", "MIN_CLUSTER_COUNT", "MAX_CLUSTER_COUNT"]:
            df[col] = ""

    def classify(row: pd.Series) -> pd.Series:
        cache_pct = safe_float(row.get("WAREHOUSE_CACHE_PCT"))
        query_count = safe_int(row.get("QUERY_COUNT"))
        families = max(safe_int(row.get("QUERY_FAMILIES")), 1)
        repeats = max(query_count - families, 0)
        auto_suspend = safe_int(row.get("AUTO_SUSPEND"))
        repeated_ratio = repeats / max(query_count, 1)
        if cache_pct < 20 and repeated_ratio >= 0.35 and auto_suspend and auto_suspend <= 60:
            severity = "High"
            decision = "Cache-hostile suspend"
            action = "For BI/reporting workloads, test a longer auto-suspend or route repeated queries to a warmer warehouse."
        elif cache_pct < 20 and repeated_ratio >= 0.35:
            severity = "Medium"
            decision = "Poor cache reuse"
            action = "Canonicalize repeated SQL and keep similar workloads on the same warehouse before resizing."
        elif cache_pct < 10 and safe_float(row.get("GB_SCANNED")) > 100:
            severity = "Medium"
            decision = "Scan-heavy no-cache workload"
            action = "Tune predicates, clustering/search optimization, or data model; warehouse cache alone will not fix this."
        else:
            severity = "Low"
            decision = "Cache acceptable"
            action = "No cache-specific change from this evidence."
        return pd.Series({
            "SEVERITY": severity,
            "CACHE_DECISION": decision,
            "REPEATED_QUERY_RATIO": round(repeated_ratio * 100, 1),
            "FINDING": f"{decision}; cache={cache_pct:.1f}, repeated={repeated_ratio * 100:.1f}%",
            "DBA_ACTION": action,
            "PROOF_SQL": (
                "SELECT warehouse_name, COUNT(*) query_count, "
                "SUM(bytes_scanned*percentage_scanned_from_cache)/NULLIF(SUM(bytes_scanned),0) cache_pct "
                "FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY "
                f"WHERE start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP()) "
                "GROUP BY warehouse_name ORDER BY cache_pct ASC;"
            ),
        })

    annotated = pd.concat([df, df.apply(classify, axis=1)], axis=1)
    annotated = _enrich_architecture_context(
        annotated,
        entity_col="WAREHOUSE_NAME",
        entity_type="WAREHOUSE",
        category="Cache Optimization",
        company=company,
        environment=environment,
        directory=load_owner_directory("Architecture Readiness"),
        days=days,
    )
    annotated["_SEVERITY_RANK"] = annotated["SEVERITY"].apply(_severity_rank)
    return annotated.sort_values(
        ["_SEVERITY_RANK", "GB_SCANNED", "QUERY_COUNT"],
        ascending=[True, False, False],
    ).drop(columns=["_SEVERITY_RANK"])


def _load_dr_readiness(session, days: int) -> dict:
    company = get_active_company()
    environment = get_active_environment()
    failover = show_to_df(session, "SHOW FAILOVER GROUPS")
    replication = show_to_df(session, "SHOW REPLICATION GROUPS")
    for key_df in (failover, replication):
        if key_df is not None and not key_df.empty:
            key_df.columns = [str(col).upper() for col in key_df.columns]

    usage = run_query(f"""
        SELECT
            replication_group_name,
            phase_name,
            start_time,
            end_time,
            DATEDIFF('minute', start_time, COALESCE(end_time, CURRENT_TIMESTAMP())) AS phase_minutes,
            credits_used,
            bytes_transferred/POWER(1024,3) AS gb_transferred,
            error
        FROM SNOWFLAKE.ACCOUNT_USAGE.REPLICATION_GROUP_USAGE_HISTORY
        WHERE start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
        ORDER BY start_time DESC
        LIMIT 300
    """, ttl_key=f"arch_dr_usage_{company}_{days}", tier="historical", section="Architecture Readiness")

    group_rows = []
    for source, df in (("FAILOVER GROUP", failover), ("REPLICATION GROUP", replication)):
        if df is None or df.empty:
            continue
        name_col = next((col for col in ("NAME", "GROUP_NAME", "REPLICATION_GROUP_NAME", "FAILOVER_GROUP_NAME") if col in df.columns), "")
        db_col = next((col for col in ("DATABASES", "ALLOWED_DATABASES", "OBJECT_TYPES") if col in df.columns), "")
        schedule_col = next((col for col in ("REPLICATION_SCHEDULE", "SCHEDULE") if col in df.columns), "")
        for _, row in df.iterrows():
            name = str(row.get(name_col) or "UNKNOWN")
            dbs = str(row.get(db_col) or "")
            schedule = str(row.get(schedule_col) or "")
            severity = "Medium"
            finding = "DR group visible; verify lag and drill evidence."
            action = "Confirm protected objects, target account, refresh schedule, client redirect, and latest drill result."
            if not dbs:
                severity = "High"
                finding = "Protected object list not visible to this role."
                action = "Reload with ACCOUNTADMIN/SYSADMIN evidence or document the group object list from Snowflake."
            if not schedule:
                severity = "High" if severity != "High" else severity
                finding = f"{finding} Replication schedule is not visible."
            group_rows.append({
                "GROUP_TYPE": source,
                "GROUP_NAME": name,
                "SEVERITY": severity,
                "FINDING": finding,
                "DBA_ACTION": action,
                "OBJECT_SCOPE": dbs,
                "SCHEDULE": schedule,
                "PROOF_SQL": "SHOW FAILOVER GROUPS; SHOW REPLICATION GROUPS;",
            })

    if not group_rows:
        group_rows.append({
            "GROUP_TYPE": "NONE VISIBLE",
            "GROUP_NAME": "No failover or replication group visible",
            "SEVERITY": "Critical",
            "FINDING": "No Snowflake DR group is visible to the active role.",
            "DBA_ACTION": "Verify whether ALFA has failover/replication groups and document RPO/RTO, target account, client redirect, and drill cadence.",
            "OBJECT_SCOPE": "",
            "SCHEDULE": "",
            "PROOF_SQL": "SHOW FAILOVER GROUPS; SHOW REPLICATION GROUPS;",
        })

    readiness = pd.DataFrame(group_rows)
    readiness = _enrich_architecture_context(
        readiness,
        entity_col="GROUP_NAME",
        entity_type="DR_GROUP",
        category="Disaster Recovery",
        company=company,
        environment=environment,
        directory=load_owner_directory("Architecture Readiness"),
        days=days,
    )
    readiness["_SEVERITY_RANK"] = readiness["SEVERITY"].apply(_severity_rank)
    readiness = readiness.sort_values(["_SEVERITY_RANK", "GROUP_TYPE", "GROUP_NAME"]).drop(columns=["_SEVERITY_RANK"])
    return {
        "readiness": readiness,
        "failover": failover if failover is not None else pd.DataFrame(),
        "replication": replication if replication is not None else pd.DataFrame(),
        "usage": usage,
    }


def _queue_architecture_findings(session, frame: pd.DataFrame, source: str, entity_col: str, category: str) -> None:
    if frame is None or frame.empty:
        st.info("No findings are loaded to queue.")
        return
    company = get_active_company()
    environment = get_active_environment()
    actionable = frame[frame["SEVERITY"].isin(["Critical", "High", "Medium"])].copy() if "SEVERITY" in frame.columns else frame.copy()
    if actionable.empty:
        st.success("No Critical/High/Medium architecture findings to queue.")
        return
    actions = []
    for _, row in actionable.head(50).iterrows():
        entity = str(row.get(entity_col) or row.get("ENTITY") or "Architecture scope")
        severity = str(row.get("SEVERITY") or "Medium")
        owner = str(row.get("OWNER") or "DBA / Platform Architecture")
        approval_required = str(row.get("APPROVAL_REQUIRED") or "Yes")
        approval_status = "Requested" if approval_required == "Yes" else "Not Required"
        verification_query = str(row.get("VERIFICATION_QUERY") or row.get("PROOF_SQL") or "")
        actions.append({
            "Source": source,
            "Category": category,
            "Severity": severity,
            "Entity Type": category,
            "Entity": entity,
            "Owner": owner,
            "Owner Email": str(row.get("OWNER_EMAIL") or ""),
            "Oncall Primary": str(row.get("ONCALL_PRIMARY") or ""),
            "Oncall Secondary": str(row.get("ONCALL_SECONDARY") or ""),
            "Approval Group": str(row.get("APPROVAL_GROUP") or ""),
            "Escalation Target": str(row.get("ESCALATION_TARGET") or ""),
            "Owner Source": str(row.get("OWNER_SOURCE") or ""),
            "Owner Evidence": str(row.get("OWNER_EVIDENCE") or row.get("OBJECTIVE_EVIDENCE") or ""),
            "Approver": str(row.get("APPROVER") or row.get("APPROVAL_GROUP") or owner),
            "Finding": str(row.get("FINDING") or row.get("CLUSTERING_DECISION") or row.get("CACHE_DECISION") or ""),
            "Action": str(row.get("DBA_ACTION") or "Review architecture evidence and document the decision."),
            "Estimated Monthly Savings": 0,
            "Generated SQL Fix": "-- Read-only architecture finding. Generate change SQL only after owner approval.",
            "Proof Query": str(row.get("PROOF_SQL") or ""),
            "Verification Query": verification_query,
            "Verification Status": "Pending",
            "Owner Approval Status": approval_status,
            "Owner Approval Note": str(row.get("ARCHITECTURE_DECISION_NOTE") or row.get("OBJECTIVE_EVIDENCE") or ""),
            "Recovery Audit State": "Architecture Review Pending",
            "Recovery SLA State": "Open Architecture Review",
            "Recovery SLA Target Hours": safe_float(row.get("RECOVERY_SLA_TARGET_HOURS")) or 72.0,
            "Recovery Evidence": str(row.get("OBJECTIVE_EVIDENCE") or row.get("QUEUE_READINESS") or ""),
            "Company": company,
            "Environment": environment,
        })
    saved = upsert_actions(session, actions)
    st.success(f"Saved {saved} architecture finding(s) to the action queue.")


def _render_loaded_metrics(df: pd.DataFrame, label: str) -> None:
    if df is None or df.empty:
        st.info(f"No {label} evidence loaded for the selected scope.")
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rows", f"{len(df):,}")
    c2.metric("Critical", f"{int((df.get('SEVERITY', pd.Series(dtype=str)) == 'Critical').sum()):,}")
    c3.metric("High", f"{int((df.get('SEVERITY', pd.Series(dtype=str)) == 'High').sum()):,}")
    c4.metric("Medium", f"{int((df.get('SEVERITY', pd.Series(dtype=str)) == 'Medium').sum()):,}")


def _render_forward_watchlist() -> None:
    rows = pd.DataFrame([
        {
            "CAPABILITY": "Adaptive Compute / warehouse evolution",
            "WHY_IT_MATTERS": "DBAs will need to distinguish concurrency scaling, single-query acceleration, and auto-managed compute decisions.",
            "OVERWATCH_CONTROL": "Track warehouse pressure, multi-cluster/QAS posture, workload routing, and before/after cost verification.",
            "NEXT_BUILD": "Add an adaptive-compute readiness flag once account metadata exposes enough signals.",
            "PRIORITY": "High",
        },
        {
            "CAPABILITY": "Openflow and managed data movement",
            "WHY_IT_MATTERS": "More ingestion paths mean more operational failure, owner, freshness, and cost surfaces.",
            "OVERWATCH_CONTROL": "Extend Pipeline Health and Change & Drift to include connector freshness, failure rates, and owner routes.",
            "NEXT_BUILD": "Inventory external connectors and map them to databases, tasks, and alert rules.",
            "PRIORITY": "High",
        },
        {
            "CAPABILITY": "Cortex AISQL and Snowflake Intelligence",
            "WHY_IT_MATTERS": "AI workloads create new cost, governance, result-quality, and data-access review duties.",
            "OVERWATCH_CONTROL": "Keep Cortex cost attribution, user spike detection, budget controls, and governed prompt context evidence.",
            "NEXT_BUILD": "Add AI workload approval, token/credit budget variance, and sensitive-data access checks.",
            "PRIORITY": "High",
        },
        {
            "CAPABILITY": "Iceberg and open table governance",
            "WHY_IT_MATTERS": "Open table formats shift reliability work toward catalog, file layout, retention, and cross-engine access.",
            "OVERWATCH_CONTROL": "Track object ownership, freshness, storage growth, failed refreshes, and external access exposure.",
            "NEXT_BUILD": "Add Iceberg table inventory and stale metadata/file-layout risk checks.",
            "PRIORITY": "Medium",
        },
        {
            "CAPABILITY": "Agentic remediation",
            "WHY_IT_MATTERS": "Automated recommendations are only acceptable when evidence, approval, rollback, and verification are explicit.",
            "OVERWATCH_CONTROL": "Route every recommendation through owner approval, generated proof SQL, action queue, and closure evidence.",
            "NEXT_BUILD": "Add reviewed remediation playbooks for cache, clustering, isolation, and DR gaps.",
            "PRIORITY": "Medium",
        },
    ])
    render_priority_dataframe(
        rows,
        title="Forward architecture watchlist",
        priority_columns=["PRIORITY", "CAPABILITY", "WHY_IT_MATTERS", "OVERWATCH_CONTROL", "NEXT_BUILD"],
        sort_by=["PRIORITY", "CAPABILITY"],
        ascending=[True, True],
        raw_label="All forward-looking architecture items",
        height=420,
    )
    download_csv(rows, "architecture_forward_watchlist.csv")


def _platform_futures_frames() -> list[pd.DataFrame]:
    return [
        st.session_state.get("arch_ai_inventory"),
        st.session_state.get("arch_ai_usage"),
        st.session_state.get("arch_openflow_usage"),
        st.session_state.get("arch_horizon_readiness"),
    ]


def _render_platform_futures(session, company: str, environment: str) -> None:
    st.subheader("AI & Platform Futures")
    st.caption(
        "Forward Snowflake controls for agents, MCP servers, AI spend, Openflow, Horizon governance, semantic trust, DR drills, and AI-assisted change."
    )
    controls = build_forward_platform_control_register()
    st.session_state["arch_forward_controls"] = controls
    st.session_state["arch_forward_controls_meta"] = _architecture_scope_meta(
        company,
        environment,
        "Forward platform controls",
    )

    futures_view = st.radio(
        "AI platform futures view",
        (
            "Overview",
            "Agents & MCP",
            "AI Usage",
            "Openflow",
            "Horizon & Semantic",
            "Control Register",
        ),
        horizontal=True,
        label_visibility="collapsed",
        key="arch_platform_futures_view",
    )

    if futures_view == "Overview":
        board = build_platform_futures_board(_platform_futures_frames())
        st.session_state["arch_futures_board"] = board
        c1, c2, c3, c4 = st.columns(4)
        loaded_surfaces = sum(1 for frame in _platform_futures_frames() if isinstance(frame, pd.DataFrame))
        c1.metric("Controls", f"{len(controls):,}")
        c2.metric("Loaded Surfaces", f"{loaded_surfaces:,}/4")
        c3.metric("Open Futures", f"{len(board):,}" if isinstance(board, pd.DataFrame) else "0")
        high_count = (
            int(board["SEVERITY"].isin(["Critical", "High"]).sum())
            if isinstance(board, pd.DataFrame) and not board.empty and "SEVERITY" in board.columns
            else 0
        )
        c4.metric("Critical/High", f"{high_count:,}")
        if board is None or board.empty:
            st.info("Load one of the futures evidence surfaces to build the prioritized board.")
        else:
            render_priority_dataframe(
                board,
                title="Forward platform actions to review first",
                priority_columns=[
                    "SEVERITY", "CONTROL_AREA", "SOURCE_TYPE", "ENTITY_NAME",
                    "FINDING", "DBA_ACTION", "OWNER", "APPROVAL_GROUP",
                    "QUEUE_READINESS",
                ],
                sort_by=["SEVERITY", "CONTROL_AREA", "ENTITY_NAME"],
                ascending=[True, True, True],
                raw_label="All platform futures rows",
                height=380,
            )
            if st.button("Queue Platform Futures Findings", key="arch_futures_queue"):
                _queue_architecture_findings(
                    session,
                    board,
                    "Architecture Readiness - AI Platform Futures",
                    "ENTITY_NAME",
                    "AI & Platform Futures",
                )
            download_csv(board, "architecture_platform_futures_board.csv")
        render_priority_dataframe(
            controls,
            title="Forward platform control register",
            priority_columns=[
                "CONTROL_AREA", "OWNER", "APPROVAL_GROUP", "PRIMARY_EVIDENCE",
                "DBA_DECISION", "AUTOMATION_BOUNDARY",
            ],
            sort_by=["MATCH_PRIORITY", "CONTROL_AREA"],
            ascending=[False, True],
            raw_label="All forward platform controls",
            height=300,
        )

    elif futures_view == "Agents & MCP":
        if st.button("Load Agents and MCP Inventory", key="arch_ai_inventory_load"):
            with st.spinner("Loading Cortex Agent and MCP inventory..."):
                try:
                    st.session_state["arch_ai_inventory"] = load_agent_mcp_inventory(session, company, environment)
                    st.session_state["arch_ai_inventory_meta"] = _architecture_scope_meta(
                        company,
                        environment,
                        "AI agent and MCP inventory",
                    )
                except Exception as exc:
                    st.warning(f"Agent and MCP inventory unavailable: {format_snowflake_error(exc)}")
        df = st.session_state.get("arch_ai_inventory")
        if isinstance(df, pd.DataFrame):
            _render_loaded_metrics(df, "agent and MCP")
            if df.empty:
                st.info("No Cortex Agents or MCP servers are visible to the active role.")
            else:
                render_priority_dataframe(
                    df,
                    title="Agents and MCP servers to govern first",
                    priority_columns=[
                        "SEVERITY", "SOURCE_TYPE", "ENTITY_NAME", "OWNER_ROLE",
                        "FINDING", "DBA_ACTION", "OWNER", "APPROVAL_GROUP",
                        "QUEUE_READINESS",
                    ],
                    sort_by=["SEVERITY", "SOURCE_TYPE", "ENTITY_NAME"],
                    ascending=[True, True, True],
                    raw_label="All agent and MCP rows",
                    height=380,
                )
                if st.button("Queue Agent and MCP Findings", key="arch_ai_inventory_queue"):
                    _queue_architecture_findings(
                        session,
                        df,
                        "Architecture Readiness - Agent & MCP Governance",
                        "ENTITY_NAME",
                        "Agent & MCP Governance",
                    )
                download_csv(df, "architecture_agent_mcp_inventory.csv")

    elif futures_view == "AI Usage":
        c1, c2 = st.columns(2)
        with c1:
            days = st.slider("AI usage lookback days", 1, 90, 7, key="arch_ai_usage_days")
        with c2:
            row_limit = st.slider("Max AI usage rows", 25, 500, 100, step=25, key="arch_ai_usage_limit")
        if st.button("Load AI Usage Guardrails", key="arch_ai_usage_load"):
            with st.spinner("Loading AI usage guardrails..."):
                try:
                    st.session_state["arch_ai_usage"] = load_ai_usage_guardrails(
                        session,
                        days=days,
                        row_limit=row_limit,
                        company=company,
                        environment=environment,
                    )
                    st.session_state["arch_ai_usage_meta"] = _architecture_scope_meta(
                        company,
                        environment,
                        "AI usage guardrails",
                        days=days,
                        row_limit=row_limit,
                    )
                except Exception as exc:
                    st.warning(f"AI usage guardrails unavailable: {format_snowflake_error(exc)}")
        df = st.session_state.get("arch_ai_usage")
        if isinstance(df, pd.DataFrame):
            _render_loaded_metrics(df, "AI usage")
            if df.empty:
                st.info("No Cortex Agent or Snowflake Intelligence usage rows are visible for this scope.")
            else:
                render_priority_dataframe(
                    df,
                    title="AI usage guardrails to review first",
                    priority_columns=[
                        "SEVERITY", "SOURCE_TYPE", "ENTITY_NAME", "USER_NAME",
                        "ROLE_NAME", "INTERFACE_NAME", "REQUESTS", "TOKEN_CREDITS",
                        "AI_FUNCTION_CREDITS", "FINDING", "DBA_ACTION", "OWNER",
                    ],
                    sort_by=["SEVERITY", "TOKEN_CREDITS", "REQUESTS"],
                    ascending=[True, False, False],
                    raw_label="All AI usage rows",
                    height=400,
                )
                if st.button("Queue AI Usage Findings", key="arch_ai_usage_queue"):
                    _queue_architecture_findings(
                        session,
                        df,
                        "Architecture Readiness - AI Spend & Token Guardrails",
                        "ENTITY_NAME",
                        "AI Spend & Token Guardrails",
                    )
                download_csv(df, "architecture_ai_usage_guardrails.csv")

    elif futures_view == "Openflow":
        c1, c2 = st.columns(2)
        with c1:
            days = st.slider("Openflow lookback days", 1, 90, 7, key="arch_openflow_days")
        with c2:
            row_limit = st.slider("Max Openflow rows", 25, 500, 100, step=25, key="arch_openflow_limit")
        if st.button("Load Openflow Operations", key="arch_openflow_load"):
            with st.spinner("Loading Openflow operations..."):
                try:
                    st.session_state["arch_openflow_usage"] = load_openflow_operations(
                        session,
                        days=days,
                        row_limit=row_limit,
                        company=company,
                        environment=environment,
                    )
                    st.session_state["arch_openflow_meta"] = _architecture_scope_meta(
                        company,
                        environment,
                        "Openflow operations",
                        days=days,
                        row_limit=row_limit,
                    )
                except Exception as exc:
                    st.warning(f"Openflow operations unavailable: {format_snowflake_error(exc)}")
        df = st.session_state.get("arch_openflow_usage")
        if isinstance(df, pd.DataFrame):
            _render_loaded_metrics(df, "Openflow")
            if df.empty:
                st.info("No Openflow usage rows are visible to the active role.")
            else:
                render_priority_dataframe(
                    df,
                    title="Openflow runtimes to review first",
                    priority_columns=[
                        "SEVERITY", "ENTITY_NAME", "DATA_PLANE_TYPE", "RUNTIME_TYPE",
                        "HOURS_REPORTED", "TOTAL_CREDITS", "FINDING", "DBA_ACTION",
                        "OWNER", "APPROVAL_GROUP",
                    ],
                    sort_by=["SEVERITY", "TOTAL_CREDITS", "HOURS_REPORTED"],
                    ascending=[True, False, False],
                    raw_label="All Openflow rows",
                    height=380,
                )
                if st.button("Queue Openflow Findings", key="arch_openflow_queue"):
                    _queue_architecture_findings(
                        session,
                        df,
                        "Architecture Readiness - Openflow Operations",
                        "ENTITY_NAME",
                        "Openflow Operations",
                    )
                download_csv(df, "architecture_openflow_operations.csv")

    elif futures_view == "Horizon & Semantic":
        if st.button("Load Horizon and Semantic Readiness", key="arch_horizon_load"):
            with st.spinner("Probing Horizon, semantic, and AI change readiness..."):
                try:
                    st.session_state["arch_horizon_readiness"] = load_horizon_semantic_readiness(session)
                    st.session_state["arch_horizon_meta"] = _architecture_scope_meta(
                        company,
                        environment,
                        "Horizon and semantic trust",
                    )
                except Exception as exc:
                    st.warning(f"Horizon and semantic readiness unavailable: {format_snowflake_error(exc)}")
        df = st.session_state.get("arch_horizon_readiness")
        if isinstance(df, pd.DataFrame):
            _render_loaded_metrics(df, "Horizon and semantic")
            if df.empty:
                st.info("No Horizon or semantic readiness rows were produced.")
            else:
                ready_count = int((df["STATE"] == "Ready").sum()) if "STATE" in df.columns else 0
                mandatory_gaps = (
                    int(((df["MANDATORY"] == "Yes") & (df["STATE"] != "Ready")).sum())
                    if {"MANDATORY", "STATE"}.issubset(df.columns)
                    else 0
                )
                c1, c2, c3 = st.columns(3)
                c1.metric("Ready", f"{ready_count:,}")
                c2.metric("Not Visible", f"{max(len(df) - ready_count, 0):,}")
                c3.metric("Mandatory Gaps", f"{mandatory_gaps:,}")
                render_priority_dataframe(
                    df,
                    title="Horizon, semantic, and AI-change readiness gaps",
                    priority_columns=[
                        "SEVERITY", "CONTROL_AREA", "STATE", "ENTITY_NAME",
                        "MANDATORY", "OBJECT_NAME", "FINDING", "DBA_ACTION",
                    ],
                    sort_by=["SEVERITY", "CONTROL_AREA", "ENTITY_NAME"],
                    ascending=[True, True, True],
                    raw_label="All Horizon and semantic rows",
                    height=420,
                )
                if st.button("Queue Horizon and Semantic Gaps", key="arch_horizon_queue"):
                    _queue_architecture_findings(
                        session,
                        df,
                        "Architecture Readiness - Horizon & Semantic Trust",
                        "ENTITY_NAME",
                        "Horizon & Semantic Trust",
                    )
                download_csv(df, "architecture_horizon_semantic_readiness.csv")

    elif futures_view == "Control Register":
        render_priority_dataframe(
            controls,
            title="Forward platform control register",
            priority_columns=[
                "CONTROL_AREA", "CONTROL_ID", "OWNER", "APPROVAL_GROUP",
                "PRIMARY_EVIDENCE", "RISK_IF_MISSING", "DBA_DECISION",
                "AUTOMATION_BOUNDARY",
            ],
            sort_by=["MATCH_PRIORITY", "CONTROL_AREA"],
            ascending=[False, True],
            raw_label="All forward platform controls",
            height=460,
        )
        with st.expander("Platform futures evidence ledger setup SQL", expanded=False):
            st.caption(
                "Creates the durable control register, evidence ledger, latest-evidence view, and coverage view. "
                "Run through Snowflake change control with the approved app owner role."
            )
            st.code(build_platform_futures_evidence_ddl(), language="sql")
        download_csv(controls, "architecture_forward_platform_controls.csv")


def render():
    session = get_session()
    company = get_active_company()
    environment = get_active_environment()
    objectives = _architecture_objectives_frame(company)
    st.session_state["arch_objectives_df"] = objectives
    st.session_state["arch_objectives_meta"] = _architecture_scope_meta(
        company,
        environment,
        "Architecture objectives",
    )
    st.session_state["arch_forward_controls"] = build_forward_platform_control_register()
    st.session_state["arch_forward_controls_meta"] = _architecture_scope_meta(
        company,
        environment,
        "Forward platform controls",
    )
    st.session_state["arch_source_health"] = _architecture_source_health_rows(st.session_state, company, environment)

    st.header("Snowflake Architecture Readiness")
    st.caption("Forward-looking Snowflake architecture checks for isolation, clustering, cache behavior, and DR readiness.")
    render_operator_briefing(
        [
            ("First move", "Find architecture risks that repeat across sections."),
            ("Evidence", "Use ACCOUNT_USAGE and SHOW metadata only after explicit load."),
            ("Decision", "Classify as isolate, cluster, tune cache, fix DR, or leave alone."),
            ("Guardrail", "No automatic DDL; queue findings only after review."),
        ],
        columns=4,
    )
    st.caption(
        " | ".join([
            metric_confidence_label("delayed"),
            metric_confidence_label("manual"),
            freshness_note("ACCOUNT_USAGE"),
            f"Company {company}",
            f"Environment {environment}",
        ])
    )

    active_pane = st.radio(
        "Architecture readiness view",
        ARCHITECTURE_READINESS_PANES,
        horizontal=True,
        label_visibility="collapsed",
        key="architecture_readiness_pane",
    )

    if active_pane == "Workload Isolation":
        st.subheader("Workload Isolation Matrix")
        c1, c2 = st.columns(2)
        with c1:
            days = st.slider("Lookback days", 1, 90, 30, key="arch_iso_days")
        with c2:
            row_limit = st.slider("Max rows", 50, 1000, 300, step=50, key="arch_iso_limit")
        if st.button("Load Isolation Matrix", key="arch_iso_load"):
            with st.spinner("Loading database-to-warehouse isolation evidence..."):
                try:
                    st.session_state["arch_iso_df"] = _load_workload_isolation(session, days, row_limit)
                    st.session_state["arch_iso_meta"] = _architecture_scope_meta(
                        company,
                        environment,
                        "Workload isolation",
                        days=days,
                        row_limit=row_limit,
                    )
                except Exception as exc:
                    st.warning(f"Isolation matrix unavailable: {format_snowflake_error(exc)}")
        df = st.session_state.get("arch_iso_df")
        if df is not None:
            _render_loaded_metrics(df, "workload isolation")
            if not df.empty:
                render_priority_dataframe(
                    df,
                    title="Isolation decisions to review first",
                    priority_columns=[
                        "SEVERITY", "ISOLATION_DECISION", "DATABASE_NAME", "WAREHOUSE_NAME",
                        "WAREHOUSE_DATABASES", "DATABASE_WAREHOUSES", "QUERY_COUNT",
                        "QUEUED_SEC", "REMOTE_SPILL_GB", "FAILED_QUERIES",
                        "SERVICE_TIER", "OWNER", "QUEUE_READINESS", "APPROVAL_REQUIRED",
                        "RPO_MINUTES", "RTO_MINUTES", "DBA_ACTION",
                    ],
                    sort_by=["SEVERITY", "QUEUED_SEC", "REMOTE_SPILL_GB", "QUERY_COUNT"],
                    ascending=[True, False, False, False],
                    raw_label="All isolation rows",
                    height=420,
                )
                if st.button("Queue Isolation Findings", key="arch_iso_queue"):
                    _queue_architecture_findings(session, df, "Architecture Readiness - Isolation", "DATABASE_NAME", "Workload Isolation")
                download_csv(df, "architecture_workload_isolation.csv")

    elif active_pane == "Clustering Strategy":
        st.subheader("Clustering Strategy Advisor")
        c1, c2 = st.columns(2)
        with c1:
            min_gb = st.slider("Minimum table GB", 1.0, 500.0, 25.0, step=1.0, key="arch_cluster_min_gb")
        with c2:
            row_limit = st.slider("Max tables", 25, 500, 150, step=25, key="arch_cluster_limit")
        st.caption("This ranks candidates only. Run clustering-depth proof SQL for one selected table before changing keys.")
        if st.button("Load Clustering Candidates", key="arch_cluster_load"):
            with st.spinner("Loading table clustering candidates..."):
                try:
                    st.session_state["arch_cluster_df"] = _load_clustering_strategy(session, min_gb, row_limit)
                    st.session_state["arch_cluster_meta"] = _architecture_scope_meta(
                        company,
                        environment,
                        "Clustering strategy",
                        row_limit=row_limit,
                    )
                except Exception as exc:
                    st.warning(f"Clustering strategy unavailable: {format_snowflake_error(exc)}")
        df = st.session_state.get("arch_cluster_df")
        if df is not None:
            _render_loaded_metrics(df, "clustering")
            if not df.empty:
                render_priority_dataframe(
                    df,
                    title="Clustering candidates to validate first",
                    priority_columns=[
                        "SEVERITY", "CLUSTERING_DECISION", "TABLE_CATALOG", "TABLE_SCHEMA",
                        "TABLE_NAME", "TABLE_GB", "ROW_COUNT", "CLUSTERING_KEY",
                        "AUTO_CLUSTERING_ON", "SERVICE_TIER", "OWNER", "QUEUE_READINESS",
                        "APPROVAL_REQUIRED", "CLUSTERING_POLICY", "DBA_ACTION",
                    ],
                    sort_by=["SEVERITY", "TABLE_GB", "ROW_COUNT"],
                    ascending=[True, False, False],
                    raw_label="All clustering rows",
                    height=420,
                )
                selected = st.selectbox(
                    "Proof SQL table",
                    df.index.tolist(),
                    format_func=lambda idx: f"{df.loc[idx, 'TABLE_CATALOG']}.{df.loc[idx, 'TABLE_SCHEMA']}.{df.loc[idx, 'TABLE_NAME']}",
                    key="arch_cluster_selected",
                )
                st.code(str(df.loc[selected, "PROOF_SQL"]), language="sql")
                if st.button("Queue Clustering Findings", key="arch_cluster_queue"):
                    queue_df = df.copy()
                    queue_df["ENTITY"] = queue_df.apply(_table_fqn, axis=1)
                    _queue_architecture_findings(session, queue_df, "Architecture Readiness - Clustering", "ENTITY", "Clustering Strategy")
                download_csv(df, "architecture_clustering_strategy.csv")

    elif active_pane == "Cache Optimization":
        st.subheader("Cache Optimization Advisor")
        c1, c2 = st.columns(2)
        with c1:
            days = st.slider("Lookback days", 1, 90, 30, key="arch_cache_days")
        with c2:
            row_limit = st.slider("Max rows", 50, 1000, 300, step=50, key="arch_cache_limit")
        if st.button("Load Cache Evidence", key="arch_cache_load"):
            with st.spinner("Loading warehouse cache evidence..."):
                try:
                    st.session_state["arch_cache_df"] = _load_cache_optimization(session, days, row_limit)
                    st.session_state["arch_cache_meta"] = _architecture_scope_meta(
                        company,
                        environment,
                        "Cache optimization",
                        days=days,
                        row_limit=row_limit,
                    )
                except Exception as exc:
                    st.warning(f"Cache evidence unavailable: {format_snowflake_error(exc)}")
        df = st.session_state.get("arch_cache_df")
        if df is not None:
            _render_loaded_metrics(df, "cache")
            if not df.empty:
                render_priority_dataframe(
                    df,
                    title="Cache decisions to review first",
                    priority_columns=[
                        "SEVERITY", "CACHE_DECISION", "WAREHOUSE_NAME", "TOP_DATABASE",
                        "QUERY_COUNT", "QUERY_FAMILIES", "REPEATED_QUERY_RATIO",
                        "GB_SCANNED", "WAREHOUSE_CACHE_PCT", "AUTO_SUSPEND",
                        "WORKLOAD_CLASS", "OWNER", "QUEUE_READINESS", "CACHE_POLICY", "DBA_ACTION",
                    ],
                    sort_by=["SEVERITY", "GB_SCANNED", "QUERY_COUNT"],
                    ascending=[True, False, False],
                    raw_label="All cache rows",
                    height=420,
                )
                if st.button("Queue Cache Findings", key="arch_cache_queue"):
                    _queue_architecture_findings(session, df, "Architecture Readiness - Cache", "WAREHOUSE_NAME", "Cache Optimization")
                download_csv(df, "architecture_cache_optimization.csv")

    elif active_pane == "Objectives & Owners":
        st.subheader("Architecture Objective Register")
        st.caption("Manual DBA control objectives for database families, execution warehouses, workload classes, and RPO/RTO targets.")
        if objectives.empty:
            st.warning("No architecture objectives are configured for the active company.")
        else:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Objectives", f"{len(objectives):,}")
            c2.metric("Tier 0", f"{int((objectives['SERVICE_TIER'] == 'Tier 0').sum()):,}")
            c3.metric("Databases", f"{int((objectives['ENTITY_TYPE'] == 'DATABASE').sum()):,}")
            c4.metric("Warehouses", f"{int((objectives['ENTITY_TYPE'] == 'WAREHOUSE').sum()):,}")
            render_priority_dataframe(
                objectives,
                title="Configured architecture objectives",
                priority_columns=[
                    "COMPANY", "ENTITY_TYPE", "ENTITY_PATTERN", "WORKLOAD_CLASS",
                    "SERVICE_TIER", "EXPECTED_ENVIRONMENT", "RPO_MINUTES",
                    "RTO_MINUTES", "OWNER", "APPROVAL_GROUP", "ISOLATION_POLICY",
                ],
                sort_by=["COMPANY", "ENTITY_TYPE", "MATCH_PRIORITY"],
                ascending=[True, True, False],
                raw_label="All architecture objectives",
                height=420,
            )
            download_csv(objectives, "architecture_objectives.csv")
        source_health = _architecture_source_health_rows(st.session_state, company, environment)
        st.session_state["arch_source_health"] = source_health
        render_priority_dataframe(
            source_health,
            title="Architecture evidence source health",
            priority_columns=["STATE", "SURFACE", "SOURCE", "CONFIDENCE", "ROWS", "SCOPE", "NEXT_ACTION"],
            sort_by=["STATE_RANK", "SURFACE"],
            ascending=[True, True],
            raw_label="All architecture source-health rows",
            height=300,
        )

    elif active_pane == "DR Readiness":
        st.subheader("Disaster Recovery Readiness")
        days = st.slider("Replication usage lookback days", 1, 90, 30, key="arch_dr_days")
        st.caption(f"Replication lag warning threshold: {THRESHOLDS.get('replication_lag_warn_min', 120)} minutes.")
        if st.button("Load DR Readiness", key="arch_dr_load"):
            with st.spinner("Loading DR and replication metadata..."):
                try:
                    st.session_state["arch_dr_data"] = _load_dr_readiness(session, days)
                    readiness = st.session_state["arch_dr_data"].get("readiness", pd.DataFrame())
                    st.session_state["arch_dr_readiness"] = readiness
                    st.session_state["arch_dr_meta"] = _architecture_scope_meta(
                        company,
                        environment,
                        "DR readiness",
                        days=days,
                    )
                except Exception as exc:
                    st.warning(f"DR readiness unavailable: {format_snowflake_error(exc)}")
        data = st.session_state.get("arch_dr_data")
        if data:
            readiness = data.get("readiness", pd.DataFrame())
            _render_loaded_metrics(readiness, "DR")
            render_priority_dataframe(
                readiness,
                title="DR readiness gaps",
                priority_columns=[
                    "SEVERITY", "GROUP_TYPE", "GROUP_NAME", "FINDING",
                    "OBJECT_SCOPE", "SCHEDULE", "SERVICE_TIER", "OWNER",
                    "QUEUE_READINESS", "RPO_MINUTES", "RTO_MINUTES", "DBA_ACTION",
                ],
                sort_by=["SEVERITY", "GROUP_TYPE", "GROUP_NAME"],
                ascending=[True, True, True],
                raw_label="All DR readiness rows",
                height=360,
            )
            if st.button("Queue DR Findings", key="arch_dr_queue"):
                _queue_architecture_findings(session, readiness, "Architecture Readiness - DR", "GROUP_NAME", "Disaster Recovery")
            usage = data.get("usage", pd.DataFrame())
            if usage is not None and not usage.empty:
                st.subheader("Replication Usage History")
                render_priority_dataframe(
                    usage,
                    title="Recent replication phases",
                    priority_columns=[
                        "REPLICATION_GROUP_NAME", "PHASE_NAME", "START_TIME",
                        "END_TIME", "PHASE_MINUTES", "CREDITS_USED", "GB_TRANSFERRED", "ERROR",
                    ],
                    sort_by=["START_TIME"],
                    ascending=False,
                    raw_label="All replication usage rows",
                    height=300,
                )
                download_csv(usage, "architecture_replication_usage.csv")
            download_csv(readiness, "architecture_dr_readiness.csv")

    elif active_pane == "AI & Platform Futures":
        _render_platform_futures(session, company, environment)

    elif active_pane == "Forward Watchlist":
        _render_forward_watchlist()
