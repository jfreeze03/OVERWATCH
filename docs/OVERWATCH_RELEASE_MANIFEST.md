# OVERWATCH Release Manifest

## Release Candidate
- Commit SHA: `24cd05e2e27ced74b29718ba85ce6112b2227cf7`
- Evidence file: `docs/releases/OVERWATCH_RELEASE_EVIDENCE_24cd05e_2026-06-24.md`
- Status: `candidate`

## Required Evidence
- Production readiness: `docs/OVERWATCH_PRODUCTION_READINESS.md`
- Release evidence: `docs/releases/OVERWATCH_RELEASE_EVIDENCE_24cd05e_2026-06-24.md`
- Snowflake regression: `docs/OVERWATCH_SNOWFLAKE_REGRESSION_RESULTS.md`
- Deployment guide: `STREAMLIT_CLOUD_DEPLOY.md`
- Mart setup: `snowflake/OVERWATCH_MART_SETUP.sql`
- Mart reset/rollback: `snowflake/OVERWATCH_MART_DROP.sql`

## Gate Status
- Validate workflow/local equivalent: PASS, local equivalent run for `24cd05e2e27ced74b29718ba85ce6112b2227cf7`
- Deployment contract: PASS, `python -m unittest tests.test_deployment_contract`
- Browser/section smoke: PASS, `PERF_TEST_SECTION_SMOKE_RELEASE_24cd05e`
- Performance smoke: PASS, section smoke readiness `100/100`, p95 `2388.01 ms`
- 12 Power User Performance: FAIL, `PERF_12_POWER_USERS_RELEASE_RERUN7C`, p95 `29766.24 ms`, p99 `32214.09 ms`, max `33570.63 ms`, errors `1`, skipped buttons `1`, readiness `35/100`; expert review `perf_tests/results/PERF_12_POWER_USERS_RELEASE_RERUN7C_expert_review.md`
- Live Snowflake regression: PASS from prior credentialed evidence in `docs/OVERWATCH_SNOWFLAKE_REGRESSION_RESULTS.md`; not rerun for `24cd05e` because the latest credentialed PASS evidence remains recorded and this pass only promoted the manifest/evidence freshness commit after local validation and section smoke were rerun
- Secrets check: PASS, no tracked literal credentials added to release manifest or evidence
- Deferred items: Reason: new live Snowflake regression was not rerun for `24cd05e`; rerun only when a fresh credentialed release gate is required. Reason: the 12-heavy-power-user benchmark still fails for `24cd05e` because RERUN7C clean scored p95 is `29766.24 ms`, p99 is `32214.09 ms`, readiness is `35/100`, one browser-error step was recorded, and one Alert Center `Load Active Alerts` step was skipped. Diagnostics still point primarily to concurrent browser/frontend capacity and Streamlit client first-paint/title-visible tail rather than Snowflake query work: HTTP-only 12-user TTFB p95 was `1029.31 ms`, in-run tail captures showed low server render phases but first-contentful-paint as high as `31924.00 ms`, and post-run single-user tail replays did not reproduce the tail. Release stability also remained blocked with median readiness `57/100`, p99-tail runs `3`, and conclusion `unstable_environment_tail`.
