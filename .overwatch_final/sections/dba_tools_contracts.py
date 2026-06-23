# sections/dba_tools_contracts.py - Stable DBA Tools contracts.

SCHEMA_COMPARE_OBJECT_COVERAGE = (
    "TABLE",
    "VIEW",
    "MATERIALIZED VIEW",
    "DYNAMIC TABLE",
    "EXTERNAL TABLE",
    "STAGE",
    "FILE FORMAT",
    "PIPE",
    "STREAM",
    "TASK",
    "SEQUENCE",
    "FUNCTION",
    "PROCEDURE",
    "MASKING POLICY",
    "ROW ACCESS POLICY",
    "TAG",
)


DATA_COMPARE_EXECUTION_STAGES = (
    "metadata inventory",
    "row count",
    "explicit-column HASH_AGG",
    "bucket isolate",
    "forensic diff SQL",
)


ACCOUNT_PARAMETER_ADMIN_ROLES = {
    "ACCOUNTADMIN",
    "SNOW_ACCOUNTADMINS",
}
