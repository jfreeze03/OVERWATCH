# Route Alias Review

Scope: `.overwatch_final/route_registry.py` after the six-section navigation cleanup.

Decision rule: keep aliases only when they preserve a known deep link, saved session value, or display-label compatibility path and are covered by tests. Retired primary route buckets remain deleted.

## Section Aliases

| Alias | Canonical Section | Reason To Keep | Compatibility Source | Test Name | Decision |
| --- | --- | --- | --- | --- | --- |
| Executive Briefing | Executive Landing | Saved executive links still open the executive overview. | Historical primary route and workflow state. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Query Analysis | Workload Operations | Query investigation links open the consolidated workload workflow. | Historical primary route. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Query Search & History | Workload Operations | Query-history links still open Query Investigation with History Search selected. | Historical query-search route. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Task Management | Workload Operations | Task queue links open Pipeline & Task Health with failed tasks selected. | Historical task route. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Pipeline Health | Workload Operations | Pipeline links open Pipeline & Task Health with load/SLA focus. | Historical pipeline route. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Stored Proc Tracker | Workload Operations | Procedure links open Pipeline & Task Health with failed procedures focus. | Historical procedure route. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Object Change Monitor | Workload Operations | Change links open Change Analysis. | Historical object-change route. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Schema Compare | Workload Operations | Schema compare links open Advanced DBA Tools with that tool selected. | Historical DBA tools route. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Data Compare | Workload Operations | Data compare links open Advanced DBA Tools with that tool selected. | Historical DBA tools route. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Cost Intelligence | Cost & Contract | Public label compatibility maps the display label back to the canonical section. | Current display alias. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Credit Contract | Cost & Contract | Contract links open Budget vs Actual. | Historical contract route. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Recommendations | Cost & Contract | Recommendation links open Cost Recommendations. | Historical recommendation route. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Recommendations & Anomalies | Cost & Contract | Recommendation/anomaly links open Cost Recommendations. | Historical recommendation route. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Cortex Monitor | Cost & Contract | Cortex links open Cortex AI. | Historical Cortex route. | test_route_alias_review_documents_every_registered_alias | KEEP |
| AI & Cortex Monitor | Cost & Contract | AI/Cortex links open Cortex AI. | Historical Cortex route. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Usage Overview | DBA Control Room | Usage overview links open Cost Watch. | Historical usage route. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Alerts | Alert Center | Alert links open Active Alerts. | Historical alert route. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Alert History | Alert Center | Alert-history links open Alert History. | Historical alert-history route. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Alert Configuration | Alert Center | Configuration links open Alert Settings / Admin with delivery admin selected. | Historical alert-admin route. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Storage Monitor | Cost & Contract | Storage links open Cost Overview with Storage & Retention selected. | Historical storage route. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Security & Access | Security Monitoring | Security/access links open Risky Grants. | Historical security route. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Data Sharing | Security Monitoring | Data-sharing links open Data Sharing Exposure. | Historical security route. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Failed Logins | Security Monitoring | Failed-login links open Failed Logins. | Historical security route. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Access posture | Security Monitoring | Lowercase saved state opens Security Overview. | Saved session value. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Access Posture | Security Monitoring | Title-case saved state opens Security Overview. | Saved session value. | test_route_alias_review_documents_every_registered_alias | KEEP |

## Workflow Aliases

| Alias | Canonical Section | Canonical Workflow | Reason To Keep | Compatibility Source | Test Name | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| Executive Briefing | Executive Landing | Executive Overview | Preserves executive overview deep links. | Historical workflow label. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Executive Summary | Executive Landing | Executive Overview | Preserves summary deep links. | Historical workflow label. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Executive Scorecard | Executive Landing | Executive Admin / Advanced | Opens the admin/scorecard workflow. | Historical workflow label. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Scorecard Formulas | Executive Landing | Executive Admin / Advanced | Opens the admin/scorecard workflow. | Historical workflow label. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Value Ledger | Executive Landing | Executive Admin / Advanced | Opens value-ledger admin context. | Historical workflow label. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Production Readiness | Executive Landing | Executive Admin / Advanced | Opens production-readiness admin context. | Historical workflow label. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Forecasting | Executive Landing | Cost Movement | Opens executive cost movement. | Historical workflow label. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Issue Inbox | Alert Center | Active Alerts | Opens the default inbox view. | Historical alert pane. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Triage Digest | Alert Center | Active Alerts | Opens the default inbox view. | Historical alert pane. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Alert History | Alert Center | Alert History | Keeps history pane deep links stable. | Historical alert pane. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Alert Brief | Alert Center | Active Alerts | Opens the default inbox view. | Historical alert pane. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Control Health | Alert Center | Alert Settings / Admin | Opens alert admin controls. | Historical alert pane. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Cost | Alert Center | Cost Alerts | Opens cost alerts. | Historical alert pane. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Spend | Alert Center | Cost Alerts | Opens cost alerts. | Historical alert pane. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Cost / Cortex | Alert Center | Cost Alerts | Opens cost/Cortex alert family. | Historical alert pane. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Cost & Behavior | Alert Center | Cost Alerts | Opens cost alert family. | Historical alert pane. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Cortex | Alert Center | Cortex Predictive Alerts | Opens Cortex predictive alerts. | Historical alert pane. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Cortex Predictive | Alert Center | Cortex Predictive Alerts | Opens Cortex predictive alerts. | Historical alert pane. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Cortex Predictive Alerts | Alert Center | Cortex Predictive Alerts | Keeps canonical self-alias stable. | Canonical saved state. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Critical | Alert Center | Critical / High | Opens critical/high alert view. | Historical alert pane. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Critical / High | Alert Center | Critical / High | Keeps canonical self-alias stable. | Canonical saved state. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Workload | Alert Center | Reliability Alerts | Opens reliability alert family. | Historical alert pane. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Pipeline | Alert Center | Reliability Alerts | Opens reliability alert family. | Historical alert pane. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Reliability | Alert Center | Reliability Alerts | Opens reliability alert family. | Historical alert pane. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Security | Alert Center | Security Alerts | Opens security alert family. | Historical alert pane. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Email Delivery | Alert Center | Alert Settings / Admin | Opens delivery admin. | Historical alert admin label. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Action Queue Routing | Alert Center | Alert Settings / Admin | Opens action queue admin controls. | Historical alert admin label. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Delivery & Remediation | Alert Center | Alert Settings / Admin | Opens delivery admin controls. | Historical alert admin label. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Detection Catalog | Alert Center | Alert Settings / Admin | Opens detection catalog admin. | Historical alert admin label. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Delivery & Automation | Alert Center | Alert Settings / Admin | Opens delivery automation admin. | Current admin label. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Suppression Windows | Alert Center | Alert Settings / Admin | Opens suppression admin. | Historical alert admin label. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Alert Configuration | Alert Center | Alert Settings / Admin | Opens alert admin. | Historical alert admin label. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Alert Settings | Alert Center | Alert Settings / Admin | Opens alert admin. | Historical alert admin label. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Advanced Alert Admin | Alert Center | Alert Settings / Admin | Opens alert admin. | Historical alert admin label. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Security & Access | Security Monitoring | Risky Grants | Opens risky grants. | Historical security workflow. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Access posture | Security Monitoring | Security Overview | Opens security overview. | Saved session value. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Access Posture | Security Monitoring | Security Overview | Opens security overview. | Saved session value. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Login Audit | Security Monitoring | Failed Logins | Opens failed-login workflow. | Historical security workflow. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Login Posture | Security Monitoring | Failed Logins | Opens failed-login workflow. | Historical security workflow. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Roles & Grants | Security Monitoring | Risky Grants | Opens risky-grants workflow. | Historical security workflow. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Privilege sprawl | Security Monitoring | Privilege Sprawl | Opens privilege-sprawl workflow. | Historical security workflow. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Data Sharing | Security Monitoring | Data Sharing Exposure | Opens data-sharing exposure workflow. | Historical security workflow. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Data sharing exposure | Security Monitoring | Data Sharing Exposure | Opens data-sharing exposure workflow. | Historical security workflow. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Data Health | Security Monitoring | Security Admin / Advanced | Opens security admin diagnostics. | Historical security workflow. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Security Summary | Security Monitoring | Security Alerts | Opens security alerts. | Historical security workflow. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Object and access changes | Security Monitoring | Access Changes | Opens access changes. | Historical security workflow. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Advanced Security Diagnostics | Security Monitoring | Security Admin / Advanced | Opens security admin diagnostics. | Historical security workflow. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Security Admin | Security Monitoring | Security Admin / Advanced | Opens security admin diagnostics. | Historical security workflow. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Advanced Security | Security Monitoring | Security Admin / Advanced | Opens security admin diagnostics. | Historical security workflow. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Raw Grants | Security Monitoring | Security Admin / Advanced | Opens security admin diagnostics. | Historical security workflow. | test_route_alias_review_documents_every_registered_alias | KEEP |
| Role Readiness | Security Monitoring | Security Admin / Advanced | Opens security admin diagnostics. | Historical security workflow. | test_route_alias_review_documents_every_registered_alias | KEEP |

## Deleted Alias Buckets

| Alias Bucket | Decision | Test Name |
| --- | --- | --- |
| Retired primary-section redirect bucket | DELETE | test_route_alias_review_keeps_retired_alias_bucket_empty |
