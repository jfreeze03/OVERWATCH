# OVERWATCH Streamlit Deployment Guide

Last updated: June 13, 2026

This guide covers the public Streamlit Community Cloud entry point and the
Snowflake Streamlit-in-Snowflake entry point.

## Deployment Decision

The deployment source of truth is intentionally split by runtime:

| Runtime | Entry point | Manifest | Warehouse / execution |
|---|---|---|---|
| Streamlit in Snowflake, Snowsight/Git deploy | mapped `app.py` from `.overwatch_final/app.py` | `snowflake.yml` | `SYSTEM_COMPUTE_POOL_CPU`, `WH_ALFA_OVERWATCH`, `CALLER` |
| Streamlit in Snowflake, package-root CLI deploy | `.overwatch_final/app.py` | `.overwatch_final/snowflake.yml` | `WH_ALFA_OVERWATCH`, `CALLER` |
| Streamlit Community Cloud | `streamlit_app.py` | `.streamlit/config.toml` | user-provided Snowflake connection |
| Snowflake setup objects | `snowflake/mart_setup/` ordered files (canonical human path; `snowflake/OVERWATCH_MART_SETUP.sql` is the byte-equivalent single-file artifact) | `utils.deployment` schema contract | setup role, mart task warehouses |

Do not deploy Streamlit in Snowflake from `streamlit_app.py`, and do not move
the app runtime back to `WH_ALFA_OVERWATCH`.

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

Use the root `snowflake.yml` for Snowsight/Git deploys. It maps
`.overwatch_final/app.py` to deploy-root `app.py` and pins `main_file: app.py`,
which avoids Snowsight emitting `CREATE STREAMLIT` without `MAIN_FILE`.

Use `.overwatch_final/snowflake.yml` only when running `snow streamlit deploy`
from inside the `.overwatch_final` package directory.

Expected values:

| Setting | Value |
|---|---|
| Project definition | `definition_version: 2` |
| Main file | `app.py` |
| Snowsight compute pool | `SYSTEM_COMPUTE_POOL_CPU` |
| Query warehouse | `WH_ALFA_OVERWATCH` |
| Snowsight manifest | `snowflake.yml` |
| Package-root CLI manifest | `.overwatch_final/snowflake.yml` |
| App package source | `.overwatch_final` |

`WH_ALFA_OVERWATCH` is the approved current app runtime warehouse until a dedicated
OVERWATCH warehouse is approved. The current mart task graph also runs on
`WH_ALFA_OVERWATCH`.

If Snowsight reports `Missing MAIN_FILE`, use the root `snowflake.yml` in the
Deploy app dialog or recreate the Streamlit object from the repository root.
The root manifest is the Snowsight source of truth for `MAIN_FILE`, package
artifact mapping, compute pool, warehouse, and caller-rights execution.

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
- `WH_ALFA_OVERWATCH`
- `WH_ALFA_OVERWATCH_RM`
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

This validates the Snowflake manifest, `WH_ALFA_OVERWATCH`, caller-mode boundary,
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
