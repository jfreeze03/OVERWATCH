# OVERWATCH Streamlit Deployment Guide

Last updated: June 13, 2026

This guide covers the public Streamlit Community Cloud entry point and the
Snowflake Streamlit-in-Snowflake entry point.

## Deployment Decision

The deployment source of truth is intentionally split by runtime:

| Runtime | Entry point | Manifest | Warehouse / execution |
|---|---|---|---|
| Streamlit in Snowflake | `.overwatch_final/app.py` | `.overwatch_final/snowflake.yml` | `OVERWATCH_WH`, `CALLER` |
| Streamlit Community Cloud | `streamlit_app.py` | `.streamlit/config.toml` | user-provided Snowflake connection |
| Snowflake setup objects | `snowflake/mart_setup/` ordered files (canonical human path; `snowflake/OVERWATCH_MART_SETUP.sql` is the byte-equivalent single-file artifact) | `utils.deployment` schema contract | setup role, mart task warehouses |

Do not deploy Streamlit in Snowflake from `streamlit_app.py`, and do not move
the app runtime back to `COMPUTE_WH`.

## Community Cloud

Use these settings:

- Main file path: `streamlit_app.py`

| Setting | Value |
|---|---|
| Repository | `jfreeze03/OVERWATCH` |
| Branch | `main` |
| Main file path | `streamlit_app.py` |
| Config path | `.streamlit/config.toml` |

Do not commit secrets:

- `.streamlit/secrets.toml`
- `.env`
- `.env.*`
- `*.pem`
- `*.key`
- local credential exports

## Streamlit In Snowflake

Use `.overwatch_final/snowflake.yml`.

Expected values:

| Setting | Value |
|---|---|
| Main file | `app.py` |
| Query warehouse | `OVERWATCH_WH` |
| App package root | `.overwatch_final` |

`OVERWATCH_WH` is the dedicated app runtime warehouse. The current mart task
graph runs on `COMPUTE_WH`.

## Snowflake Setup

Deploy the ordered split under `snowflake/mart_setup/` (the canonical human
deployment path). Run the numbered files in order or use the bundled runner:

```bash
cd snowflake/mart_setup
./run_mart_setup.sh <snowsql-connection-name>
# or: !source snowflake/mart_setup/01_runtime_objects.sql, then 02_..08_ in order
```

`snowflake/OVERWATCH_MART_SETUP.sql` is the byte-equivalent single-file artifact
of those parts (enforced by `tests/test_mart_setup_split.py`) and can be run
directly instead.

The setup creates:

- OVERWATCH app database/schema objects
- `OVERWATCH_WH`
- `OVERWATCH_WH_RM`
- mart facts and views
- owner, alert, action, audit, automation, and external feed tables
- refresh procedures
- scheduled tasks

## Local Validation Before Release

Run from:

```powershell
cd C:\Users\jfree\Desktop\overwatchv3\_deploy_OVERWATCH
```

CI deployment contract:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_deployment_contract
```

This validates the Snowflake manifest, `OVERWATCH_WH`, caller-mode boundary,
Snowflake artifact list, Community Cloud wrapper, `.streamlit/config.toml`,
deployment guide, and CI release rule. If it fails, fix the manifest, docs,
and code contract before deploying.

Focused hot-path guard:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_navigation_integrity.NavigationIntegrityTests.test_app_performance_hot_paths_are_deferred_or_cached
```

Full suite:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Section smoke:

```powershell
.\.venv\Scripts\python.exe .\perf_tests\section_smoke_runner.py --url http://localhost:8501/ --timeout-ms 30000 --initial-wait-ms 1500 --run-id PERF_TEST_SECTION_SMOKE_RELEASE
```

Compile changed Python files when code changed:

```powershell
.\.venv\Scripts\python.exe -m compileall .overwatch_final tests
```

## Browser Sanity Check

After deployment, open the app and confirm:

1. the app starts without import errors
2. topbar filters render
3. DBA Control Room renders quickly
4. Cost & Contract opens without auto-loading heavy detail
5. Workload Operations opens with live status and no visible errors
6. Security Posture opens without source/report errors
7. Change & Drift schema compare dropdowns cascade by selected database
8. Executive Landing can produce copyable summary evidence

## Release Rule

Only commit and push when explicitly instructed. Keep local validation results
with the release notes or final response so the deployment state is clear.
