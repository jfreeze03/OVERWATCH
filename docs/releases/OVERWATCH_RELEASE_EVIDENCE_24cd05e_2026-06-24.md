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
- Run ID: `PERF_12_POWER_USERS_RELEASE_RERUN4`
- Users: `12`
- Iterations: `3`
- p95: `28187.44 ms`
- p99: `38916.67 ms`
- errors: `0`
- readiness: `57/100`
- slowest section: `App Shell`
- slowest action: `initial_load`
- skipped buttons: `2`, Alert Center -> Load Active Alerts; Cost & Contract -> Refresh Cost
- live report path: `perf_tests/results/PERF_12_POWER_USERS_RELEASE_RERUN4_live_concurrent.json`
- expert review path: `perf_tests/results/PERF_12_POWER_USERS_RELEASE_RERUN4_expert_review.md`
- import timing path: `perf_tests/results/IMPORT_TIMING_CCFBC48_RERUN4_import_timing.json`
- HTTP first-response path: `perf_tests/results/HTTP_FIRST_RESPONSE_CCFBC48_RERUN4_http_first_response.json`
- initial-load ladder path: `perf_tests/results/PERF_INITIAL_LOAD_LADDER_RERUN4_initial_load_ladder.json`
- initial-load-only diagnostic path: `perf_tests/results/PERF_12_POWER_USERS_INITIAL_LOAD_RERUN4_live_concurrent.json`
- diagnostic samples: `1152` section/initial-load substeps in the release run, excluded from release p95/readiness/error scoring.
- release initial-load breakdown p95: `shell_title_visible 27875.42 ms`, `goto_commit 10820.61 ms`, `domcontentloaded 1657.49 ms`, `section_container_visible 1337.12 ms`, `initial_wait 1214.36 ms`, `idle_wait 921.39 ms`.
- release section-nav breakdown p95: `DBA Control Room title_visible 27759.22 ms`, `Alert Center title_visible 27170.05 ms`, `Cost & Contract title_visible 26784.86 ms`, `Workload Operations title_visible 26704.54 ms`, `Executive Landing title_visible 26257.31 ms`.
- release app-entry p95: `pre_render_total 81.67 ms`, `set_page_config 81.66 ms`, `import_shell 0.01 ms`.
- release server phase p95: `section_dispatch:render:Cost & Contract 1259.76 ms`, `section_dispatch:render:Alert Center 1100.82 ms`, `shell:total_render_app 1060.46 ms`, `shell:dispatch_section_total 907.64 ms`, `section_dispatch:render:DBA Control Room 395.52 ms`.
- release browser timing p95: `responseStart 10815.40 ms`, `domContentLoadedEventEnd 11132.20 ms`, `first-paint 11228.00 ms`, `first-contentful-paint 37416.00 ms`.
- initial-load-only diagnostic result: WATCH, `PERF_12_POWER_USERS_INITIAL_LOAD_RERUN4`, p95 `11402.73 ms`, p99 `11402.73 ms`, errors `0`, skipped buttons `0`, readiness `86/100`; app-entry pre-render p95 was `3.20 ms`, server render p95 was `145.38 ms`, browser `responseStart` p95 was `4000.00 ms`, and first contentful paint p95 was `9988.00 ms`.
- HTTP first-response result: PASS as diagnostic, `HTTP_FIRST_RESPONSE_CCFBC48_RERUN4`, users `1/3/6/9/12`, errors `0`; time-to-first-byte p95 stayed near `1015.07-1043.96 ms`, with 12-user TTFB p95 `1032.13 ms`.
- initial-load ladder result: diagnostic only, `PERF_INITIAL_LOAD_LADDER_RERUN4`; p95 by users was `1: 5359.33 ms`, `3: 3529.89 ms`, `6: 3728.51 ms`, `9: 7130.42 ms`, `12: 12376.22 ms`; 12-user `responseStart` p95 `2526.00 ms`, first contentful paint p95 `10052.00 ms`, and server shell total render p95 `68.74 ms`.
- import timing summary: all `8` target imports passed; slowest target import was `sections.alert_center` at `2502.34 ms` (`474.22 ms` above the slowest baseline), followed by `shell` at `2458.99 ms` (`430.87 ms` above baseline) and `sections.cost_contract` at `1932.66 ms`. Baseline imports all passed; slowest baseline was `layout` at `2028.12 ms`.
- artifact storage: `perf_tests/results/` is intentionally stored outside git; reason: generated Playwright performance artifacts are local run evidence with environment-specific timing and browser metadata.
- result: FAIL, because p95 exceeded the 10000 ms 12-power-user release threshold and two configured load actions skipped, even though browser-step errors were zero.
- release blockers: p95 threshold exceeded (`28187.44 ms` > `10000 ms`), two configured load buttons skipped (`Alert Center -> Load Active Alerts`; `Cost & Contract -> Refresh Cost`), and readiness remained below target (`57/100` < `95/100`).
- top next fixes: treat this as a Streamlit/browser concurrency and first-paint capacity issue first, because HTTP-only TTFB stayed near `1s` and app-entry/server phases were much lower than browser FCP; then investigate section navigation title-visible waits for Alert Center, DBA Control Room, and Cost & Contract.

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
- Reason: Failed on RERUN4 because live browser p95 was `28187.44 ms` against the `10000 ms` threshold and readiness was `57/100`; one Alert Center `Load Active Alerts` action and one Cost & Contract `Refresh Cost` action skipped. Diagnostics show high browser first response/paint and section title-visible waits: release `responseStart` p95 `10815.40 ms`, `first-contentful-paint` p95 `37416.00 ms`, DBA Control Room title-visible p95 `27759.22 ms`, and Alert Center title-visible p95 `27170.05 ms`, while app-entry import p95 and server render p95 were much lower. HTTP-only TTFB remained near `1s`, so the next pass should focus on Streamlit/browser concurrency capacity and client paint pressure before changing mart or Snowflake query paths.
- Owner: release operator
- Follow-up: tune Streamlit/browser first-paint concurrency and section title-visible waits; rerun `python perf_tests/run_12_power_users.py --url http://localhost:8503/ --run-id PERF_12_POWER_USERS_RELEASE_RERUN5 --output-dir perf_tests/results` and regenerate the expert review.
