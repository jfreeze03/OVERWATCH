# OVERWATCH Release Evidence

## Commit
- Commit SHA: `a00846f03bb8bcce9a9dfdc3a01101eadbbc2c57`
- Branch: `main`
- Release date: `2026-06-23`
- Operator: `jfreeze03`

## Validation Commands
- `python -m ruff check .overwatch_final tests`: PASS, `All checks passed!`
- `python -m mypy`: PASS, `Success: no issues found in 7 source files`
- `python -m compileall .overwatch_final tests`: PASS, compiled app and tests
- `python -m unittest tests.test_deployment_contract`: PASS, 14 tests
- `python -m unittest tests.test_cortex_guard`: PASS, 6 tests
- `python -m unittest tests.test_mart_contracts tests.test_production_readiness_contract`: PASS, 25 tests
- `python -m unittest tests.test_validation_workflow tests.test_route_registry tests.test_facade_no_creep`: PASS, 22 tests
- `python -m unittest discover -s tests`: PASS, 976 tests

## Deployment Contract
- Streamlit in Snowflake entrypoint: PASS via `tests.test_deployment_contract`
- Manifest: PASS via `tests.test_deployment_contract`
- Warehouse: PASS via `tests.test_deployment_contract`
- Execute-as boundary: PASS via `tests.test_deployment_contract`
- Result: PASS, deployment contract validated locally

## Mart Setup
- Setup script used: `snowflake/OVERWATCH_MART_SETUP.sql`
- Target account/environment: `LOKAXGM-WU94316`, `DBA_MAINT_DB.OVERWATCH`
- Core facts verified: PASS in `docs/OVERWATCH_SNOWFLAKE_REGRESSION_RESULTS.md`
- Mart load status: PASS in the latest credentialed live regression evidence
- Notes: Mart setup was not rerun in this pass; this evidence references the latest recorded credentialed run.

## Browser Sanity
- Executive Landing: PASS in section smoke run `PERF_TEST_SECTION_SMOKE_RELEASE`
- DBA Control Room: PASS in section smoke run `PERF_TEST_SECTION_SMOKE_RELEASE`
- Alert Center: PASS in section smoke run `PERF_TEST_SECTION_SMOKE_RELEASE`
- Cost & Contract: PASS in section smoke run `PERF_TEST_SECTION_SMOKE_RELEASE`
- Workload Operations: PASS in section smoke run `PERF_TEST_SECTION_SMOKE_RELEASE`
- Security Monitoring: PASS in section smoke run `PERF_TEST_SECTION_SMOKE_RELEASE`
- Legacy/deep-link workflow checks: covered by route registry, navigation integrity, facade no-creep, and full unit discovery tests; no separate manual deep-link browser pass was run in this pass because route compatibility is locked by automated contracts.

## Performance Smoke
- `perf_tests/README.md` threshold review: PASS, section smoke completed against `http://localhost:8501/`
- Section smoke result: PASS, `PERF_TEST_SECTION_SMOKE_RELEASE`
- HTTP/live browser p95: `299.12 ms`
- Failed dashboard queries: `0` section smoke errors recorded
- Readiness score: `100/100`

## 12 Power User Performance
- Run ID: not run; reason: the 12-heavy-power-user benchmark did not exist for this historical evidence pass.
- Users: not run; reason: benchmark profile was added after this historical evidence pass.
- Iterations: not run; reason: benchmark profile was added after this historical evidence pass.
- p95: not run; reason: benchmark profile was added after this historical evidence pass.
- errors: not run; reason: benchmark profile was added after this historical evidence pass.
- readiness: not run; reason: benchmark profile was added after this historical evidence pass.
- expert review path: not run; reason: expert review generator was added after this historical evidence pass.
- result: not run; reason: run `perf_tests/run_12_power_users.py` before using this historical evidence for a high-traffic release.

## Guarded Operations
- Action queue review-only smoke: PASS via unit contracts covering review-only action queue behavior and full unit discovery
- Typed confirmation smoke: PASS via guarded Task Management/Admin contracts and full unit discovery
- `admin_button_disabled()` unauthorized-user smoke: PASS via production readiness contract, admin control tests, guarded Task Management contracts, and full unit discovery
- Notes: No state-changing admin operation was executed as part of this release evidence pass.

## Live Snowflake Regression
- Run status: PASS from latest credentialed run; no new live Snowflake regression was run in this pass.
- Credentials/auth available: available for the recorded run in `docs/OVERWATCH_SNOWFLAKE_REGRESSION_RESULTS.md`
- Result: PASS, see `docs/OVERWATCH_SNOWFLAKE_REGRESSION_RESULTS.md`
- Status: `PASS`
- Run ID: `SNOWFLAKE_REGRESSION_LIVE_PASS`
- Role: `SNOW_ACCOUNTADMINS`
- Warehouse: `WH_ALFA_OVERWATCH`
- Database/schema: `DBA_MAINT_DB.OVERWATCH`
- If not run, reason: New live regression not run in this pass because the latest credentialed PASS evidence was already recorded; local validation, full unit regression, and section smoke were rerun for this evidence.

## Secrets Check
- Git diff/logs/screenshots/release notes checked: PASS, tracked-file scan found only placeholder/env-variable references and code variable names; `.streamlit/secrets.toml` remains ignored.
- Result: PASS, no literal credential was added to tracked release evidence or code.

## Rollback / Reset
- Rollback reference: `STREAMLIT_CLOUD_DEPLOY.md`
- `snowflake/OVERWATCH_MART_DROP.sql` reset posture acknowledged: acknowledged as reset/rollback only, not a rationalization or release step
- Notes: No mart object was dropped, renamed, disabled, or rewritten in this pass.

## Deferred Items
- Item: New live Snowflake regression run for this release evidence pass
- Reason: Not rerun; existing credentialed PASS evidence is linked and local validation plus section smoke were rerun.
- Workflow: release operator
- Follow-up: rerun `perf_tests/full_app_snowflake_regression.py` only when a fresh credentialed release gate is required.
