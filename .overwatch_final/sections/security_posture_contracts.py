# sections/security_posture_contracts.py - Security Monitoring workflow contracts
from __future__ import annotations


SECURITY_OVERVIEW_WORKFLOW = "Security Overview"
FAILED_LOGINS_WORKFLOW = "Failed Logins"
RISKY_GRANTS_WORKFLOW = "Risky Grants"
PRIVILEGE_SPRAWL_WORKFLOW = "Privilege Sprawl"
ACCESS_CHANGES_WORKFLOW = "Access Changes"
DATA_SHARING_EXPOSURE_WORKFLOW = "Data Sharing Exposure"
SECURITY_ALERTS_WORKFLOW = "Security Alerts"
SECURITY_ADMIN_ADVANCED_WORKFLOW = "Security Admin / Advanced"

SECURITY_POSTURE_VIEWS = (
    SECURITY_OVERVIEW_WORKFLOW,
    FAILED_LOGINS_WORKFLOW,
    RISKY_GRANTS_WORKFLOW,
    PRIVILEGE_SPRAWL_WORKFLOW,
    ACCESS_CHANGES_WORKFLOW,
    DATA_SHARING_EXPOSURE_WORKFLOW,
    SECURITY_ALERTS_WORKFLOW,
    SECURITY_ADMIN_ADVANCED_WORKFLOW,
)

SECURITY_POSTURE_VIEW_DETAILS = {
    SECURITY_OVERVIEW_WORKFLOW: "Failed logins, risky grants, privilege changes, sharing exposure, and top actions.",
    FAILED_LOGINS_WORKFLOW: "Login failures, MFA gaps, user activity, source IPs, and client programs.",
    RISKY_GRANTS_WORKFLOW: "User grants, elevated roles, ownership grants, and grant-option exposure.",
    PRIVILEGE_SPRAWL_WORKFLOW: "Admin role spread, elevated privilege growth, blockers, and review routes.",
    ACCESS_CHANGES_WORKFLOW: "Security-sensitive grants, roles, policies, integrations, and access drift.",
    DATA_SHARING_EXPOSURE_WORKFLOW: "Shares, imported databases, exposed datasets, consumers, and ownership.",
    SECURITY_ALERTS_WORKFLOW: "Loaded security incidents with owner, impact, and recommended action.",
    SECURITY_ADMIN_ADVANCED_WORKFLOW: "Source freshness, readiness, raw evidence, validation, and review-only plans.",
}

SECURITY_VIEW_ALIASES = {
    "Security Posture": SECURITY_OVERVIEW_WORKFLOW,
    "Security & Access": RISKY_GRANTS_WORKFLOW,
    "Access posture": SECURITY_OVERVIEW_WORKFLOW,
    "Access Posture": SECURITY_OVERVIEW_WORKFLOW,
    "Login Audit": FAILED_LOGINS_WORKFLOW,
    "Login Posture": FAILED_LOGINS_WORKFLOW,
    "Roles & Grants": RISKY_GRANTS_WORKFLOW,
    "Privilege sprawl": PRIVILEGE_SPRAWL_WORKFLOW,
    "Data Sharing": DATA_SHARING_EXPOSURE_WORKFLOW,
    "Data sharing exposure": DATA_SHARING_EXPOSURE_WORKFLOW,
    "Data Health": SECURITY_ADMIN_ADVANCED_WORKFLOW,
    "Security Summary": SECURITY_ALERTS_WORKFLOW,
    "Object and access changes": ACCESS_CHANGES_WORKFLOW,
    "Advanced Security Diagnostics": SECURITY_ADMIN_ADVANCED_WORKFLOW,
    "Security Admin": SECURITY_ADMIN_ADVANCED_WORKFLOW,
    "Advanced Security": SECURITY_ADMIN_ADVANCED_WORKFLOW,
    "Raw Grants": SECURITY_ADMIN_ADVANCED_WORKFLOW,
    "Role Readiness": SECURITY_ADMIN_ADVANCED_WORKFLOW,
}

WORKFLOWS = SECURITY_POSTURE_VIEWS

WORKFLOW_DETAILS = {
    SECURITY_OVERVIEW_WORKFLOW: "Fast security triage across identity, grants, access changes, sharing, and alerts.",
    FAILED_LOGINS_WORKFLOW: "Login failures, MFA gaps, user activity, source IPs, and client programs.",
    RISKY_GRANTS_WORKFLOW: "User grants, elevated roles, ownership grants, and grant-option exposure.",
    PRIVILEGE_SPRAWL_WORKFLOW: "Admin roles, ownership grants, grant-option exposure, and telemetry gaps.",
    ACCESS_CHANGES_WORKFLOW: "Recent grants, revokes, role memberships, object privileges, and who changed them.",
    DATA_SHARING_EXPOSURE_WORKFLOW: "Shares, imported databases, exposed datasets, and route follow-up.",
    SECURITY_ALERTS_WORKFLOW: "Security incidents from Alert Center with owners, impact, and investigation routes.",
    SECURITY_ADMIN_ADVANCED_WORKFLOW: "Raw evidence, validation, readiness, diagnostics, and review-gated plans.",
}

SECURITY_BRIEF_WORKFLOWS = (
    {
        "WORKFLOW": SECURITY_OVERVIEW_WORKFLOW,
        "BUTTON_LABEL": "Open Overview",
        "DBA_MOVE": "Start with failed logins, risky grants, access changes, sharing exposure, and top actions.",
        "WHEN": "Morning security review or quick triage.",
    },
    {
        "WORKFLOW": FAILED_LOGINS_WORKFLOW,
        "BUTTON_LABEL": "Open Logins",
        "DBA_MOVE": "Start with failed logins, MFA gaps, and user-level access signals.",
        "WHEN": "Morning triage, identity incidents, or audit prep.",
    },
    {
        "WORKFLOW": RISKY_GRANTS_WORKFLOW,
        "BUTTON_LABEL": "Open Grants",
        "DBA_MOVE": "Review admin roles, ownership, grant option, and review blockers.",
        "WHEN": "Role cleanup, least-privilege review, or elevated-access questions.",
    },
    {
        "WORKFLOW": PRIVILEGE_SPRAWL_WORKFLOW,
        "BUTTON_LABEL": "Open Sprawl",
        "DBA_MOVE": "Find dormant high-privilege users, orphaned roles, and accumulated access.",
        "WHEN": "Quarterly access cleanup or broad privilege growth review.",
    },
    {
        "WORKFLOW": ACCESS_CHANGES_WORKFLOW,
        "BUTTON_LABEL": "Open Changes",
        "DBA_MOVE": "Review recent grants, revokes, role membership, and object privilege changes.",
        "WHEN": "Something changed, access broke, or a user suddenly gained elevated rights.",
    },
    {
        "WORKFLOW": DATA_SHARING_EXPOSURE_WORKFLOW,
        "BUTTON_LABEL": "Open Sharing",
        "DBA_MOVE": "Validate shared databases, imported data, consumers, and ownership.",
        "WHEN": "External exposure, vendor access, or data-sharing audit review.",
    },
    {
        "WORKFLOW": SECURITY_ALERTS_WORKFLOW,
        "BUTTON_LABEL": "Open Alerts",
        "DBA_MOVE": "Triage security alerts with owner, impact, and recommended action.",
        "WHEN": "Alert Center routes a security incident or repeated signal.",
    },
    {
        "WORKFLOW": SECURITY_ADMIN_ADVANCED_WORKFLOW,
        "BUTTON_LABEL": "Open Advanced",
        "DBA_MOVE": "Load raw evidence, readiness, validation, and review-gated action plans.",
        "WHEN": "Audit support, admin validation, or deep proofing only.",
    },
)

WORKFLOW_MODULES = {
    FAILED_LOGINS_WORKFLOW: "sections.security_access",
    RISKY_GRANTS_WORKFLOW: "sections.security_access",
    DATA_SHARING_EXPOSURE_WORKFLOW: "sections.data_sharing",
}

__all__ = [
    "SECURITY_OVERVIEW_WORKFLOW",
    "FAILED_LOGINS_WORKFLOW",
    "RISKY_GRANTS_WORKFLOW",
    "PRIVILEGE_SPRAWL_WORKFLOW",
    "ACCESS_CHANGES_WORKFLOW",
    "DATA_SHARING_EXPOSURE_WORKFLOW",
    "SECURITY_ALERTS_WORKFLOW",
    "SECURITY_ADMIN_ADVANCED_WORKFLOW",
    "SECURITY_POSTURE_VIEWS",
    "SECURITY_POSTURE_VIEW_DETAILS",
    "SECURITY_VIEW_ALIASES",
    "WORKFLOWS",
    "WORKFLOW_DETAILS",
    "SECURITY_BRIEF_WORKFLOWS",
    "WORKFLOW_MODULES",
]
