# OVERWATCH Release Manifest

## Release Candidate
- Commit SHA: `cda40dda9c4ffd8da731e3dde9ba6d9e6608f06a`
- Evidence file: `docs/releases/OVERWATCH_RELEASE_EVIDENCE_cda40dd_2026-06-23.md`
- Status: `release-ready`

## Required Evidence
- Production readiness: `docs/OVERWATCH_PRODUCTION_READINESS.md`
- Release evidence: `docs/releases/OVERWATCH_RELEASE_EVIDENCE_cda40dd_2026-06-23.md`
- Snowflake regression: `docs/OVERWATCH_SNOWFLAKE_REGRESSION_RESULTS.md`
- Deployment guide: `STREAMLIT_CLOUD_DEPLOY.md`
- Mart setup: `snowflake/OVERWATCH_MART_SETUP.sql`
- Mart reset/rollback: `snowflake/OVERWATCH_MART_DROP.sql`

## Gate Status
- Validate workflow/local equivalent: PASS, local equivalent run for `cda40dda9c4ffd8da731e3dde9ba6d9e6608f06a`
- Deployment contract: PASS, `python -m unittest tests.test_deployment_contract`
- Browser/section smoke: PASS, `PERF_TEST_SECTION_SMOKE_RELEASE_cda40dd`
- Performance smoke: PASS, section smoke readiness `100/100`, p95 `258.2 ms`
- Live Snowflake regression: PASS from prior credentialed evidence in `docs/OVERWATCH_SNOWFLAKE_REGRESSION_RESULTS.md`; not rerun for `cda40dd` because the prior run already recorded credentialed PASS evidence and this pass only refreshed manifest/evidence guardrails
- Secrets check: PASS, no tracked literal credentials added to release manifest or evidence
- Deferred items: New live Snowflake regression was not rerun for `cda40dd`; rerun only when a fresh credentialed release gate is required
