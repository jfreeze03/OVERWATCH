# OVERWATCH Performance Audit

Date: 2026-06-22

## Current Position

OVERWATCH is still large, but the performance direction is now clear: first paint should use compact marts and daily operators should not trigger broad live scans until they explicitly load details.

The new regression runner confirmed static workflow coverage but could not complete live Snowflake SQL checks because the local connection failed before authentication:

`390190 (08001): Failed to connect to DB: LOKAXGM-WU94316.snowflakecomputing.com:443, There was an error related to the SAML Identity Provider account parameter.`

Local Streamlit section smoke completed successfully:

- Run ID: `PERF_TEST_SECTION_SMOKE_HARDENING`
- Readiness: `PASS`
- Score: `100`
- p95: `2385.17 ms`
- Slowest section: `Cost & Contract`

## Performance Risks Found

| Risk | Evidence | Impact | Fix status |
|---|---|---|---|
| Local Snowflake auth blocks live regression | `docs/OVERWATCH_SNOWFLAKE_REGRESSION_RESULTS.md` | Cannot validate live SQL, object freshness, query count, or timings from this workstation until account/auth is corrected. | Blocked by connection configuration. |
| Large section modules | `cost_contract.py` 5003 lines, `alert_center.py` 3432 lines, `security_posture.py` 3267 lines, `account_health.py` 3604 lines | Slow imports, hard-to-review UI changes, repeated helpers. | Documented for de-bloat. |
| Heavy fallback SQL remains in legacy/detail modules | `ACCOUNT_USAGE` appears in account health, contention, change drift, cortex, shared command-board helpers | Risk of expensive scans if routed outside explicit load gates. | Needs continued query audit. |
| Historical proof/scorecard logic still exists | Advanced panes load value, scorecard, production-readiness, closed-loop, and correlated investigation details | Useful for admin, but not daily first screen. | Hidden behind advanced/load gates in current workflow sections. |
| Duplicate cost/workload helper surfaces | Cost Contract delegates to Cost Center, Warehouse Health, Recommendations, Cortex, Storage; Workload delegates to old query/task modules | Preserves functionality but increases mental and code overhead. | Route tests prove mappings; de-bloat plan identifies rewrite candidates. |
| Cost & Contract remains slowest smoke section | Section smoke p95 2385.17 ms, slowest section Cost & Contract | Still acceptable locally, but it is the first de-bloat candidate. | Documented for next rewrite pass. |

## Fixes Completed In This Pass

- Removed stale primary UI labels that sent users toward old route names.
- Kept detail/evidence panels behind explicit load buttons.
- Added `perf_tests/full_app_snowflake_regression.py` for repeatable live regression evidence.
- Added static workflow coverage to the regression runner for all six sections and their current workflows.
- Confirmed command/correlated investigation detail panels are load-gated by `tests/test_command_center.py`.
- Updated Snowflake descriptive text so mart setup messages align with the current investigation language.

## Deferred Performance Work

| Area | Rewrite direction |
|---|---|
| `cost_contract.py` | Split workflow renderers from live SQL/detail evidence; keep Cost Overview first-paint mart-only. |
| `utils/alerts.py` | Separate alert catalog/build SQL from active alert queue rendering and admin delivery actions. |
| `warehouse_health.py` | Fold operator-facing pieces into Cost & Contract > Waste Detection and keep raw advisor controls advanced. |
| `account_health.py` | Retire visible legacy account health workflows after DBA Control Room coverage is complete. |
| `shared_metrics.py` | Normalize query caching and remove repeated SQL builders after Snowflake regression can compare output. |

## Measurement Commands

Commands run in this pass:

```powershell
.\.venv\Scripts\python.exe .\perf_tests\section_smoke_runner.py --url http://localhost:8501/ --timeout-ms 30000 --initial-wait-ms 1500 --run-id PERF_TEST_SECTION_SMOKE_HARDENING
```

Run after the Snowflake auth issue is fixed:

```powershell
.\.venv\Scripts\python.exe perf_tests\full_app_snowflake_regression.py --run-id SNOWFLAKE_REGRESSION_LIVE
```

## Release Position

Performance signoff is partially complete: local section smoke passes, static route/workflow checks pass, and live SQL timing is blocked by authentication. Full production signoff still requires the Snowflake regression runner to pass against the intended test account.
