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
- 12 Power User Performance: FAIL, `PERF_12_POWER_USERS_RELEASE_RERUN2`, p95 `26196.91 ms`, p99 `27696.06 ms`, errors `0`, skipped buttons `0`, readiness `57/100`; expert review `perf_tests/results/PERF_12_POWER_USERS_RELEASE_RERUN2_expert_review.md`
- Live Snowflake regression: PASS from prior credentialed evidence in `docs/OVERWATCH_SNOWFLAKE_REGRESSION_RESULTS.md`; not rerun for `24cd05e` because the latest credentialed PASS evidence remains recorded and this pass only promoted the manifest/evidence freshness commit after local validation and section smoke were rerun
- Secrets check: PASS, no tracked literal credentials added to release manifest or evidence
- Deferred items: Reason: new live Snowflake regression was not rerun for `24cd05e`; rerun only when a fresh credentialed release gate is required. Reason: the 12-heavy-power-user benchmark still fails for `24cd05e` because rerun p95 `26196.91 ms` exceeds the `10000 ms` release threshold and readiness is `57/100`; diagnostics point to App Shell `initial_load:app_ready` p95 `23824.96 ms` and `initial_load:goto_domcontentloaded` p95 `19439.42 ms`, so tune cold Streamlit first render/server response before high-traffic rollout.
