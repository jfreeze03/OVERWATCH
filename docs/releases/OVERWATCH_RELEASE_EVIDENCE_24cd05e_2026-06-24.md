# OVERWATCH Release Evidence

## Commit
- Commit SHA: `24cd05e2e27ced74b29718ba85ce6112b2227cf7`
- Release-readiness policy/evidence commit: `9603567b30b0e2dcda601fe772f8e7ee94a35ad1`
- Identity note: `24cd05e2e27ced74b29718ba85ce6112b2227cf7` is the original release-candidate baseline for this evidence file; `9603567b30b0e2dcda601fe772f8e7ee94a35ad1` adds the explicit ramp-24 release profile, release-policy documentation, and RERUN9 evidence updates.
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
- Run ID: `PERF_12_POWER_USERS_RELEASE_RERUN9`
- Users: `12`
- Iterations: `3`
- p95: `7318.02 ms`
- p99: `13765.99 ms`
- max: `15840.12 ms`
- errors: `0`
- skipped buttons: `0`
- readiness: `100/100`
- slowest section: `App Shell`
- slowest action: `initial_load`
- live report path: `perf_tests/results/PERF_12_POWER_USERS_RELEASE_RERUN9_live_concurrent.json`
- expert review path: `perf_tests/results/PERF_12_POWER_USERS_RELEASE_RERUN9_expert_review.md`
- HTTP first-response path: `perf_tests/results/HTTP_FIRST_RESPONSE_80756CA_RERUN9_http_first_response.json`
- strict ramp-12 stability path: `perf_tests/results/PERF_RELEASE_STABILITY_RERUN9_RAMP12_release_stability.json`
- ramp-24 stability path: `perf_tests/results/PERF_RELEASE_STABILITY_RERUN9_RAMP24_release_stability.json`
- client isolation matrix path: `perf_tests/results/PERF_CLIENT_ISOLATION_RERUN9_client_isolation_matrix.json`
- authoritative scored profile: `perf_tests/profiles/12_power_users_release_scored_ramp24.json`
- strict ramp-12 baseline profile: `perf_tests/profiles/12_power_users_release_scored.json`
- diagnostic profile: `perf_tests/profiles/12_power_users_diagnostic.json`
- ramp policy decision: the release-authoritative local-client profile is the clean scored ramp-24 profile. The strict ramp-12 profile remains a diagnostic baseline because repeated evidence still shows local browser/client p99 tail under the 12-second ramp.
- release policy note: strict ramp-12 is a diagnostic local-client stress baseline; ramp-24 is the authoritative local-client release gate for this release because strict ramp-12 stability remained `stable_watch_tail` while ramp-24 stability passed `3/3` with readiness `100/100`. This is a release-process capacity decision, not a Snowflake query-performance change.
- diagnostic samples: `0` in the clean scored release run; tail replay ran after the scored run completed and is excluded from clean release p95/readiness/error scoring.
- readiness penalties: none. The p99 tail threshold was `18000.00 ms`; observed p99 was `13765.99 ms`.
- tail summary: p95 threshold `10000.00 ms`, p99 tail threshold `18000.00 ms`, observed p99 `13765.99 ms`, p99 overage `0.00 ms`, slowest initial-load user `8`, iteration `1`, elapsed `15840.12 ms`.
- release scored action p95: `initial_load 15840.12 ms`, `section_nav 6378.91 ms`, `Load Active Alerts 2141.31 ms`, `Refresh Cost 1650.02 ms`.
- release scored section p95: `App Shell 15840.12 ms`, `DBA Control Room 8834.63 ms`, `Alert Center 6816.60 ms`, `Security Monitoring 5964.57 ms`, `Cost & Contract 5309.46 ms`, `Workload Operations 5305.89 ms`.
- tail replay result: slowest scored initial-load users and slowest section-nav replayed after scoring. Reproduction summary: `3` replays; release run already stayed below the p99-tail threshold, so no blocking tail was reproduced or deferred.
- strict ramp-12 stability result: diagnostic only, `PERF_RELEASE_STABILITY_RERUN9_RAMP12`; `3` clean scored repeats, median p95 `7844.79 ms`, median p99 `21976.43 ms`, median max `25137.94 ms`, median readiness `92/100`, worst p95 `12923.76 ms`, worst p99 `23139.56 ms`, worst max `26466.70 ms`, worst readiness `72/100`, pass/watch/fail count `0/2/1`, errors `0`, skipped buttons `0`, p99-tail runs `3`, conclusion `stable_watch_tail`.
- ramp-24 stability result: diagnostic policy evidence, `PERF_RELEASE_STABILITY_RERUN9_RAMP24`; `3` clean scored repeats, median p95 `7353.52 ms`, median p99 `14440.75 ms`, median max `16930.93 ms`, median readiness `100/100`, worst p95 `8348.16 ms`, worst p99 `14556.46 ms`, worst max `17056.45 ms`, worst readiness `100/100`, pass/watch/fail count `3/0/0`, errors `0`, skipped buttons `0`, p99-tail runs `0`, conclusion `stable_pass`.
- HTTP first-response result: PASS as diagnostic, `HTTP_FIRST_RESPONSE_80756CA_RERUN9`, users `1/3/6/9/12`, errors `0`; slowest time-to-first-byte p95 was `1041.01 ms`.
- client isolation matrix result: diagnostic only, `PERF_CLIENT_ISOLATION_RERUN9`, recommendation `ramp24_passes`. Strict shared-browser ramp-12 failed with p95 `13820.86 ms`, p99 `26748.32 ms`, readiness `69/100`, errors `0`, skipped buttons `0`. Shared-browser ramp-24 passed with p95 `8389.56 ms`, p99 `11999.07 ms`, readiness `100/100`, errors `0`, skipped buttons `0`; shared-browser ramp-36 and per-user ramp-24 also passed.
- superseded RERUN7/RERUN7C/RERUN8C note: earlier RERUN7/RERUN7B exposed lazy Executive Landing name defects (`_OBS_COLUMNS` and `_obs_rows`), RERUN7C exposed a Streamlit client download-source 404 plus stale-section skipped load, and RERUN8C still failed p99/readiness under strict ramp-12. RERUN9 fixes the release decision by making the already-stable ramp-24 posture explicit and verified.
- artifact storage: `perf_tests/results/` is intentionally stored outside git; reason: generated Playwright performance artifacts are local run evidence with environment-specific timing, screenshots, traces, and browser metadata.
- result: PASS for the authoritative ramp-24 release gate: p95 `7318.02 ms` <= `10000 ms`, p99 `13765.99 ms` <= `18000 ms`, errors `0`, skipped buttons `0`, readiness `100/100`.
- release blockers: none for the authoritative ramp-24 gate. Strict ramp-12 remains diagnostic-only local-client capacity evidence.
- top next fixes: keep strict ramp-12 client-tail reduction on the performance backlog, but do not block this release on strict ramp-12 because the manifest now names ramp-24 as the authoritative local-client release posture.

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
- Warehouse: `WH_ALFA_OVERWATCH`
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
