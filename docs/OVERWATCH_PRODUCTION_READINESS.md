# OVERWATCH Production Readiness

Use this checklist before promoting a release. It is intentionally offline-first:
do not run live Snowflake regression unless credentials/auth are available.

## Required Release Gates

1. Green Validate workflow or local equivalent:
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
   - Primary route navigation renders without blank pages.
   - Executive Landing, DBA Control Room, Cost Center, Account Health, Security Posture, Alert Center, Task Management, and Change Drift render their default views.
6. Performance smoke thresholds:
   - Follow `perf_tests/README.md`.
   - Use the section smoke runner only against an available local or staged URL.
   - Treat regressions above documented thresholds as release blockers until explained.
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

## Non-Negotiables

- Do not drop, rename, disable, or rewrite mart objects as part of readiness.
- Do not bypass review-only action queue flows.
- Do not weaken typed/admin guarded DBA behavior.
- Do not mark live Snowflake regression complete unless credentials/auth were available and the run actually happened.
