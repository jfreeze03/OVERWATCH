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
- Run ID: `PERF_12_POWER_USERS_RELEASE_RERUN7C`
- Users: `12`
- Iterations: `3`
- p95: `29766.24 ms`
- p99: `32214.09 ms`
- max: `33570.63 ms`
- errors: `1`
- skipped buttons: `1`, Alert Center -> Load Active Alerts
- readiness: `35/100`
- slowest section: `App Shell`
- slowest action: `initial_load`
- live report path: `perf_tests/results/PERF_12_POWER_USERS_RELEASE_RERUN7C_live_concurrent.json`
- expert review path: `perf_tests/results/PERF_12_POWER_USERS_RELEASE_RERUN7C_expert_review.md`
- import timing path: `perf_tests/results/IMPORT_TIMING_483CD39_RERUN7_import_timing.json`
- HTTP first-response path: `perf_tests/results/HTTP_FIRST_RESPONSE_483CD39_RERUN7_http_first_response.json`
- release stability path: `perf_tests/results/PERF_RELEASE_STABILITY_RERUN7_release_stability.json`
- diagnostic profile path: `perf_tests/results/PERF_12_POWER_USERS_DIAGNOSTIC_RERUN7C_live_concurrent.json`
- scored profile: `perf_tests/profiles/12_power_users_release_scored.json`
- diagnostic profile: `perf_tests/profiles/12_power_users_diagnostic.json`
- diagnostic samples: `0` in the clean scored release run; in-run tail captures and tail replays ran after each scored stopwatch stopped or after the scored run completed, and are excluded from clean release p95/readiness/error scoring.
- readiness penalties: `p95_threshold`, `35` points, because p95 `29766.24 ms` exceeded `10000.00 ms`; `p99_tail`, `8` points, because p99 `32214.09 ms` exceeded the tail threshold `18000.00 ms` (`fail_p95_ms * 1.8`); `error_rate`, `20` points, because one browser-error step produced error rate `0.0033`; `browser_errors`, `2` points, because one step recorded Streamlit client 404 messages.
- tail summary: p95 threshold `10000.00 ms`, p99 tail threshold `18000.00 ms`, observed p99 `32214.09 ms`, p99 overage `14214.09 ms`, slowest initial-load user `8`, iteration `1`, elapsed `33570.63 ms`.
- release scored action p95: `initial_load 33570.63 ms`, `section_nav 29729.15 ms`, `Load Active Alerts 3111.19 ms`, `Refresh Cost 1941.86 ms`.
- release scored section p95: `App Shell 33570.63 ms`, `DBA Control Room 31264.12 ms`, `Workload Operations 30164.76 ms`, `Alert Center 29263.81 ms`, `Cost & Contract 28635.79 ms`, `Executive Landing 5896.36 ms`, `Security Monitoring 4839.59 ms`.
- in-run tail capture result: `6` initial-load tail captures were collected after scored timing stopped. The slowest capture was user `8`, elapsed `33570.63 ms`, browser `responseStart 8919.10 ms`, `first-contentful-paint 31924.00 ms`, DOM node count `586`, script transfer `3159638 bytes`, while server trace remained small: `shell:total_render_app 255.12 ms`, `shell:dispatch_section_total 203.07 ms`, `section_dispatch:render:Executive Landing 201.79 ms`, and app-entry pre-render `3.37 ms`.
- tail replay result: slowest scored initial-load users replayed single-user with responseStart near `312 ms` and first-contentful-paint near `908 ms`; the slowest section-nav replay also stayed under `1s` first-contentful-paint. Reproduction summary: `3` replays, `0` reproduced, `3` not reproduced. This keeps the remaining blocker in concurrent browser/client timing rather than a slow single-session app render.
- release stability result: diagnostic only, `PERF_RELEASE_STABILITY_RERUN7`; `3` clean scored repeats, median p95 `21036.23 ms`, median p99 `29165.62 ms`, median max `29259.31 ms`, median readiness `57/100`, worst p95 `27106.49 ms`, worst p99 `29206.46 ms`, worst max `31368.67 ms`, worst readiness `57/100`, pass/watch/fail count `0/1/2`, errors `0`, skipped buttons `2`, p99-tail runs `3`, conclusion `unstable_environment_tail`.
- diagnostic profile result: `PERF_12_POWER_USERS_DIAGNOSTIC_RERUN7C`, p95 `9230.10 ms`, p99 `21250.46 ms`, max `24271.98 ms`, errors `0`, skipped buttons `0`, readiness `92/100`; diagnostic profile is not the release gate.
- diagnostic initial-load breakdown p95: `domcontentloaded 11902.64 ms`, `shell_title_visible 11670.50 ms`, `goto_commit 10866.50 ms`, `idle_wait 2113.33 ms`, `initial_wait 1233.17 ms`, `section_container_visible 268.44 ms`.
- diagnostic section-nav breakdown p95: `DBA Control Room title_visible 11480.06 ms`, `Alert Center title_visible 8249.81 ms`, `Security Monitoring title_visible 4399.29 ms`, `Cost & Contract title_visible 4004.76 ms`, `Executive Landing title_visible 3376.81 ms`, `Workload Operations title_visible 2851.48 ms`.
- diagnostic browser timing p95: `responseStart 10860.30 ms`, `domContentLoadedEventEnd 12216.00 ms`, `first-paint 12316.00 ms`, `first-contentful-paint 21452.00 ms`.
- diagnostic frontend paint metrics: DOM node count p95 `1235`, visible button count p95 `46`, CSS rule count p95 `1358`, script resource count p95 `2`, script transfer in in-run release capture `3159638 bytes`.
- HTTP first-response result: PASS as diagnostic, `HTTP_FIRST_RESPONSE_483CD39_RERUN7`, users `1/3/6/9/12`, errors `0`; time-to-first-byte p95 stayed near `1015.64-1045.33 ms`, with 12-user TTFB p95 `1029.31 ms`.
- import timing summary: all `8` target imports passed; slowest target import was `sections.cost_contract` at `2599.57 ms`, followed by the remaining target set; baseline imports all passed and the slowest baseline was `pandas` at `2272.03 ms`.
- superseded RERUN7 note: earlier RERUN7 and RERUN7B tail captures exposed visible first-paint exceptions from the lazy Executive Landing data split (`_OBS_COLUMNS` and `_obs_rows` names). Those name defects were fixed before RERUN7C; RERUN7C is the current release-gate evidence.
- artifact storage: `perf_tests/results/` is intentionally stored outside git; reason: generated Playwright performance artifacts are local run evidence with environment-specific timing and browser metadata.
- result: FAIL for the release gate, because clean scored p95 exceeded `10000 ms`, readiness was below target (`35/100` < `95/100`), one configured load button was skipped, and one Streamlit client 404/browser-error step was recorded.
- release blockers: p95 threshold, p99 tail/readiness, one browser-error step (`Client Error: Download Button source error - 404` after a 404 resource load), one skipped Alert Center `Load Active Alerts` step after the page still showed DBA Control Room load controls, and repeatable stability-tail failure.
- top next fixes: treat the dominant issue as concurrent browser/client first-paint and section title-visible tail, not Snowflake query work; inspect Streamlit client resource loading and the intermittent download-button 404, reduce remaining first-paint DOM/CSS where feasible, and use the stability runner plus in-run tail captures to distinguish app/client regressions from local browser-host capacity.

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
- Reason: Failed on RERUN7C because the clean scored profile regressed to p95 `29766.24 ms`, p99 `32214.09 ms`, readiness `35/100`, one browser-error step, and one skipped Alert Center load button. The RERUN7 stability pass also failed (`0/1/2` pass/watch/fail, median readiness `57/100`, conclusion `unstable_environment_tail`). In-run tail captures showed low server render time but high concurrent browser FCP, while post-run single-user replays did not reproduce the tail. Do not treat this as Snowflake query latency without new credentialed evidence.
- Owner: release operator
- Follow-up: tune concurrent Streamlit/browser first-paint tail and the intermittent client 404/skipped-button path; rerun `python perf_tests/run_12_power_users.py --url http://localhost:8503/ --run-id PERF_12_POWER_USERS_RELEASE_RERUN8 --output-dir perf_tests/results --profile perf_tests/profiles/12_power_users_release_scored.json --tail-diagnostics --tail-capture-threshold-ms 18000` and regenerate the expert review.
