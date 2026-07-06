# OVERWATCH Final Regression Report

Date: 2026-06-22

## Summary

This hardening pass focused on route/label correctness, compatibility-safe workflow routing, real regression tooling, and documentation of remaining de-bloat and mart strategy work. It did not remove functional areas or collapse the app into four sections.

## Commands Run

| Command | Status | Notes |
|---|---|---|
| `.\.venv\Scripts\python.exe -m unittest tests.test_navigation_integrity tests.test_contention_center tests.test_operational_intelligence` | PASS | 77 tests passed. |
| `.\.venv\Scripts\python.exe -m unittest tests.test_formula_regressions` | PASS | 289 tests passed. |
| `.\.venv\Scripts\python.exe -m unittest tests.test_command_center` | PASS | 11 tests passed after visible labels changed to correlated/investigation language. |
| `.\.venv\Scripts\python.exe -m unittest tests.test_navigation_integrity tests.test_contention_center tests.test_operational_intelligence tests.test_command_center` | PASS | 88 focused route/label/investigation tests passed. |
| `.\.venv\Scripts\python.exe -m unittest discover -s tests` | PASS | 642 tests passed. |
| `.\.venv\Scripts\python.exe -m unittest tests.test_navigation_integrity` | PASS | 61 navigation/contract tests passed after centralizing the workflow contract. |
| `.\.venv\Scripts\python.exe -m py_compile <touched files>` | PASS | Python syntax check passed for changed app/test/regression files. |
| `.\.venv\Scripts\python.exe perf_tests\full_app_snowflake_regression.py --run-id SNOWFLAKE_REGRESSION_HARDENING` | FAIL | Actual Snowflake connection failed with SAML account parameter error before SQL checks. Static workflow checks passed. |
| Streamlit app boot at `http://localhost:8501/` | PASS | HTTP 200 OK. |
| `.\.venv\Scripts\python.exe .\perf_tests\section_smoke_runner.py --url http://localhost:8501/ --timeout-ms 30000 --initial-wait-ms 1500 --run-id PERF_TEST_SECTION_SMOKE_HARDENING` | PASS | Score 100, p95 2385.17 ms, slowest section Cost & Contract. |
| `rg -n "bad character pattern" .overwatch_final tests docs README.md` | PASS | No matches. |
| `git diff --check` | PASS | No whitespace errors. |

## Snowflake Environment Used

- Account: `LOKAXGM-WU94316`
- User: `CHRISJOHNSON1985007`
- Role: `ACCOUNTADMIN`
- Warehouse: `WH_ALFA_OVERWATCH`
- Database/schema: `DBA_MAINT_DB.OVERWATCH`
- Authenticator: `externalbrowser`

## Failures

| Failure | Impact | Next action |
|---|---|---|
| Snowflake connector failed with `390190 (08001)` SAML Identity Provider account parameter error. | Live SQL regression could not validate object existence, mart freshness, ACCOUNT_USAGE access, or workflow SQL execution. | Correct local Snowflake account/authenticator configuration or run with a working `SNOWFLAKE_*` auth method, then rerun `perf_tests/full_app_snowflake_regression.py`. |

Additional account probes:

- `LOKAXGM-WU94316`: SAML Identity Provider account parameter error.
- `de53256.us-east-2.aws`: same SAML Identity Provider account parameter error.
- `LOKAXGM-WU94316.us-east-2.aws`: connector host form invalid, returned 404.

## Skipped Because Blocked

- Live mart existence checks.
- Live mart freshness checks.
- Live ACCOUNT_USAGE access checks.
- Live SQL compile/execution checks.
- Live performance timings by workflow.

## Known Issues

- The codebase remains large; this pass documented de-bloat targets but did not perform a risky module rewrite.
- The six-section workflow contract is now centralized for tests and live regression, but section modules still contain their own render-specific workflow tuples.
- Internal object names still include `COMMAND_CENTER` for backward compatibility. Visible UI text now uses correlated investigations.
- Several legacy labels remain as route aliases by design. Tests prove they redirect to current workflows.
- Full suite, section smoke, bad-character scan, and `git diff --check` passed after code changes. `git diff --check` should be rerun after any later documentation edits.

## Current Recommendation

No broad production signoff from this machine until the Snowflake auth problem is fixed and the live regression runner passes. Static route/label regression is significantly stronger now, and the app remains on the correct six-section model.
