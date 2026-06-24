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
- Run ID: `PERF_12_POWER_USERS_RELEASE_RERUN6`
- Users: `12`
- Iterations: `3`
- p95: `7446.09 ms`
- p99: `22403.39 ms`
- max: `25286.02 ms`
- errors: `0`
- skipped buttons: `0`
- readiness: `92/100`
- slowest section: `App Shell`
- slowest action: `initial_load`
- live report path: `perf_tests/results/PERF_12_POWER_USERS_RELEASE_RERUN6_live_concurrent.json`
- expert review path: `perf_tests/results/PERF_12_POWER_USERS_RELEASE_RERUN6_expert_review.md`
- import timing path: `perf_tests/results/IMPORT_TIMING_14020F4_RERUN6_FINAL_import_timing.json`
- HTTP first-response path: `perf_tests/results/HTTP_FIRST_RESPONSE_14020F4_RERUN6_FINAL_http_first_response.json`
- initial-load ladder path: `perf_tests/results/PERF_INITIAL_LOAD_LADDER_RERUN6_FINAL_initial_load_ladder.json`
- release stability path: `perf_tests/results/PERF_RELEASE_STABILITY_RERUN6_FINAL_release_stability.json`
- diagnostic profile path: `perf_tests/results/PERF_12_POWER_USERS_DIAGNOSTIC_RERUN6_live_concurrent.json`
- scored profile: `perf_tests/profiles/12_power_users_release_scored.json`
- diagnostic profile: `perf_tests/profiles/12_power_users_diagnostic.json`
- diagnostic samples: `0` in the clean scored release run; tail replays ran after scoring and are excluded from clean release p95/readiness/error scoring.
- readiness penalty: `p99_tail`, `8` points, because p99 `22403.39 ms` exceeded the tail threshold `18000.00 ms` (`fail_p95_ms * 1.8`).
- release scored action p95: `initial_load 25286.02 ms`, `section_nav 5299.06 ms`, `Load Active Alerts 2347.56 ms`, `Refresh Cost 1337.35 ms`.
- release scored section p95: `App Shell 25286.02 ms`, `DBA Control Room 17491.66 ms`, `Security Monitoring 6309.75 ms`, `Cost & Contract 5294.42 ms`, `Workload Operations 4848.63 ms`, `Executive Landing 4367.25 ms`, `Alert Center 4348.94 ms`.
- tail replay result: slowest scored initial-load users replayed single-user with responseStart near `312 ms` and first-contentful-paint near `904-908 ms`; slowest DBA section navigation replayed with responseStart `316.9 ms` and first-contentful-paint `924 ms`. Replay DOM counts were `382` for App Shell and `534` for DBA Control Room, confirming the scored tail is concurrency/client-capacity sensitive rather than a slow single-session render.
- release stability result: diagnostic only, `PERF_RELEASE_STABILITY_RERUN6_FINAL`; `3` clean scored repeats, median p95 `7909.44 ms`, median p99 `21949.79 ms`, median max `25800.37 ms`, median readiness `92/100`, pass/watch/fail count `0/2/1`, errors `0`, skipped buttons `0`.
- diagnostic profile result: `PERF_12_POWER_USERS_DIAGNOSTIC_RERUN6`, p95 `10395.71 ms`, p99 `25644.23 ms`, max `29717.24 ms`, errors `0`, skipped buttons `1`, readiness `81/100`, diagnostic samples `1152`; diagnostic profile is not the release gate.
- diagnostic initial-load breakdown p95: `shell_title_visible 14043.66 ms`, `section_container_visible 11519.28 ms`, `sidebar_visible 11487.95 ms`, `goto_commit 9108.12 ms`, `domcontentloaded 2527.47 ms`, `initial_wait 1216.39 ms`, `idle_wait 919.09 ms`.
- diagnostic section-nav breakdown p95: `DBA Control Room title_visible 13723.90 ms`, `Alert Center title_visible 4441.44 ms`, `Security Monitoring title_visible 3939.62 ms`, `Cost & Contract title_visible 3469.14 ms`, `Executive Landing title_visible 3381.69 ms`, `Workload Operations title_visible 3350.87 ms`.
- diagnostic browser timing p95: `responseStart 9102.60 ms`, `domContentLoadedEventEnd 9394.40 ms`, `first-paint 9484.00 ms`, `first-contentful-paint 23868.00 ms`.
- diagnostic server phase p95: `section_dispatch:render:Alert Center 1436.11 ms`, `shell:total_render_app 1335.26 ms`, `section_dispatch:render:Cost & Contract 1277.46 ms`, `shell:dispatch_section_total 1190.70 ms`, `section_dispatch:render:Workload Operations 563.31 ms`.
- diagnostic frontend paint metrics: DOM node count p95 `1235`, visible button count p95 `46`, CSS rule count p95 `1344`, script resource count p95 `46`, script transfer p95 `5396081 bytes`.
- HTTP first-response result: PASS as diagnostic, `HTTP_FIRST_RESPONSE_14020F4_RERUN6_FINAL`, users `1/3/6/9/12`, errors `0`; time-to-first-byte p95 stayed near `1013.07-1047.90 ms`, with 12-user TTFB p95 `1047.90 ms`.
- initial-load ladder result: diagnostic only, `PERF_INITIAL_LOAD_LADDER_RERUN6_FINAL`; p95 by users was `1: 4124.47 ms`, `3: 4137.12 ms`, `6: 5225.88 ms`, `9: 14497.94 ms`, `12: 20980.97 ms`; 12-user `responseStart` p95 `7913.90 ms`, first contentful paint p95 `19348.00 ms`, and server shell total render p95 `313.75 ms`.
- import timing summary: all `8` target imports passed; slowest target import was `sections.cost_contract` at `2738.81 ms` (`820.78 ms` above the slowest baseline), followed by `sections.alert_center` and `shell` in the target set. Baseline imports all passed; slowest baseline was `layout` at `1918.03 ms`.
- artifact storage: `perf_tests/results/` is intentionally stored outside git; reason: generated Playwright performance artifacts are local run evidence with environment-specific timing and browser metadata.
- result: FAIL for the release gate (runner state `WATCH`), because clean scored readiness remained below target (`92/100` < `95/100`) even though p95 was below `10000 ms`, errors were zero, and skipped buttons were zero.
- release blockers: readiness score remained below target (`92/100` < `95/100`), driven by the long initial-load tail (`max 25286.02 ms`, p99 `22403.39 ms`).
- top next fixes: treat the remaining issue as local browser/frontend capacity and Streamlit client first-paint tail rather than Snowflake query work; continue reducing first-paint/section-nav DOM and CSS pressure, consider multi-host or calibrated ramp diagnostics for local client capacity, and rerun the clean scored profile.

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
