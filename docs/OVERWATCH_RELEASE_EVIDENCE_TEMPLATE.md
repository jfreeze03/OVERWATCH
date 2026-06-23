# OVERWATCH Release Evidence

## Commit
- Commit SHA:
- Branch:
- Release date:
- Operator:

## Validation Commands
- `python -m ruff check .overwatch_final tests`:
- `python -m mypy`:
- `python -m compileall .overwatch_final tests`:
- `python -m unittest tests.test_deployment_contract`:
- `python -m unittest tests.test_cortex_guard`:
- `python -m unittest discover -s tests`:

## Deployment Contract
- Streamlit in Snowflake entrypoint:
- Manifest:
- Warehouse:
- Execute-as boundary:
- Result:

## Mart Setup
- Setup script used:
- Target account/environment:
- Core facts verified:
- Mart load status:
- Notes:

## Browser Sanity
- Executive Landing:
- DBA Control Room:
- Alert Center:
- Cost & Contract:
- Workload Operations:
- Security Monitoring:
- Legacy/deep-link workflow checks:

## Performance Smoke
- `perf_tests/README.md` threshold review:
- Section smoke result:
- HTTP/live browser p95:
- Failed dashboard queries:
- Readiness score:

## Guarded Operations
- Action queue review-only smoke:
- Typed confirmation smoke:
- `admin_button_disabled()` unauthorized-user smoke:
- Notes:

## Live Snowflake Regression
- Run status:
- Credentials/auth available:
- Result:
- If not run, reason:
- Do not claim live Snowflake regression passed unless it was actually run with credentials/auth available.

## Secrets Check
- Git diff/logs/screenshots/release notes checked:
- Result:

## Rollback / Reset
- Rollback reference:
- `snowflake/OVERWATCH_MART_DROP.sql` reset posture acknowledged:
- Notes:

## Deferred Items
- Item:
- Reason:
- Owner:
- Follow-up:

References:
- Deployment guide: `STREAMLIT_CLOUD_DEPLOY.md`
- Mart setup: `snowflake/OVERWATCH_MART_SETUP.sql`
- Reset/rollback runbook: `snowflake/OVERWATCH_MART_DROP.sql`
