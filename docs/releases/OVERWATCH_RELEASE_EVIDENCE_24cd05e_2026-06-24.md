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
- Run ID: `PERF_12_POWER_USERS_RELEASE_RERUN5`
- Users: `12`
- Iterations: `3`
- p95: `9938.77 ms`
- p99: `21049.17 ms`
- errors: `0`
- readiness: `92/100`
- slowest section: `App Shell`
- slowest action: `initial_load`
- skipped buttons: `0`
- live report path: `perf_tests/results/PERF_12_POWER_USERS_RELEASE_RERUN5_live_concurrent.json`
- expert review path: `perf_tests/results/PERF_12_POWER_USERS_RELEASE_RERUN5_expert_review.md`
- import timing path: `perf_tests/results/IMPORT_TIMING_F7C6308_RERUN5_import_timing.json`
- HTTP first-response path: `perf_tests/results/HTTP_FIRST_RESPONSE_F7C6308_RERUN5_http_first_response.json`
- initial-load ladder path: `perf_tests/results/PERF_INITIAL_LOAD_LADDER_RERUN5_initial_load_ladder.json`
- diagnostic overhead A/B path: `perf_tests/results/PERF_DIAGNOSTIC_OVERHEAD_RERUN5_diagnostic_overhead_ab.json`
- browser capacity matrix path: `perf_tests/results/PERF_BROWSER_CAPACITY_RERUN5_browser_capacity_matrix.json`
- section-nav-only diagnostic path: `perf_tests/results/PERF_12_POWER_USERS_SECTION_NAV_RERUN5_live_concurrent.json`
- diagnostic profile path: `perf_tests/results/PERF_12_POWER_USERS_DIAGNOSTIC_RERUN5_live_concurrent.json`
- scored profile: `perf_tests/profiles/12_power_users_release_scored.json`
- diagnostic profile: `perf_tests/profiles/12_power_users_diagnostic.json`
- diagnostic samples: `0` in the clean scored release run; `1152` section/initial-load substeps in the separate diagnostic profile run, excluded from clean release p95/readiness/error scoring.
- release scored action p95: `initial_load 23944.63 ms`, `section_nav 9026.44 ms`, `Load Active Alerts 1383.46 ms`, `Refresh Cost 1312.62 ms`.
- release scored section p95: `App Shell 23944.63 ms`, `DBA Control Room 10460.96 ms`, `Alert Center 5359.01 ms`, `Executive Landing 5338.62 ms`, `Workload Operations 4913.57 ms`, `Cost & Contract 4899.31 ms`.
- diagnostic initial-load breakdown p95: `goto_commit 11980.28 ms`, `shell_title_visible 11510.97 ms`, `domcontentloaded 4880.21 ms`, `initial_wait 1215.99 ms`, `idle_wait 918.39 ms`.
- diagnostic section-nav breakdown p95: `DBA Control Room title_visible 11036.14 ms`, `Alert Center title_visible 10025.02 ms`, `Cost & Contract title_visible 4925.65 ms`, `Executive Landing title_visible 4887.13 ms`, `Workload Operations title_visible 3447.54 ms`.
- diagnostic browser timing p95: `responseStart 11974.40 ms`, `domContentLoadedEventEnd 12237.20 ms`, `first-paint 12408.00 ms`, `first-contentful-paint 21220.00 ms`.
- diagnostic frontend paint metrics: DOM node count p95 `1220`, visible button count p95 `46`, CSS rule count p95 `1328`, script resource count p95 `46`, script transfer p95 `5395780 bytes`.
- diagnostic overhead A/B result: clean scored run p95 `31754.80 ms`, diagnostic run p95 `7895.38 ms`, delta `-23859.42 ms`; this noisy A/B result does not support diagnostic overhead as the primary blocker.
- HTTP first-response result: PASS as diagnostic, `HTTP_FIRST_RESPONSE_F7C6308_RERUN5`, users `1/3/6/9/12`, errors `0`; time-to-first-byte p95 stayed near `1017.79-1050.57 ms`, with 12-user TTFB p95 `1025.65 ms`.
- initial-load ladder result: diagnostic only, `PERF_INITIAL_LOAD_LADDER_RERUN5`; p95 by users was `1: 5870.52 ms`, `3: 3541.00 ms`, `6: 3529.94 ms`, `9: 7168.19 ms`, `12: 12412.68 ms`; 12-user `responseStart` p95 `2495.90 ms`, first contentful paint p95 `10152.00 ms`, and server shell total render p95 `67.30 ms`.
- browser capacity matrix result: diagnostic only, `PERF_BROWSER_CAPACITY_RERUN5`; slowest case was current `1440x1000/default` at 12 users with p95 `26147.68 ms`, `responseStart` p95 `9574.80 ms`, FCP p95 `23524.00 ms`, DOM node count p95 `382`, and resource count p95 `26`; all 12-user viewport/runtime variants remained above `21726 ms` p95.
- section-nav-only diagnostic result: FAIL, `PERF_12_POWER_USERS_SECTION_NAV_RERUN5`, p95 `19546.66 ms`, p99 `26304.47 ms`, errors `0`, skipped buttons `0`, readiness `57/100`; App Shell initial load p95 `26925.60 ms`, section_nav p95 `3373.27 ms`, and DBA Control Room title-visible p95 `18592.49 ms`.
- import timing summary: all `8` target imports passed; slowest target import was `sections.alert_center` at `2537.98 ms` (`519.87 ms` above the slowest baseline), followed by `shell` at `2452.07 ms` (`433.96 ms` above baseline) and `sections.cost_contract` at `1976.75 ms`. Baseline imports all passed; slowest baseline was `layout` at `2018.11 ms`.
- artifact storage: `perf_tests/results/` is intentionally stored outside git; reason: generated Playwright performance artifacts are local run evidence with environment-specific timing and browser metadata.
- result: FAIL for the release gate (runner state `WATCH`), because clean scored readiness remained below target (`92/100` < `95/100`) even though p95 was below `10000 ms`, errors were zero, and skipped buttons were zero.
- release blockers: readiness score remained below target (`92/100` < `95/100`), driven by the long initial-load tail (`max 23944.63 ms`, p99 `21049.17 ms`).
- top next fixes: treat the remaining issue as browser/frontend capacity and Streamlit client first-paint tail rather than instrumentation overhead or Snowflake query work; continue with frontend paint/resource reduction and local browser capacity controls, then rerun the clean scored profile.

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
- Reason: Failed on RERUN5 because the clean scored profile reached only `92/100` readiness; p95 improved to `9938.77 ms`, browser-step errors were `0`, and skipped buttons were `0`, but p99 remained `21049.17 ms` and the slowest App Shell initial load was `23944.63 ms`. Separate diagnostics show HTTP-only TTFB stayed near `1s`, diagnostic FCP p95 was `21220.00 ms`, and 12-user browser capacity variants remained above `21726 ms` p95, so the next pass should focus on frontend/client paint capacity and tail control before changing mart or Snowflake query paths.
- Owner: release operator
- Follow-up: tune Streamlit/browser first-paint tail and frontend resource pressure; rerun `python perf_tests/run_12_power_users.py --url http://localhost:8503/ --run-id PERF_12_POWER_USERS_RELEASE_RERUN6 --output-dir perf_tests/results --profile perf_tests/profiles/12_power_users_release_scored.json` and regenerate the expert review.
