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
- 12 Power User Performance: FAIL, `PERF_12_POWER_USERS_RELEASE_RERUN6`, p95 `7446.09 ms`, p99 `22403.39 ms`, max `25286.02 ms`, errors `0`, skipped buttons `0`, readiness `92/100`; expert review `perf_tests/results/PERF_12_POWER_USERS_RELEASE_RERUN6_expert_review.md`
- Live Snowflake regression: PASS from prior credentialed evidence in `docs/OVERWATCH_SNOWFLAKE_REGRESSION_RESULTS.md`; not rerun for `24cd05e` because the latest credentialed PASS evidence remains recorded and this pass only promoted the manifest/evidence freshness commit after local validation and section smoke were rerun
- Secrets check: PASS, no tracked literal credentials added to release manifest or evidence
- Deferred items: Reason: new live Snowflake regression was not rerun for `24cd05e`; rerun only when a fresh credentialed release gate is required. Reason: the 12-heavy-power-user benchmark still fails for `24cd05e` because RERUN6 clean scored readiness is `92/100`, below the `95/100` release target, even though p95 improved to `7446.09 ms`, browser-step errors were `0`, and skipped buttons were `0`. Diagnostics point to browser/frontend capacity and Streamlit client first-paint tail rather than Snowflake query work: HTTP-only 12-user TTFB p95 was `1047.90 ms`, tail replays of the slowest users had first-contentful-paint near `904-924 ms`, but the scored p99 remained `22403.39 ms` and triggered the `p99_tail` readiness penalty.
