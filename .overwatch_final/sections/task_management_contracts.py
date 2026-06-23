# sections/task_management_contracts.py - Task Management workflow contracts

TASK_CONTROL_VIEWS = (
    "Job Status Brief",
    "Failure Console",
    "SLA & Cost Drift",
    "Task History",
    "ETL Audit",
    "Control Center",
    "Execute Task",
)
TASK_CONTROL_DETAILS = {
    "Job Status Brief": "Live Snowflake task handoff, task job status, performance indicators, and errors.",
    "Failure Console": "Failure patterns, query links, runbooks, and action queue handoff.",
    "SLA & Cost Drift": "Release-sensitive task duration and estimated credit regression review.",
    "Task History": "Run history, active task count, and raw task inventory.",
    "ETL Audit": "Custom ETL audit table setup and recent pipeline runs.",
    "Control Center": "Guarded suspend, resume, retry, execute, and cancel workflows.",
    "Execute Task": "Focused on-demand task execution with pre-flight checks.",
}
TASK_FAILURE_STATES = {"FAILED", "FAILED_WITH_ERROR"}
TASK_SUCCESS_STATES = {"SUCCEEDED", "SUCCESS", "COMPLETED"}
TASK_RUNNING_STATES = {"EXECUTING", "RUNNING"}
TASK_RECOVERY_SLA_HOURS = 4

__all__ = ['TASK_CONTROL_VIEWS', 'TASK_CONTROL_DETAILS', 'TASK_FAILURE_STATES', 'TASK_SUCCESS_STATES', 'TASK_RUNNING_STATES', 'TASK_RECOVERY_SLA_HOURS']
