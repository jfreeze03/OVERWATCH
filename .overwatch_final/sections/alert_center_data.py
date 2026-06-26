"""Alert Center bounded source loading helpers."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from sections.alert_center_contracts import ALERT_CENTER_DEFAULT_VIEW, ALERT_CENTER_SOURCES_BY_PANE
from sections.decision_workspace_target_filters import get_decision_evidence_target
from utils import format_snowflake_error
from utils.action_queue import load_action_queue
from utils.alert_catalog import load_alert_rule_catalog
from utils.alert_delivery import load_alert_delivery_log
from utils.alert_native_catalog import (
    load_alert_native_object_registry,
    load_alert_remediation_dry_runs,
    load_alert_remediation_policy,
)
from utils.alert_triage import build_dashboard_issue_rows, load_alert_history


def _load_center_data(
    session,
    company: str,
    environment: str,
    days: int,
    limit: int,
    sources: set[str] | None = None,
) -> dict:
    sources = set(sources or ALERT_CENTER_SOURCES_BY_PANE[ALERT_CENTER_DEFAULT_VIEW])
    data: dict[str, object] = {
        "alerts": pd.DataFrame(),
        "action_queue": pd.DataFrame(),
        "issues": pd.DataFrame(),
        "delivery_log": pd.DataFrame(),
        "rules": pd.DataFrame(),
        "native_registry": pd.DataFrame(),
        "remediation_policy": pd.DataFrame(),
        "remediation_dry_run": pd.DataFrame(),
        "alerts_error": "",
        "queue_error": "",
        "delivery_error": "",
        "rule_error": "",
        "native_registry_error": "",
        "remediation_policy_error": "",
        "remediation_dry_run_error": "",
        "loaded_at": datetime.now().isoformat(timespec="seconds"),
        "_loaded_sources": sorted(sources),
    }
    if "alerts" in sources:
        try:
            data["alerts"] = load_alert_history(
                session,
                company=company,
                environment=environment,
                days=days,
                limit=limit,
                section="Alert Center",
                target=get_decision_evidence_target("Alert Center"),
            )
        except Exception as exc:
            data["alerts_error"] = format_snowflake_error(exc)
    if "action_queue" in sources:
        try:
            data["action_queue"] = load_action_queue(session, limit=max(200, limit))
        except Exception as exc:
            data["queue_error"] = format_snowflake_error(exc)
    if "delivery_log" in sources:
        try:
            data["delivery_log"] = load_alert_delivery_log(days=max(days, 14), limit=100, section="Alert Center")
        except Exception as exc:
            data["delivery_error"] = format_snowflake_error(exc)
    if "rules" in sources:
        try:
            data["rules"] = load_alert_rule_catalog(section="Alert Center")
        except Exception as exc:
            data["rule_error"] = format_snowflake_error(exc)
    if "native_registry" in sources:
        try:
            data["native_registry"] = load_alert_native_object_registry(section="Alert Center")
        except Exception as exc:
            data["native_registry_error"] = format_snowflake_error(exc)
    if "remediation_policy" in sources:
        try:
            data["remediation_policy"] = load_alert_remediation_policy(section="Alert Center")
        except Exception as exc:
            data["remediation_policy_error"] = format_snowflake_error(exc)
    if "remediation_dry_run" in sources:
        try:
            data["remediation_dry_run"] = load_alert_remediation_dry_runs(
                days=max(days, 14),
                limit=limit,
                section="Alert Center",
            )
        except Exception as exc:
            data["remediation_dry_run_error"] = format_snowflake_error(exc)
    data["issues"] = build_dashboard_issue_rows(
        alerts=data["alerts"] if isinstance(data["alerts"], pd.DataFrame) else pd.DataFrame(),
        queue=data["action_queue"] if isinstance(data["action_queue"], pd.DataFrame) else pd.DataFrame(),
    )
    return data


__all__ = ["_load_center_data"]
