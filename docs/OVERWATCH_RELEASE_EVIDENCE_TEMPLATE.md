# OVERWATCH Release Evidence Template

## Commit SHA

- Release commit:
- Branch:

## Validation Commands And Results

- `python -m ruff check .overwatch_final tests`:
- `python -m mypy`:
- `python -m compileall .overwatch_final tests`:
- `python -m unittest tests.test_deployment_contract`:
- `python -m unittest tests.test_cortex_guard`:
- `python -m unittest discover -s tests`:

## Deployment Contract Result

- `tests.test_deployment_contract` result:
- `STREAMLIT_CLOUD_DEPLOY.md` reviewed:

## Mart Setup Status

- `snowflake/OVERWATCH_MART_SETUP.sql` deployed:
- Target account/environment:
- Core facts verified:

## Browser Sanity Result

- Six primary routes rendered:
- Compatibility/deep-link routes checked:
- Notes/screenshots:

## Performance Smoke Result

- `perf_tests/README.md` thresholds reviewed:
- Section smoke command/result:
- Regressions or exceptions:

## Action Queue/Admin Guard Smoke Result

- Review-only action queue previews:
- Typed confirmation exact-text checks:
- `admin_button_disabled()` unauthorized-action checks:

## Live Snowflake Regression Result

- Result:
- If not run: `not run, credentials unavailable`
- Do not claim live Snowflake regression passed unless it was actually run with credentials/auth available.

## Known Deferred Items

- Item:
- Reason:
- Owner/follow-up:

## Rollback/Reset Reference

- Deployment guide: `STREAMLIT_CLOUD_DEPLOY.md`
- Mart setup: `snowflake/OVERWATCH_MART_SETUP.sql`
- Reset/rollback runbook: `snowflake/OVERWATCH_MART_DROP.sql`
