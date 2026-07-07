# Person/Team Dispatch Removal Audit

Scope: active app code, active setup SQL, validation SQL, migration SQL, and tests after the hardening pass.

## Current Model

Findings now move through:

`Finding -> Section/Workflow -> Severity -> Status -> Ticket/Change ID -> Verification -> Closure`

The generic action queue keeps workflow, ticket, due-date, acknowledgement, fix, verification, and explicit review metadata. It does not keep generic person/team dispatch email fields.

## Evidence

| Area | Result | Evidence | Test |
| --- | --- | --- | --- |
| Generic action queue schema | PASS | `.overwatch_final/utils/action_queue.py`, `snowflake/mart_setup/03_config_and_audit_tables.sql` | `tests/test_owner_routing_removed.py`, `tests/test_admin_controls.py` |
| Active setup SQL | PASS | `snowflake/OVERWATCH_MART_SETUP.sql`, generated from split setup files | `tests/test_owner_routing_removed.py` |
| Operational route map | PASS | `snowflake/mart_setup/04_mart_tables.sql` keeps only workflow-section fallback columns | `tests/test_enterprise_operating_model.py` |
| Alert delivery email fields | PASS | Alert delivery keeps delivery-target fields only for notification mechanics | `tests/test_alert_delivery.py`, `tests/test_alert_center_default.py` |
| Migration and validation | PASS | `snowflake/migrations/2026_07_remove_owner_routing.sql`, `snowflake/validation/validate_owner_routing_removed.sql` | `tests/test_owner_routing_removed.py` |
| App default surfaces | PASS | Alert Center default and first-paint shells avoid person/team columns | `tests/test_alert_center_default.py`, `tests/test_first_paint_account_usage_audit.py` |

## Remaining Allowlist

| Term | Allowed Meaning |
| --- | --- |
| `WORKFLOW_ROUTE` | Section/workflow destination, not a person/team assignment. |
| `REVIEW_STATUS` | Explicit review state. |
| `REVIEWED_BY` | Actual human review/audit metadata. |
| `EMAIL_TARGET` | Alert notification delivery target only. |
| `ALLOCATION_SOURCE` / `ALLOCATION_BASIS` | Cost or telemetry allocation metadata, not dispatch ownership. |

The required repository searches are run before release and remaining hits are classified in the final report.
