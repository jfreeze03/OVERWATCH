# sections/change_drift_contracts.py - Change Drift workflow contracts
import re

CHANGE_DRIFT_VIEWS = ("Change Brief", "Change Workflows")
CHANGE_DRIFT_VIEW_DETAILS = {
    "Change Brief": "Default cockpit: status strip, KPI row, and compact exception-first workflow grid.",
    "Change Workflows": "Open Snowflake object/access changes, stored procedure lineage, schema drift, data movement, or guarded DBA action telemetry.",
}
CHANGE_DRIFT_BRIEF_FIRST_VERSION = 2
WORKFLOWS = (
    "Object and access changes",
    "Schema and object drift",
    "Data movement and replication",
    "Stored procedure lineage",
    "Controlled DBA actions",
)
WORKFLOW_DETAILS = {
    "Object and access changes": "Who changed what, access movement, destructive object changes, and policy changes.",
    "Schema and object drift": "Schema compare, object inventory, unused objects, and Snowflake-native drift signals.",
    "Controlled DBA actions": "Guarded admin actions, DBA review, and operational controls.",
    "Data movement and replication": "Replication, dynamic tables, Snowpipe, data loading, and freshness risk.",
    "Stored procedure lineage": "Procedure execution context, child statements, downstream objects, and runtime/cost drift.",
}
CHANGE_BRIEF_WORKFLOWS = (
    {
        "WORKFLOW": "Object and access changes",
        "BUTTON_LABEL": "Open Object Changes",
        "DBA_MOVE": "Start with recent object changes, grants, ownership, policy, and actor telemetry.",
        "WHEN": "Unknown actor, manual object change, access movement",
    },
    {
        "WORKFLOW": "Schema and object drift",
        "BUTTON_LABEL": "Open Schema Drift",
        "DBA_MOVE": "Compare databases and schemas, then review orphaned or unmanaged objects.",
        "WHEN": "Schema compare, object inventory, unused assets",
    },
    {
        "WORKFLOW": "Data movement and replication",
        "BUTTON_LABEL": "Open Data Movement",
        "DBA_MOVE": "Review Snowpipe, dynamic tables, replication, and load freshness signals.",
        "WHEN": "Pipeline freshness, replication, load issues",
    },
    {
        "WORKFLOW": "Stored procedure lineage",
        "BUTTON_LABEL": "Open Procedure Lineage",
        "DBA_MOVE": "Trace stored procedure ownership, child statements, runtime drift, and downstream impact.",
        "WHEN": "Procedure change, runtime drift, ownership review",
    },
    {
        "WORKFLOW": "Controlled DBA actions",
        "BUTTON_LABEL": "Open DBA Actions",
        "DBA_MOVE": "Use guarded admin workflows with audit telemetry and review requirements.",
        "WHEN": "Reviewed changes, recovery, controlled fixes",
    },
)
WORKFLOW_MODULES = {
    "Object and access changes": "sections.object_change_monitor",
    "Stored procedure lineage": "sections.stored_proc_tracker",
    "Schema and object drift": "sections.dba_tools",
    "Data movement and replication": "sections.dba_tools",
    "Controlled DBA actions": "sections.dba_tools",
}
CHANGE_CONTROL_EVIDENCE_TABLE = "OVERWATCH_CHANGE_CONTROL_EVIDENCE"
CHANGE_CONTROL_OPERABILITY_FACT_TABLE = "FACT_CHANGE_CONTROL_OPERABILITY_DAILY"
CHANGE_SCOPE_FILTER_KEYS = (
    "global_warehouse",
    "global_user",
    "global_role",
    "global_database",
    "global_start_date",
    "global_end_date",
)
CHANGE_TICKET_PATTERN = re.compile(
    r"\b(?:CHG|CHANGE|INC|REQ|RFC|OWNER_APPROVAL)[-_]?\d+\b|\b[A-Z][A-Z0-9]+-\d+\b",
    re.IGNORECASE,
)

__all__ = ['CHANGE_DRIFT_VIEWS', 'CHANGE_DRIFT_VIEW_DETAILS', 'CHANGE_DRIFT_BRIEF_FIRST_VERSION', 'WORKFLOWS', 'WORKFLOW_DETAILS', 'CHANGE_BRIEF_WORKFLOWS', 'WORKFLOW_MODULES', 'CHANGE_CONTROL_EVIDENCE_TABLE', 'CHANGE_CONTROL_OPERABILITY_FACT_TABLE', 'CHANGE_SCOPE_FILTER_KEYS', 'CHANGE_TICKET_PATTERN']
