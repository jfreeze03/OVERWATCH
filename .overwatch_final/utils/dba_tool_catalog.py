"""Static DBA tool catalog and warehouse setting metadata."""

WH_PARAM_HELP = {
    "WAREHOUSE_SIZE": "Credit rate: X-Small=1, Small=2, Medium=4, Large=8, X-Large=16, 2X-Large=32...",
    "AUTO_SUSPEND": "Seconds of inactivity before the warehouse suspends. 0 = never. Recommended: 60-300.",
    "AUTO_RESUME": "Automatically resume when a query is submitted. Should almost always be TRUE.",
    "STATEMENT_TIMEOUT_IN_SECONDS": "Maximum seconds a single query can run before being cancelled. 0 = no limit. Recommended: 3600.",
    "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS": "Max seconds a query waits in the queue. 0 = no limit. Recommended: 600.",
    "MAX_CONCURRENCY_LEVEL": "Max concurrent SQL statements per cluster. Default: 8. Range: 1-10.",
    "MAX_CLUSTER_COUNT": "Multi-cluster: max number of clusters. 1 = single cluster. Requires Enterprise.",
    "MIN_CLUSTER_COUNT": "Multi-cluster: min clusters always running. Setting >1 incurs constant credit cost.",
    "SCALING_POLICY": "STANDARD = scale up when queue builds. ECONOMY = scale only when full queue detected.",
    "ENABLE_QUERY_ACCELERATION": "Allow eligible queries to use the Query Acceleration Service. Requires Enterprise.",
    "QUERY_ACCELERATION_MAX_SCALE_FACTOR": "Max scale factor for QAS (0 = unlimited, 1-100). Each factor = 1 credit/hr.",
    "COMMENT": "Free-text label for this warehouse.",
}

SIZE_OPTS = ["X-Small", "Small", "Medium", "Large", "X-Large", "2X-Large", "3X-Large", "4X-Large", "5X-Large", "6X-Large"]

SIZE_SQL = {
    "X-Small": "XSMALL",
    "Small": "SMALL",
    "Medium": "MEDIUM",
    "Large": "LARGE",
    "X-Large": "XLARGE",
    "2X-Large": "XXLARGE",
    "3X-Large": "XXXLARGE",
    "4X-Large": "X4LARGE",
    "5X-Large": "X5LARGE",
    "6X-Large": "X6LARGE",
}

SCALE_OPTS = ["STANDARD", "ECONOMY"]

TASK_GRAPH_CONTROL_PANES = (
    "Running Task Queries",
    "Cancel Graph / Task",
    "Suspend / Resume",
    "DAG Inspector",
)

DBA_TOOL_GROUPS = {
    "Warehouse Ops": [
        "Query Kill List",
        "Warehouse Settings",
        "QAS Monitor",
        "Task Graph Control",
    ],
    "Data Movement": [
        "Data Loading",
        "Snowpipe Monitor",
        "Dynamic Tables",
        "Replication",
    ],
    "Governance": [
        "Network & Sessions",
        "Unused Objects",
        "Schema Compare",
        "Data Compare",
        "Recent Objects",
    ],
    "Cost & Setup": [
        "Mart Readiness",
        "Serverless Costs",
        "Cost Formula Audit",
        "Cortex AI Limits",
        "Usage Log",
        "Setup Status",
    ],
}

DBA_TOOL_FOCUS_HINTS = {
    "Governance": "Start with Governance for schema compare, recent objects, unused objects, and object drift.",
    "Data Movement": "Start with Data Movement for loads, Snowpipe, dynamic tables, and replication.",
    "Controlled Actions": "Start with Warehouse Ops for query/task/warehouse actions, then Cost & Setup for setup/audit evidence.",
}

DBA_TOOL_FOCUS_GROUPS = {
    "Governance": "Governance",
    "Data Movement": "Data Movement",
    "Controlled Actions": "Warehouse Ops",
    "Cost": "Cost & Setup",
}
