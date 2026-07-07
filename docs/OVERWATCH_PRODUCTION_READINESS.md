# OVERWATCH Production Readiness

Use this checklist before promoting a release. It is intentionally offline-first:
do not run live Snowflake regression unless credentials/auth are available.

## Required Release Gates

1. Green Validate workflow or local equivalent:
   - GitHub workflow: `.github/workflows/validate.yml`
   - `python -m ruff check .overwatch_final tests`
   - `python -m mypy`
   - `python -m compileall .overwatch_final tests`
   - `python -m unittest tests.test_deployment_contract`
   - `python -m unittest tests.test_cortex_guard`
   - `python -m unittest discover -s tests`
2. Deployment contract green:
   - `tests.test_deployment_contract`
   - `STREAMLIT_CLOUD_DEPLOY.md` reviewed for current entrypoint and manifest expectations.
3. Snowflake Streamlit manifest validated:
   - Confirm `.streamlit/config.toml`, app entrypoint, package manifest, and deployment docs still match the target environment.
4. Mart setup deployed and verified in the target account:
   - Deploy with `snowflake/OVERWATCH_MART_SETUP.sql`.
   - Verify core fact/dimension tables load without changing or dropping mart objects.
   - Treat `snowflake/OVERWATCH_MART_DROP.sql` as a reset/rollback runbook, not a rationalization step.
5. Browser sanity checklist:
   - App loads at the target URL.
   - Primary route navigation renders the six-section model without blank pages:
     - Executive Landing
     - DBA Control Room
     - Alert Center
     - Cost & Contract
     - Workload Operations
     - Security Monitoring
   - Primary route labels match `route_registry.PRIMARY_SECTION_TITLES`.
   - Compatibility/deep-link routes normalize to current workflow locations:
     - Executive Briefing -> Executive Landing workflow
     - Cost Intelligence -> Cost & Contract workflow
     - Task Management -> Workload Operations workflow
     - Security & Access -> Security Monitoring workflow
     - Alert History -> Alert Center workflow
6. Performance smoke thresholds:
   - Follow `perf_tests/README.md`.
   - Use the section smoke runner only against an available local or staged URL.
   - Treat regressions above documented thresholds as release blockers until explained.
   - For performance-sensitive releases, run the 12-heavy-power-user benchmark in `perf_tests/profiles/12_power_users.json`.
   - The 12-user benchmark must not click mutation controls, including grant, save, queue, email send, retry, suspend/resume, task execute, or admin mutation controls.
   - Attach the deterministic expert review from `perf_tests/power_user_review.py`, or explicitly defer the benchmark with a reason.
7. Action queue, typed confirmation, and admin guard smoke:
   - Action queue previews stay review-only.
   - Typed confirmations still require exact operator text.
   - `admin_button_disabled()` guarded actions remain disabled for unauthorized users.
8. Secrets check:
   - No credentials, tokens, private keys, or Snowflake passwords in git diff, logs, screenshots, release notes, or Streamlit config.
9. Rollback/reset runbook reference:
   - Keep release notes linked to `STREAMLIT_CLOUD_DEPLOY.md`, `snowflake/OVERWATCH_MART_SETUP.sql`, and `snowflake/OVERWATCH_MART_DROP.sql`.
   - Use reset scripts only for intentional rollback/rebuild operations.
10. Release notes:
    - Include commit SHA, validation command results, mart deployment status, browser/performance smoke status, and any intentionally deferred live Snowflake regression.

## Release Manifest

The current release candidate is declared in `docs/OVERWATCH_RELEASE_MANIFEST.md`.
Release evidence must match the release manifest commit SHA. Historical evidence
files under `docs/releases/` are allowed, but they cannot be used as current
release evidence unless their commit SHA matches the manifest.
Follow `docs/OVERWATCH_RELEASE_PROCESS.md` when choosing a release candidate,
filling evidence, and tagging only after the manifest is release-ready.

## Non-Negotiables

- Do not drop, rename, disable, or rewrite mart objects as part of readiness.
- Do not bypass review-only action queue flows.
- Do not weaken typed/admin guarded DBA behavior.
- Do not mark live Snowflake regression complete unless credentials/auth were available and the run actually happened.
