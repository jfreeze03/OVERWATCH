# OVERWATCH Company Scope Audit

Static audit date: 2026-06-17

OVERWATCH supports ALFA, Trexis, and ALL views. The company boundary is strongest
when Snowflake telemetry exposes a warehouse, database, user, or role. Trexis
classification uses the confirmed Trexis warehouse allowlist, Trexis database
families, `TRXS_%` user names, and active user grants to roles containing `TRXS`.

Do not present account-level service, storage-class, policy, integration, or
global security telemetry as company-exact unless a source view exposes a
defensible owner dimension.

## Section Audit

| Section | Exact company split | Directional / allocated | Account-wide only |
| --- | --- | --- | --- |
| Executive Landing | Query, warehouse, task, procedure, storage database/failsafe signals when backed by company-scoped facts | Composite health scores that mix scoped and account-level facts | Global service, admin, policy, and account-health totals |
| DBA Control Room | Query, warehouse, task, procedure, failed-query, and object-change facts with warehouse/database/user/role context | Composite priority and cost explanations that include allocated workload cost | Access hygiene, global control state, and account service pressure |
| Alert Center | Alerts raised from company-scoped facts or action rows carrying company | Global threshold incidents that reference shared services | Alert rules, delivery configuration, notification plumbing |
| Cost & Contract | Warehouse metering by configured warehouse ownership; database/failsafe storage; query workload by warehouse/database/user/role | Query-attributed chargeback, user/role/database allocation, warehouse advisor savings | Snowflake Admin/Cost Management totals, broad `METERING_HISTORY` service spend, stage/hybrid/archive storage classes |
| Workload Operations | Query history, task history, stored procedure inventory/calls, load failures with database/warehouse/user/role context | Procedure cost where child-query lineage or root query IDs are partial | Account refresh metadata and service-only workload telemetry |
| Security Monitoring | User, login, MFA, and grant posture through configured user patterns plus active `TRXS` role membership; object grants with database context | Composite security posture that mixes identity and object telemetry | Account policies, network policies, integrations, external shares, global admin posture |

## Implementation Rules

- Use `get_global_filter_clause()` for query facts whenever `role_name` is
  available so role scoping participates in ALFA/Trexis classification.
- Use `get_user_company_filter_clause()` for user-only sources such as
  `USERS`, `LOGIN_HISTORY`, `SESSIONS`, and `GRANTS_TO_USERS`.
- Cost and Cortex user views should prefer role-aware user scoping. Trexis users
  with active `%TRXS%` role grants belong in the Trexis company view even if a
  source table does not expose a Trexis warehouse or database.
- Alert events should populate `COMPANY` and `ENVIRONMENT` when the signal
  comes from company-labeled OVERWATCH facts. Native alert candidates should
  prefer `FACT_CORTEX_DAILY`, `FACT_WAREHOUSE_HOURLY`, `FACT_GRANT_DAILY`,
  `FACT_TASK_RUN`, and `FACT_QUERY_DETAIL_RECENT` before falling back to raw
  account usage.
- Run `snowflake/OVERWATCH_ALERT_OPERATIONS_REVIEW.sql` after mart refreshes or
  alert registry changes to review `ALERT_EVENTS`, cost/Cortex, warehouse,
  query, task, and grant fact company distribution before company-specific
  alert routing or threshold tuning.
- Keep `get_user_filter_clause()` centralized in `utils/company_filter.py` as
  the fallback primitive. App surfaces should call the role-aware helper.
- Label `METERING_HISTORY` service rows and account storage classes as
  account-wide unless a service-specific view exposes user, warehouse, database,
  or owner tags.
- Snowflake Admin/Cost Management reconciliation belongs in Cost Center
  reconciliation as an account-wide bridge, not as company-exact chargeback.

## Remaining Non-Splittable Signals

- Annual service projection and other broad `METERING_HISTORY` totals.
- Stage storage, hybrid table storage, archive cool storage, and archive cold
  storage from account-level storage views.
- Account-level security and integration objects without database/object/user
  ownership.
- Alert routing/configuration and global thresholds.
- Any service cost whose Snowflake source does not expose user, role, warehouse,
  database, or tag ownership.
- Snowflake Admin/Cost Management account totals. Use them for reconciliation,
  then explain which subset is company-scoped, allocated, or account-wide.
