# OVERWATCH Release Evidence

## Commit
- Commit SHA: `24cd05e2e27ced74b29718ba85ce6112b2227cf7`
- Branch: `main`
- Release date: `2026-06-24`
- Operator: `jfreeze03`

## Validation Commands
- `python -m ruff check .overwatch_final tests perf_tests`: PASS, `All checks passed!`
- `python -m mypy`: PASS, `Success: no issues found in 7 source files`
- `python -m compileall .overwatch_final tests perf_tests`: PASS, compiled app, tests, and perf tests
- `python -m unittest tests.test_deployment_contract`: PASS, 14 tests
- `python -m unittest tests.test_cortex_guard`: PASS, 6 tests
- `python -m unittest tests.test_release_manifest_contract tests.test_release_evidence_contract tests.test_production_readiness_contract tests.test_snowflake_regression_results_contract tests.test_release_process_contract`: PASS, 26 tests
- `python -m unittest tests.test_mart_contracts tests.test_validation_workflow tests.test_route_registry tests.test_facade_no_creep`: PASS, 42 tests
- `python -m unittest discover -s tests`: PASS, 1039 tests, 1 skipped

## Deployment Contract
- Streamlit in Snowflake entrypoint: PASS via `tests.test_deployment_contract`
- Manifest: PASS via `tests.test_deployment_contract`
- Warehouse: PASS via `tests.test_deployment_contract`
- Execute-as boundary: PASS via `tests.test_deployment_contract`
- Result: PASS, deployment contract validated locally for `24cd05e2e27ced74b29718ba85ce6112b2227cf7`

## Mart Setup
- Setup script used: `snowflake/OVERWATCH_MART_SETUP.sql`
- Target account/environment: `LOKAXGM-WU94316`, `DBA_MAINT_DB.OVERWATCH`
- Core facts verified: PASS in `docs/OVERWATCH_SNOWFLAKE_REGRESSION_RESULTS.md`
- Mart load status: PASS in the latest credentialed live regression evidence
- Notes: Mart setup was not rerun in this pass because no mart object drop, rename, disable, rewrite, or SQL semantic change was made.

## Browser Sanity
- Executive Landing: PASS in section smoke run `PERF_TEST_SECTION_SMOKE_RELEASE_24cd05e`
- DBA Control Room: PASS in section smoke run `PERF_TEST_SECTION_SMOKE_RELEASE_24cd05e`
- Alert Center: PASS in section smoke run `PERF_TEST_SECTION_SMOKE_RELEASE_24cd05e`
- Cost & Contract: PASS in section smoke run `PERF_TEST_SECTION_SMOKE_RELEASE_24cd05e`
- Workload Operations: PASS in section smoke run `PERF_TEST_SECTION_SMOKE_RELEASE_24cd05e`
- Security Monitoring: PASS in section smoke run `PERF_TEST_SECTION_SMOKE_RELEASE_24cd05e`
- Legacy/deep-link workflow checks: covered by route registry, navigation integrity, facade no-creep, and full unit discovery tests; no separate manual deep-link browser pass was run because route compatibility is locked by automated contracts.

## Performance Smoke
- `perf_tests/README.md` threshold review: PASS, section smoke completed against `http://localhost:8503/`
- Section smoke result: PASS, `PERF_TEST_SECTION_SMOKE_RELEASE_24cd05e`
- HTTP/live browser p95: `2388.01 ms`
- Failed dashboard queries: `0` section smoke errors recorded
- Readiness score: `100/100`

## 12 Power User Performance
- Run ID: `PERF_12_POWER_USERS_RELEASE_RERUN3`
- Users: `12`
- Iterations: `3`
- p95: `15388.74 ms`
- p99: `37835.50 ms`
- errors: `0`
- readiness: `64/100`
- slowest section: `App Shell`
- slowest action: `initial_load`
- skipped buttons: `0`
- live report path: `perf_tests/results/PERF_12_POWER_USERS_RELEASE_RERUN3_live_concurrent.json`
- expert review path: `perf_tests/results/PERF_12_POWER_USERS_RELEASE_RERUN3_expert_review.md`
- import timing path: `perf_tests/results/IMPORT_TIMING_3E75A32_RERUN3_import_timing.json`
- initial-load-only diagnostic path: `perf_tests/results/PERF_12_POWER_USERS_INITIAL_LOAD_RERUN3_live_concurrent.json`
- diagnostic samples: `120` initial-load substeps in the release run, excluded from release p95/readiness/error scoring.
- release initial-load breakdown p95: `shell_title_visible 27281.85 ms`, `goto_commit 9175.17 ms`, `domcontentloaded 9152.78 ms`, `section_container_visible 8919.38 ms`, `initial_wait 1208.94 ms`, `idle_wait 922.74 ms`.
- release server phase p95: `shell:total_render_app 212.41 ms`, `shell:dispatch_section_total 102.74 ms`, `section_dispatch:render:Executive Landing 97.63 ms`, `executive_shell:workflow_selector 97.16 ms`, `shell:render_sidebar 93.84 ms`.
- release browser timing p95: `responseStart 9169.90 ms`, `domContentLoadedEventEnd 11692.50 ms`, `first-paint 11792.00 ms`, `first-contentful-paint 37408.00 ms`.
- initial-load-only diagnostic result: FAIL, `PERF_12_POWER_USERS_INITIAL_LOAD_RERUN3`, p95 `23790.15 ms`, p99 `23790.15 ms`, errors `0`, skipped buttons `0`, readiness `57/100`; server render p95 was `319.74 ms`, while browser `responseStart` p95 was `11303.00 ms` and first contentful paint p95 was `22428.00 ms`.
- import timing summary: all `8` target imports passed; slowest target import was `sections.alert_center` at `2761.46 ms` (`737.67 ms` above the slowest baseline), followed by `shell` at `2670.90 ms` (`647.11 ms` above baseline) and `sections.cost_contract` at `1943.46 ms`. Baseline imports all passed; slowest baseline was `pandas` at `2023.79 ms`.
- artifact storage: `perf_tests/results/` is intentionally stored outside git; reason: generated Playwright performance artifacts are local run evidence with environment-specific timing and browser metadata.
- result: FAIL, because p95 exceeded the 10000 ms 12-power-user release threshold even though browser-step errors were zero.
- release blockers: p95 threshold exceeded (`15388.74 ms` > `10000 ms`) and readiness remained below target (`64/100` < `95/100`).
- top next fixes: tune Streamlit/server first response and browser first contentful paint under 12 concurrent sessions; then investigate first-iteration DBA Control Room navigation p95 (`28124.10 ms`) after App Shell contention is reduced.

## Guarded Operations
- Action queue review-only smoke: PASS via unit contracts covering review-only action queue behavior and full unit discovery
- Typed confirmation smoke: PASS via guarded Task Management/Admin contracts and full unit discovery
- `admin_button_disabled()` unauthorized-user smoke: PASS via production readiness contract, admin control tests, guarded Task Management contracts, and full unit discovery
- Notes: No state-changing admin operation was executed as part of this release evidence pass.

## Live Snowflake Regression
- Run status: PASS from latest credentialed run; no new live Snowflake regression was run for `24cd05e`.
- Credentials/auth available: available for the recorded run in `docs/OVERWATCH_SNOWFLAKE_REGRESSION_RESULTS.md`
- Result: PASS from prior credentialed evidence, see `docs/OVERWATCH_SNOWFLAKE_REGRESSION_RESULTS.md`
- Status: `PASS`
- Run ID: `SNOWFLAKE_REGRESSION_LIVE_PASS`
- Role: `SNOW_ACCOUNTADMINS`
- Warehouse: `COMPUTE_WH`
- Database/schema: `DBA_MAINT_DB.OVERWATCH`
- If not run, reason: New live regression not run for `24cd05e` because the latest credentialed PASS evidence was already recorded; local validation, full unit regression, and section smoke were rerun for this release candidate.

## Secrets Check
- Git diff/logs/screenshots/release notes checked: PASS, tracked release files contain no literal Snowflake password, private key, or token.
- Result: PASS, `.streamlit/secrets.toml` and generated performance results remain ignored.

## Rollback / Reset
- Rollback reference: `STREAMLIT_CLOUD_DEPLOY.md`
- `snowflake/OVERWATCH_MART_DROP.sql` reset posture acknowledged: acknowledged as reset/rollback only, not a rationalization or release step
- Notes: No mart object was dropped, renamed, disabled, or rewritten in this pass.

## Deferred Items
- Item: New live Snowflake regression run for `24cd05e`
- Reason: Not rerun because existing credentialed PASS evidence is linked and local validation plus section smoke were rerun for this release candidate.
- Owner: release operator
- Follow-up: rerun `perf_tests/full_app_snowflake_regression.py` only when a fresh credentialed release gate is required.
- Item: 12 heavy power user benchmark for `24cd05e`
- Reason: Failed on RERUN3 because live browser p95 was `15388.74 ms` against the `10000 ms` threshold and readiness was `64/100`; skipped buttons remained `0`, but App Shell `initial_load` remained the slowest action. Diagnostic substeps show high browser/server first response and paint timing: `responseStart` p95 `9169.90 ms`, `domContentLoadedEventEnd` p95 `11692.50 ms`, and `first-contentful-paint` p95 `37408.00 ms`, while server-side `shell:total_render_app` p95 was `212.41 ms`.
- Owner: release operator
- Follow-up: tune Streamlit/server first-response and browser paint tail latency; rerun `python perf_tests/run_12_power_users.py --url http://localhost:8503/ --run-id PERF_12_POWER_USERS_RELEASE_RERUN4 --output-dir perf_tests/results` and regenerate the expert review.
