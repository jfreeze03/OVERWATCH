"""Explicit visual fixtures for the OVERWATCH Decision Workspace.

These values mirror the dashboard mockup and are allowed only when fixture
mode is explicitly enabled. They are not production data and must not be used
as a fallback when Snowflake or mart summaries are unavailable.
"""

from __future__ import annotations

from datetime import datetime, timedelta


def _now_label() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _expiry_label(seconds: int = 300) -> str:
    return (datetime.now() + timedelta(seconds=max(int(seconds), 1))).isoformat(timespec="seconds")


def build_fixture_brief(contract, *, company: str, environment: str, window_days: int):
    """Return the deterministic mockup packet for visual/screenshot tests only."""
    from sections.section_command_brief import (
        SectionCommandAction,
        SectionCommandBrief,
        SectionCommandMetric,
        SectionCommandSignal,
    )

    def fixture_metric(
        key: str,
        label: str,
        value: str,
        *,
        numeric: float | None = None,
        tone: str = "neutral",
        detail: str = "",
        fmt: str = "integer",
        sort: int = 10,
    ) -> SectionCommandMetric:
        return SectionCommandMetric(
            key=key,
            label=label,
            value=value,
            numeric_value=numeric,
            metric_format=fmt,
            tone=tone,
            detail=detail,
            trend=detail,
            sort_order=sort,
            trend_points=(4, 5, 6, 7, 9, 11, 13),
            source_key="fixture",
            confidence="demo",
        )

    section = contract.section
    fixture_metrics = {
        "Executive Landing": (
            fixture_metric("total_spend", "Total Spend", "$42.8K", numeric=42800, fmt="currency", detail="vs prior 7d up 18.2%", tone="risk", sort=10),
            fixture_metric("critical_high_issues", "Critical / High Alerts", "7", numeric=7, fmt="integer", detail="vs prior 7d up 2", tone="risk", sort=20),
            fixture_metric("open_actions", "Open Actions", "23", numeric=23, fmt="integer", detail="vs prior 7d down 4", tone="improvement", sort=30),
            fixture_metric("cortex_spend", "Cortex AI Spend", "$6.4K", numeric=6400, fmt="currency", detail="31% of total spend", tone="cortex", sort=40),
            fixture_metric("failed_queries", "Failed Queries", "182", numeric=182, fmt="integer", detail="vs prior 7d down 34", tone="improvement", sort=50),
        ),
        "Cost & Contract": (
            fixture_metric("total_spend", "Spend", "$42.8K", numeric=42800, fmt="currency", sort=10),
            fixture_metric("spend_movement_pct", "Change", "+18.2%", numeric=18.2, fmt="percentage", tone="warning", sort=20),
            fixture_metric("cortex_spend", "Cortex AI Spend", "$6.4K", numeric=6400, fmt="currency", tone="cortex", sort=30),
            fixture_metric("forecast_run_rate", "Forecast", "$51.2K", numeric=51200, fmt="currency", sort=40),
        ),
        "Alert Center": (
            fixture_metric("active_alerts", "Active Alerts", "18", numeric=18, sort=10),
            fixture_metric("critical_high", "Critical / High", "5", numeric=5, tone="warning", sort=20),
            fixture_metric("cortex_predictive", "Cortex Predictive", "3", numeric=3, tone="cortex", sort=30),
            fixture_metric("notification_failures", "Delivery Failures", "2", numeric=2, sort=40),
        ),
        "DBA Control Room": (
            fixture_metric("failed_queries", "Failed Queries", "14", numeric=14, tone="warning", sort=10),
            fixture_metric("pipeline_failures", "Pipeline Failures", "3", numeric=3, tone="warning", sort=20),
            fixture_metric("queue_pressure", "Queue Pressure", "12m", numeric=720, fmt="duration", sort=30),
            fixture_metric("cost_24h", "Cost 24h", "$8.6K", numeric=8600, fmt="currency", sort=40),
        ),
        "Workload Operations": (
            fixture_metric("failed_queries", "Failed SQL", "14", numeric=14, tone="warning", sort=10),
            fixture_metric("pipeline_failures", "Pipeline Risk", "4", numeric=4, tone="warning", sort=20),
            fixture_metric("queue_blocked_pressure", "Queue / Blocked", "9m", numeric=540, fmt="duration", sort=30),
            fixture_metric("sla_risk", "SLA Risk", "3", numeric=3, sort=40),
        ),
        "Security Monitoring": (
            fixture_metric("failed_logins", "Failed Logins", "22", numeric=22, tone="warning", sort=10),
            fixture_metric(
                "credential_expirations",
                "Credential expirations",
                "1 expired - 2 due within 30d",
                numeric=3,
                tone="critical",
                detail="Next: Jane Doe - PAT - 5d",
                sort=20,
            ),
            fixture_metric("mfa_gaps", "MFA Gaps", "4", numeric=4, tone="warning", sort=30),
            fixture_metric("risky_grants", "Risky Grants", "6", numeric=6, tone="warning", sort=40),
        ),
    }
    metrics = fixture_metrics.get(section) or tuple(
        fixture_metric(metric.key, metric.label, "Demo", sort=index * 10)
        for index, metric in enumerate(contract.metric_contracts[:4], start=1)
    )
    if section == "Executive Landing":
        exceptions = (
            SectionCommandSignal(
                severity="High",
                signal="Cortex forecast exceeds threshold",
                entity="$8.2K projected exposure",
                detail="$8.2K projected exposure",
                route_section="Cost & Contract",
                route_workflow="Cortex AI",
                priority_score=98,
                impact_value=8200,
                impact_unit="USD",
                owner_route="AI Cost Route",
                sla_state="Due in 2h",
                route_key="cost_contract_cortex_ai",
                confidence="fixture",
            ),
            SectionCommandSignal(
                severity="High",
                signal="PROD_WH drove 54% of cost increase",
                entity="$6.7K increase vs prior 7d",
                detail="$6.7K increase vs prior 7d",
                route_section="Cost & Contract",
                route_workflow="Cost Explorer",
                priority_score=92,
                impact_value=6700,
                impact_unit="USD",
                owner_route="DBA / Cost",
                sla_state="On track",
                route_key="cost_contract_explorer_warehouse",
                confidence="fixture",
            ),
            SectionCommandSignal(
                severity="Watch",
                signal="$8.1K in savings remain unverified",
                entity="Verification overdue",
                detail="Verification overdue",
                route_section="Cost & Contract",
                route_workflow="Recommendations",
                priority_score=78,
                impact_value=8100,
                impact_unit="USD",
                owner_route="Cost Governance",
                sla_state="Overdue",
                route_key="cost_contract_budget",
                confidence="fixture",
            ),
        )
    elif section == "Security Monitoring":
        exceptions = (
            SectionCommandSignal(
                severity="Critical",
                signal="Credential expirations",
                entity="Jane Doe - PAT",
                detail="1 expired and 2 due within 30 days. Rotate or renew credential before expiration.",
                route_section="Security Monitoring",
                route_workflow="Security Overview",
                priority_score=96,
                owner_route="Jane Doe",
                sla_state="Due soon",
                route_key="security_credential_expirations",
                confidence="fixture",
                finding_key="CREDENTIAL_EXPIRING::JDOE::cred-001",
                dedupe_key="CREDENTIAL_EXPIRING::JDOE::cred-001",
                entity_type="USER_CREDENTIAL",
                entity_id="JDOE",
                evidence_id="credential_expiration::cred-001",
                owner_id="JDOE",
                owner_name="Jane Doe",
                due_ts="2026-07-05",
            ),
        )
    elif section == "Alert Center":
        exceptions = (
            SectionCommandSignal(
                severity="Critical",
                signal="Credential expirations",
                entity="Jane Doe - PAT",
                detail="Security credential rotation is due from the current command packet.",
                route_section="Security Monitoring",
                route_workflow="Security Overview",
                priority_score=96,
                owner_route="Jane Doe",
                sla_state="Due soon",
                route_key="security_credential_expirations",
                confidence="fixture",
                finding_key="CREDENTIAL_EXPIRING::JDOE::cred-001",
                dedupe_key="CREDENTIAL_EXPIRING::JDOE::cred-001",
                entity_type="USER_CREDENTIAL",
                entity_id="JDOE",
                evidence_id="credential_expiration::cred-001",
                owner_id="JDOE",
                owner_name="Jane Doe",
                due_ts="2026-07-05",
            ),
        )
    else:
        exceptions = (
            SectionCommandSignal(
                severity="High" if section in {"Cost & Contract", "Alert Center"} else "Watch",
                signal="Cortex forecast exceeds threshold" if section == "Cost & Contract" else contract.top_signal_label,
                entity="PROD_WH" if section == "Cost & Contract" else section,
                detail="Load evidence in Snowflake to validate the route.",
                route_section=contract.section,
                route_workflow=contract.default_view,
                priority_score=90,
                impact_value=8200 if section == "Cost & Contract" else None,
                impact_unit="USD" if section == "Cost & Contract" else "",
                owner_route="DBA / Cost",
                sla_state="Due in 2h",
                route_key=contract.fallback_route_keys[0] if contract.fallback_route_keys else "",
                confidence="fixture",
            ),
        )
    actions = tuple(
        SectionCommandAction(
            label=label,
            detail=detail,
            target_section=target_section or contract.section,
            target_workflow=target_workflow,
            cta=label,
            action_key=label.lower().replace(" ", "_"),
            route_key=contract.fallback_route_keys[index] if index < len(contract.fallback_route_keys) else "",
        )
        for index, (label, detail, target_section, target_workflow) in enumerate(contract.next_actions[:3])
    )
    if section == "Executive Landing":
        actions = (
            SectionCommandAction("Review Cortex AI", "Open Cortex spend and predictive alerts.", "Cost & Contract", "Cortex AI", cta="Review Cortex AI", action_key="review_cortex_ai", route_key="cost_contract_cortex_ai"),
            SectionCommandAction("Open Warehouse Drivers", "Open warehouse cost drivers.", "Cost & Contract", "Cost Explorer", cta="Open Warehouse Drivers", action_key="open_warehouse_drivers", route_key="cost_contract_explorer_warehouse"),
            SectionCommandAction("View Open Actions", "Open active alerts and action queue.", "Alert Center", "Active Alerts", cta="View Open Actions", action_key="view_open_actions", route_key="alert_center_active"),
        )
    elif section == "Security Monitoring":
        actions = (
            SectionCommandAction(
                "Review Credential Expirations",
                "Open credential expiration evidence target.",
                "Security Monitoring",
                "Security Overview",
                cta="Review Credential Expirations",
                action_key="review_credential_expirations",
                route_key="security_credential_expirations",
            ),
        ) + actions[:2]
    elif section == "Alert Center":
        actions = (
            SectionCommandAction(
                "Review Credential Expirations",
                "Route to Security Monitoring with the credential evidence target.",
                "Security Monitoring",
                "Security Overview",
                cta="Review Credential Expirations",
                action_key="review_credential_expirations",
                route_key="security_credential_expirations",
            ),
        ) + actions[:2]
    loaded_at = _now_label()
    return SectionCommandBrief(
        section=section,
        company=str(company),
        environment=str(environment),
        window_label=f"{int(window_days)} days",
        state="At Risk" if section in {"Cost & Contract", "Executive Landing"} else "Watch",
        headline=(
            "Spend is 18.2% above the prior 7 days."
            if section == "Executive Landing"
            else (
                "Spend is 18.2% above the prior period."
                if section == "Cost & Contract"
                else f"{section} decision brief is populated from fixture data."
            )
        ),
        summary=(
            "Cortex AI represents 31% of the increase."
            if section == "Executive Landing"
            else (
                "Cortex AI accounts for 31% of the increase, and PROD_WH is the largest infrastructure driver."
                if section == "Cost & Contract"
                else "Use this fixture packet for local visual review; Snowflake-backed evidence remains explicit."
            )
        ),
        source="Fixture data",
        freshness_label="Updated 8m ago | Fixture data",
        loaded_at=loaded_at,
        metrics=tuple(metrics),
        top_signal=exceptions[0],
        exceptions=exceptions,
        next_actions=actions,
        detail_cta=contract.detail_cta,
        detail_available=True,
        requested_company=str(company),
        requested_environment=str(environment),
        requested_window_days=int(window_days),
        resolved_company=str(company),
        resolved_environment=str(environment),
        resolved_window_days=int(window_days),
        source_objects="Fixture data",
        source_snapshot_ts=loaded_at,
        freshness_minutes=8,
        target_freshness_minutes=int(contract.target_freshness_minutes),
        stale=False,
        confidence="fixture",
        required_source_count=3,
        available_source_count=3,
        missing_source_count=0,
        source_coverage_pct=100,
        data_availability_state="Fixture data",
        cache_expires_at=_expiry_label(),
        app_query_loaded_at=loaded_at,
        command_brief_query_count=0,
        command_brief_fallback_used=False,
        raw_payload={"workspace_mode": "READY", "fixture_mode": True, "source_mode": "fixture"},
    )


__all__ = ["build_fixture_brief"]
