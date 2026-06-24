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
- `python -m unittest discover -s tests`: PASS, 1082 tests, 1 skipped

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
- Run ID: `PERF_12_POWER_USERS_RELEASE_RERUN8C`
- Users: `12`
- Iterations: `3`
- p95: `8784.90 ms`
- p99: `20393.32 ms`
- max: `23936.24 ms`
- errors: `0`
- skipped buttons: `0`
- readiness: `92/100`
- slowest section: `App Shell`
- slowest action: `initial_load`
- live report path: `perf_tests/results/PERF_12_POWER_USERS_RELEASE_RERUN8C_live_concurrent.json`
- expert review path: `perf_tests/results/PERF_12_POWER_USERS_RELEASE_RERUN8C_expert_review.md`
- import timing path: `perf_tests/results/IMPORT_TIMING_7A704A3_RERUN8_import_timing.json`
- HTTP first-response path: `perf_tests/results/HTTP_FIRST_RESPONSE_7A704A3_RERUN8_http_first_response.json`
- release stability path: `perf_tests/results/PERF_RELEASE_STABILITY_RERUN8C_release_stability.json`
- diagnostic profile path: `perf_tests/results/PERF_12_POWER_USERS_DIAGNOSTIC_RERUN8C_live_concurrent.json`
- client isolation matrix path: `perf_tests/results/PERF_CLIENT_ISOLATION_RERUN8C_client_isolation_matrix.json`
- scored profile: `perf_tests/profiles/12_power_users_release_scored.json`
- diagnostic profile: `perf_tests/profiles/12_power_users_diagnostic.json`
- diagnostic samples: `0` in the clean scored release run; in-run tail captures and tail replays ran after each scored stopwatch stopped or after the scored run completed, and are excluded from clean release p95/readiness/error scoring.
- readiness penalties: `p99_tail`, `8` points, because p99 `20393.32 ms` exceeded the tail threshold `18000.00 ms` (`fail_p95_ms * 1.8`).
- tail summary: p95 threshold `10000.00 ms`, p99 tail threshold `18000.00 ms`, observed p99 `20393.32 ms`, p99 overage `2393.32 ms`, slowest initial-load user `10`, iteration `1`, elapsed `23936.24 ms`.
- release scored action p95: `initial_load 23936.24 ms`, `section_nav 7904.30 ms`, `Load Active Alerts 3836.23 ms`, `Refresh Cost 1796.42 ms`.
- release scored section p95: `App Shell 23936.24 ms`, `DBA Control Room 14934.72 ms`, `Alert Center 8793.86 ms`, `Workload Operations 5305.16 ms`, `Cost & Contract 4929.06 ms`, `Security Monitoring 4791.34 ms`.
- in-run tail capture result: `7` initial-load tail captures were collected after scored timing stopped. The slowest capture was user `10`, elapsed `23936.24 ms`, browser `responseStart 10816.90 ms`, `first-contentful-paint 22204.00 ms`, DOM node count `591`, script transfer `3159638 bytes`, and zero failed resource or console-error events. Server trace remained small: `shell:total_render_app 84.43 ms`, `shell:dispatch_section_total 60.31 ms`, `section_dispatch:render:Executive Landing 58.85 ms`, and app-entry pre-render `1.86 ms`.
- tail replay result: slowest scored initial-load users and slowest section-nav replayed single-user with first-contentful-paint below `1s`; reproduction summary: `3` replays, `0` reproduced. This keeps the remaining blocker in concurrent browser/client timing rather than slow single-session app render or Snowflake query latency.
- release stability result: diagnostic only, `PERF_RELEASE_STABILITY_RERUN8C`; `3` clean scored repeats, median p95 `7863.91 ms`, median p99 `21757.57 ms`, median max `25350.26 ms`, median readiness `92/100`, worst p95 `12415.63 ms`, worst p99 `22608.65 ms`, worst max `26091.37 ms`, worst readiness `74/100`, pass/watch/fail count `0/2/1`, errors `0`, skipped buttons `0`, p99-tail runs `3`, conclusion `stable_watch_tail`.
- diagnostic profile result: `PERF_12_POWER_USERS_DIAGNOSTIC_RERUN8C`, p95 `7709.94 ms`, p99 `21127.18 ms`, max `23820.49 ms`, errors `0`, skipped buttons `0`, readiness `92/100`; diagnostic profile is not the release gate.
- diagnostic browser timing p95: `responseStart 11112.90 ms`, `domContentLoadedEventEnd 13738.10 ms`, `first-paint 13872.00 ms`, `first-contentful-paint 20872.00 ms`.
- diagnostic frontend paint metrics: DOM node count p95 `1209`, visible button count p95 `46`, CSS rule count p95 `1348`, script resource count in in-run capture `22`, script transfer in in-run release capture `3159638 bytes`.
- HTTP first-response result: PASS as diagnostic, `HTTP_FIRST_RESPONSE_7A704A3_RERUN8`, users `1/3/6/9/12`, errors `0`; time-to-first-byte p95 stayed near `1020.33-1045.85 ms`, with 12-user TTFB p95 `1034.22 ms`.
- import timing summary: all `8` target imports passed; slowest target import was `shell` at `2940.38 ms`; baseline imports all passed and the slowest baseline was `layout` at `2658.39 ms`.
- client isolation matrix result: diagnostic only, `PERF_CLIENT_ISOLATION_RERUN8C`; current shared-browser ramp-12 profile stayed WATCH with p95 `7293.29 ms`, p99 `23818.47 ms`, readiness `92/100`, errors `0`, skipped buttons `0`; shared-browser ramp-24 passed with p95 `8420.29 ms`, p99 `15498.33 ms`, readiness `100/100`; shared-browser ramp-36 passed with p95 `6316.27 ms`, p99 `8524.01 ms`, readiness `100/100`; per-user ramp-24 also passed with p95 `8648.72 ms`, p99 `13671.00 ms`, readiness `100/100`.
- superseded RERUN7/RERUN7C note: earlier RERUN7/RERUN7B exposed lazy Executive Landing name defects (`_OBS_COLUMNS` and `_obs_rows`), and RERUN7C exposed a Streamlit client download-source 404 plus stale-section skipped load. RERUN8C fixed the client 404 and skipped-button blockers; the remaining blocker is p99/readiness tail under the current 12-second ramp.
- artifact storage: `perf_tests/results/` is intentionally stored outside git; reason: generated Playwright performance artifacts are local run evidence with environment-specific timing, screenshots, traces, and browser metadata.
- result: WATCH/FAIL for the release gate, because p95 passed (`8784.90 ms` <= `10000 ms`) and errors/skips were zero, but readiness remained below target (`92/100` < `95/100`) due to the p99 tail.
- release blockers: readiness score below `95/100` from p99 tail; release stability still concluded `stable_watch_tail` under the clean scored release profile.
- top next fixes: treat the remaining issue as concurrent browser/client first-paint tail under the current release ramp, not Snowflake query work; use the client-isolation matrix to decide whether release policy should accept a longer ramp, and continue reducing client first-paint resource pressure if the 12-second ramp must remain mandatory.

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
- Reason: Still blocked on RERUN8C because the clean scored profile passed p95 with errors `0` and skipped buttons `0`, but p99 `20393.32 ms` kept readiness at `92/100`. The corrected RERUN8C stability pass concluded `stable_watch_tail` and the client isolation matrix showed longer diagnostic ramps (`24s`/`36s`) passing, pointing to concurrent browser/client first-paint tail under the current release ramp. Do not treat this as Snowflake query latency without new credentialed evidence.
- Owner: release operator
- Follow-up: decide whether the release process accepts a longer ramp policy or continue reducing concurrent Streamlit/browser first-paint tail; rerun `python perf_tests/run_12_power_users.py --url http://localhost:8503/ --run-id PERF_12_POWER_USERS_RELEASE_RERUN9 --output-dir perf_tests/results --profile perf_tests/profiles/12_power_users_release_scored.json --tail-diagnostics --tail-capture-threshold-ms 18000` and regenerate the expert review.
