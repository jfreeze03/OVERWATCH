# OVERWATCH Mart Object Review

Static scan date: 2026-06-17

This review inventories deployable Snowflake objects in `snowflake/OVERWATCH_MART_SETUP.sql`
and cross-checks them against `.overwatch_final` app references. It is a static code scan,
not a live database dependency graph. Use `docs/MART_RESET_RUNBOOK.md` with
`snowflake/OVERWATCH_MART_DROP.sql` when a clean mart rebuild is needed.

## Counts

| Object type | Count |
| --- | ---: |
| Tables | 56 |
| Procedures | 8 |
| Tasks | 7 |
| Views | 2 |
| Functions | 1 |
| Total | 74 |

Objects with direct `.overwatch_final` references: 59.

Objects without direct `.overwatch_final` references: 15. Most are scheduled refresh
procedures/tasks or setup-support tables that are referenced by the setup SQL itself.

Objects without `.overwatch_final` or test references: 6. All six are refresh plumbing.

Latest static dependency pass:

- Deployable setup objects: 74.
- Drop coverage: every deployable table, view, procedure, function, and task has
  a matching `DROP ... IF EXISTS` in `snowflake/OVERWATCH_MART_DROP.sql`.
- Refresh procedure ownership is current: hourly/daily/Cortex procedures populate
  the retained facts, cost monitoring populates `FACT_COST_MONITORING_SIGNAL` and
  `FACT_COST_INCIDENT_TIMELINE`, and executive/control-room refresh procedures
  populate only their current summary marts.
- No additional safe drop was found without intentionally retiring an active app
  workflow, setup-support object, or refresh/bookkeeping object.
- The latest consolidation pass moved repeated-query, duplicate-query,
  right-sizing, storage-retention, clustering, and procedure summary reads into
  shared app loaders. This did not create new mart objects; it increased reuse
  of existing query detail and procedure facts.
- The latest cost cleanup also moved warehouse credit anomaly detection into a
  shared mart-first loader. `FACT_WAREHOUSE_HOURLY` remains the preferred source
  for completed-day anomaly scans, with `WAREHOUSE_METERING_HISTORY` only as the
  explicit fallback path.
- The latest Cost & Contract pass moved cockpit movement and run-rate/YOY SQL
  into shared metering builders used by both mart and live fallback paths. This
  did not add or remove mart objects, but it reduced duplicated app query logic.
- The latest service-cost pass moved Cost & Contract official service lens and
  service trend reads into shared `METERING_HISTORY` loaders. This did not add
  or remove mart objects and keeps account service-cost scans behind explicit
  cost refresh surfaces.
- The latest Service Health pass moved hourly query, warehouse, login, task,
  and load health counters into shared app loaders. This did not add or remove
  mart objects; it reuses the current query, warehouse, login, and task marts
  where grain matches, with bounded ACCOUNT_USAGE fallback.
- The latest Security Monitoring pass moved summary/exception SQL, privileged
  grant review SQL, and MFA compatibility helpers into shared app utilities.
  This did not add or remove mart objects; it reuses `FACT_LOGIN_DAILY` and
  `FACT_GRANT_DAILY` where available with bounded ACCOUNT_USAGE fallback.
- The latest Warehouse Health pass moved efficiency, spill/memory, and workload
  heatmap support panels into shared app loaders. This did not add or remove
  mart objects; the heatmap still prefers `FACT_QUERY_HOURLY` and falls back to
  bounded `QUERY_HISTORY` only from the explicit heatmap action.
- Latest static object disposition: 59 deployable objects are directly app-read
  or app-managed, 9 are test/setup contracts, and 6 are refresh/setup plumbing.
  See `docs/QUERY_INVENTORY.md` for the current query and object map.
- Latest mart/SP audit: refresh procedures do not create, insert, merge, or
  delete against retired automation, executive packet, monitoring-cost,
  external-control, owner-directory, or cost-savings verification objects.
  `snowflake/OVERWATCH_MART_DROP.sql` remains the mass-drop script for both
  current objects and old deployed copies.
- Latest secure-view compatibility audit: `snowflake/OVERWATCH_MART_SETUP.sql`
  contains no deployable Dynamic Tables or Secure Views. Refreshable facts stay
  as task/procedure-loaded transient tables so a secure view in an upstream
  dependency path does not break the mart.
- Latest validation hardening: `snowflake/OVERWATCH_MART_VALIDATION.sql` now
  reports dynamic-table and secure-view collisions in the deployed OVERWATCH
  schema. A clean rebuild should return `PASS` for both checks before app
  validation continues.
- Latest ALFA/Trexis scope hardening did not add mart objects. App surfaces now
  use role-aware user scope for user/login/grant telemetry, and Cost Center
  reconciliation compares Snowflake Admin account totals to OVERWATCH scoped
  warehouse/query totals without changing mart grain.
- Latest reset proof hardening: the validation script also checks the expected
  table/view/procedure/function counts and task graph state so mass rebuilds
  can be verified from Snowflake without manually recounting the setup file.
- Latest retired-object cleanup hardening: `snowflake/OVERWATCH_MART_DROP.sql`
  now has explicit drops for retired monitoring-cost, cost-savings verification,
  external-control, owner-directory, platform-futures, and static metadata
  objects that older deployments may still contain.

## Keep

These are directly used by app surfaces, validation, or core persisted DBA workflows.

| Object family | Why it stays |
| --- | --- |
| `MART_EXECUTIVE_OBSERVABILITY`, `MART_DBA_CONTROL_ROOM` | Fast first-paint telemetry for Executive Landing and DBA Control Room. |
| `FACT_COST_DAILY`, `FACT_CORTEX_DAILY`, `FACT_QUERY_HOURLY`, `FACT_QUERY_DETAIL_RECENT`, `FACT_WAREHOUSE_HOURLY` | Main cost, Cortex, workload, and warehouse health marts used by Cost & Contract, workload, query, and warehouse sections. |
| `FACT_TASK_RUN`, `FACT_TASK_CRITICAL_PATH`, `FACT_PROCEDURE_RUN`, `DIM_TASK_SNAPSHOT`, `DIM_PROCEDURE_SNAPSHOT`, `DIM_TABLE_SNAPSHOT` | Task/procedure health, task graph blast radius, stored procedure context, and workload reliability. |
| `FACT_COST_SOURCE_HEALTH_DAILY`, `FACT_COST_MONITORING_SIGNAL`, `FACT_COST_INCIDENT_TIMELINE` | Cost telemetry health, ranked cost movement signals, and cost incident timeline. Keep while cost advisor/RCA metrics settle. |
| `OVERWATCH_ACTION_QUEUE`, `OVERWATCH_ALERTS`, `OVERWATCH_ADMIN_ACTION_AUDIT`, alert rule/log tables | Alert Center, recommendations, action queue, admin audit, and delivery/remediation history. |
| `OVERWATCH_RECON_CONFIG`, `OVERWATCH_RECON_RUN`, `OVERWATCH_SCHEMA_DIFF_RESULT` | Schema/data compare persistence and generated DDL review. |
| `OVERWATCH_WAREHOUSE_SETTING_REVIEW`, `FACT_WAREHOUSE_OPERABILITY_DAILY` | Warehouse settings audit, safe setting review, and capacity telemetry. |
| `OVERWATCH_WORKLOAD_RECOVERY_AUDIT`, `OVERWATCH_WORKLOAD_RECOVERY_AUDIT_LATEST_V` | Task/procedure recovery status and latest recovery state. |
| `FACT_SECURITY_OPERABILITY_DAILY`, `FACT_ACCOUNT_HEALTH_OPERABILITY_DAILY`, `FACT_LOGIN_DAILY`, `FACT_GRANT_DAILY` | Security and account-health telemetry used by admin monitoring surfaces. |
| `FACT_STORAGE_DAILY`, `FACT_COPY_LOAD_DAILY`, `FACT_OBJECT_CHANGE`, `FACT_CHANGE_CONTROL_OPERABILITY_DAILY` | Storage, load, object-change, and operability facts. `FACT_STORAGE_DAILY` includes standard/stage, hybrid, archive cool, and archive cold storage classes for account-wide reconciliation. Keep while corresponding monitoring code/tests still reference them. |

## Keep As Refresh Plumbing

These do not have direct app reads, but they drive scheduled mart refresh or refresh
bookkeeping. Do not remove them unless their downstream facts are removed or replaced.

| Object | Current purpose |
| --- | --- |
| `SP_OVERWATCH_LOAD_HOURLY`, `SP_OVERWATCH_LOAD_DAILY`, `SP_OVERWATCH_LOAD_CORTEX` | Load hourly, daily, and Cortex facts consumed by app marts. |
| `SP_OVERWATCH_REFRESH_CONTROL_ROOM`, `SP_OVERWATCH_REFRESH_EXECUTIVE_OBSERVABILITY` | Refresh compact summary marts used by first-paint surfaces. |
| `SP_OVERWATCH_REFRESH_COST_MONITORING`, `OVERWATCH_COST_MONITORING_REFRESH` | Refresh cost monitoring signal and incident timeline facts. |
| `SP_OVERWATCH_PRUNE` | Retention cleanup for transient facts. |
| `OVERWATCH_LOAD_HOURLY`, `OVERWATCH_LOAD_DAILY`, `OVERWATCH_LOAD_CORTEX`, `OVERWATCH_REFRESH_CONTROL_ROOM`, `OVERWATCH_EXECUTIVE_OBSERVABILITY_REFRESH` | Scheduled wrappers around refresh procedures. |
| `OVERWATCH_LOAD_AUDIT` | Refresh bookkeeping written by setup procedures. It is not surfaced today, but remains useful for live refresh troubleshooting. |

## Mart Slimming Assessment

The current mart count still looks large, but most tables fall into active roles:

| Role | Keep rationale |
| --- | --- |
| Hourly/daily rollups | Reduce repeated ACCOUNT_USAGE scans for cost, warehouse, query, storage, Cortex, security, and executive summary surfaces. |
| Recent detail facts | Support drilldowns and advisor fallbacks without broad historical scans. |
| Snapshot dimensions | Preserve task, procedure, table, grant, and warehouse setting context that Snowflake history views do not expose cleanly in one place. |
| Workflow/audit tables | Keep action queue, alert delivery, recovery, setting-review, and admin audit state visible for DBA operations. |

No table is marked for immediate removal in this pass. The next safe slimming
step is to merge only after a pair of objects has the same grain, refresh cadence,
retention need, and no unique downstream display or audit purpose.

Do not use Dynamic Tables as the merge target for any object whose source path
can include secure views. Merge candidates must remain physical tables populated
by the scheduled refresh chain unless a live Snowflake proof confirms the source
dependency path is compatible.

## Procedure Output Map

The setup procedures now map to current facts only:

| Procedure | Current outputs |
| --- | --- |
| `SP_OVERWATCH_LOAD_HOURLY` | `FACT_WAREHOUSE_HOURLY`, `FACT_QUERY_HOURLY`, `FACT_QUERY_DETAIL_RECENT`, `FACT_OBJECT_CHANGE`, `FACT_TASK_RUN`, `FACT_TASK_CRITICAL_PATH`, `FACT_PROCEDURE_RUN` |
| `SP_OVERWATCH_LOAD_DAILY` | `FACT_COST_DAILY`, `FACT_COST_SOURCE_HEALTH_DAILY`, `FACT_LOGIN_DAILY`, `FACT_GRANT_DAILY`, `FACT_STORAGE_DAILY`, `FACT_COPY_LOAD_DAILY`, `DIM_COST_OWNER_TAG`, role-aware `FACT_CHARGEBACK_DAILY`, operability facts |
| `SP_OVERWATCH_LOAD_CORTEX` | `FACT_CORTEX_DAILY` |
| `SP_OVERWATCH_REFRESH_COST_MONITORING` | `FACT_COST_MONITORING_SIGNAL`, `FACT_COST_INCIDENT_TIMELINE` |
| `SP_OVERWATCH_REFRESH_CONTROL_ROOM` | `MART_DBA_CONTROL_ROOM` |
| `SP_OVERWATCH_REFRESH_EXECUTIVE_OBSERVABILITY` | `MART_EXECUTIVE_OBSERVABILITY` |
| `SP_OVERWATCH_PRUNE` | Retention cleanup for retained facts only |

Retired refresh objects stay only in the drop script so old deployed copies are
removed during a fresh rebuild. They are not setup outputs.

## Keep As Setup Support

These are not primary UI surfaces. Keep them only while their dependent facts,
tests, or setup logic still need them.

| Object | Current purpose |
| --- | --- |
| `OVERWATCH_SETTINGS`, `OVERWATCH_SCHEMA_MIGRATION`, `OVERWATCH_USAGE_LOG` | Settings, deployment/version state, and optional app usage bookkeeping. |
| `OVERWATCH_OWNER_TAG_NAMES`, `DIM_COST_OWNER_TAG` | Owner tag configuration and snapshot used in chargeback fact construction. Candidate to remove only if owner-tag chargeback is removed from scope. |
| `OVERWATCH_DBA_CHECKLIST_HISTORY`, `OVERWATCH_CHANGE_CONTROL_EVIDENCE` | Referenced by app code/tests today. Review separately if those remaining workflows are retired from the admin monitoring product. |

## Pruned Metadata Objects

These were already removed from the deployable setup because the app does not read them
and the same information is maintained in docs, Python config, or read-only validation SQL.

| Object | Replacement |
| --- | --- |
| `OVERWATCH_COMMAND_INTELLIGENCE_CAPABILITY` | Capability direction remains in docs and app code, not a static mart table. |
| `OVERWATCH_REFRESH_POLICY` | Refresh contract remains in `docs/REFRESH_ARCHITECTURE.md` and inline validation SQL. |
| `OVERWATCH_COMPANY_SCOPE` | Company/scope filtering remains in app config and Python scope helpers. |
| `OVERWATCH_COMPLIANCE_READINESS_V` | Security Monitoring reads native Snowflake telemetry directly or through relevant future facts. |

## Retire Or Merge Candidates

These are compatibility-debt targets, not immediate drop targets. They should not
be removed by table count alone.

| Object | Recommendation |
| --- | --- |
| `OVERWATCH_OWNER_TAG_NAMES`, `DIM_COST_OWNER_TAG` | Candidate only if owner-tag chargeback is intentionally retired. Otherwise keep as setup support. |
| `OVERWATCH_DBA_CHECKLIST_HISTORY`, `OVERWATCH_CHANGE_CONTROL_EVIDENCE` | Candidate only after confirming the remaining app/test references are intentionally out of scope. |

## Retired In Latest Review

| Object | Replacement |
| --- | --- |
| `FACT_MONITORING_COST_DAILY` | Removed from deployable setup. Its overlapping app/runtime cost view is covered by `FACT_COST_DAILY`, `FACT_COST_MONITORING_SIGNAL`, `FACT_COST_INCIDENT_TIMELINE`, and `MART_EXECUTIVE_OBSERVABILITY`. |
| `OVERWATCH_AUTOMATION_RUN`, `OVERWATCH_EXECUTIVE_PACKET`, `OVERWATCH_AUTOMATION_HEALTH_V` | Removed from deployable setup. Alert delivery remains in `OVERWATCH_ALERT_DELIVERY_LOG`; first-paint executive metrics remain in `MART_EXECUTIVE_OBSERVABILITY`; old deployed copies are covered by `snowflake/OVERWATCH_MART_DROP.sql`. |
| `SP_OVERWATCH_REFRESH_AUTOMATION`, `OVERWATCH_AUTOMATION_REFRESH` | Removed from deployable setup. The scheduled task chain now refreshes cost monitoring and then `SP_OVERWATCH_REFRESH_EXECUTIVE_OBSERVABILITY` directly. |
| Cost-savings verification, external-control, owner-directory, platform-futures, static metadata/control-policy objects | Removed from deployable setup and covered by `snowflake/OVERWATCH_MART_DROP.sql` retired cleanup so old lower-environment rebuilds do not preserve stale scope. |

## Current No-App-Reference List

These 15 objects do not have direct `.overwatch_final` references in the static scan:

| Object | Disposition |
| --- | --- |
| `DIM_COST_OWNER_TAG` | Setup support. |
| `OVERWATCH_DATABASE_ENVIRONMENT` | Shared setup function used by mart SQL. |
| `OVERWATCH_EXECUTIVE_OBSERVABILITY_REFRESH` | Refresh task. |
| `OVERWATCH_LOAD_AUDIT` | Refresh bookkeeping. |
| `OVERWATCH_LOAD_CORTEX` | Refresh task. |
| `OVERWATCH_LOAD_DAILY` | Refresh task. |
| `OVERWATCH_LOAD_HOURLY` | Refresh task. |
| `OVERWATCH_OWNER_TAG_NAMES` | Setup support. |
| `OVERWATCH_REFRESH_CONTROL_ROOM` | Refresh task. |
| `SP_OVERWATCH_LOAD_CORTEX` | Refresh procedure. |
| `SP_OVERWATCH_LOAD_DAILY` | Refresh procedure. |
| `SP_OVERWATCH_LOAD_HOURLY` | Refresh procedure. |
| `SP_OVERWATCH_PRUNE` | Retention procedure. |
| `SP_OVERWATCH_REFRESH_CONTROL_ROOM` | Refresh procedure. |
| `SP_OVERWATCH_REFRESH_EXECUTIVE_OBSERVABILITY` | Refresh procedure. |

## Next Pruning Rule

Do not prune by table count alone. For each candidate, confirm:

1. No app read path.
2. No refresh procedure output dependency.
3. No validation/test contract that still represents desired production behavior.
4. No required audit/history retention purpose.
5. A replacement exists, or the feature is intentionally out of product scope.

After retiring `FACT_MONITORING_COST_DAILY` and the old packet objects, the
remaining no-app/test-reference objects are refresh procedures,
refresh bookkeeping, or setup support. The latest scan found no additional safe
drops without first retiring active app workflows or doing a larger compatibility
rename/migration. Keep `OVERWATCH_USAGE_LOG`, owner-tag chargeback helpers, DBA
checklist history, and change-control history until those consuming surfaces are
intentionally reworked or retired.
