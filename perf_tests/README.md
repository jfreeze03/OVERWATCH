# OVERWATCH Performance Test Framework

This package validates whether the OVERWATCH Streamlit dashboard can handle
load without creating surprise Snowflake cost.

## Modes

| Mode | Purpose | Cost posture |
|---|---|---|
| `metadata` | Simulate a 5 TB account through metadata-scale tables and bounded synthetic events. | Safe default. Does not physically materialize 5 TB. |
| `medium` | Increase generated row counts for query/task/procedure pressure. | Requires DBA approval and row caps. |
| `full_5tb` | Physical 5 TB CTAS pattern for a real storage/scan stress test. | Blocked by default. Requires FinOps/DBA approval and explicit script edits. |

## Files

| File | Purpose |
|---|---|
| `sql/01_perf_test_setup.sql` | Creates `PERF_TEST_*` control, run, result, risk, and guardrail objects. |
| `sql/02_generate_synthetic_light_medium.sql` | Creates synthetic query history, warehouse metering, task, procedure, user, and 5 TB metadata simulation objects. |
| `sql/03_generate_full_5tb_physical_BLOCKED_BY_DEFAULT.sql` | Contains the physical 5 TB pattern, commented and blocked by default. |
| `sql/04_benchmark_report.sql` | Creates report views for app usage, Snowflake query behavior, cost estimate, and readiness gates. |
| `sql/99_cleanup_perf_test.sql` | Drops only `PERF_TEST_*` objects. |
| `perf_runner.py` | Local HTTP concurrency runner and Markdown/JSON report generator. |
| `section_smoke_runner.py` | Optional browser runner that clicks every primary section and reports visible section switch time. |
| `live_concurrent_runner.py` | Concurrent browser runner that exercises Streamlit sessions, section navigation, and safe live-data load buttons. |
| `run_snowflake_safe_suite.py` | Env-driven Snowflake runner for the guarded metadata-scale SQL suite. It never runs the physical 5 TB script. |

## Safe Test Sequence

1. Start OVERWATCH locally or open the Snowflake Streamlit app.
2. In the app settings, enable query logging and detailed Snowflake query tags when measuring Snowflake-side cost.
   Enable section timing only for benchmark windows; it writes one lightweight usage row per completed section render.
3. Optional local instrumentation:

```powershell
$env:OVERWATCH_PERF_RUN_ID="PERF_TEST_LOCAL_001"
```

4. Run the local HTTP load test:

```powershell
.\.venv\Scripts\python.exe .\perf_tests\perf_runner.py --url http://localhost:8501/ --users 10 --iterations 5
```

5. Optional: run the browser section smoke test to catch slow navigation paths:

```powershell
.\.venv\Scripts\python.exe .\perf_tests\section_smoke_runner.py --url http://localhost:8501/
```

6. Optional live-data stress test with real concurrent browser users:

```powershell
# Calibration run.
.\.venv\Scripts\python.exe .\perf_tests\live_concurrent_runner.py --url http://localhost:8501/ --users 5 --iterations 1

# Larger run after calibration is clean.
.\.venv\Scripts\python.exe .\perf_tests\live_concurrent_runner.py --url http://localhost:8501/ --users 20 --iterations 1 --ramp-seconds 10
```

The live concurrent runner clicks only safe read/load actions by default:

- Alert Center: `Load Issue Inbox`
- Cost & Contract: `Refresh Cost`

The default profile intentionally avoids deep workflow buttons that may be
behind a selected subview or collapsed investigation path, such as Account
Health refresh, Warehouse Capacity Brief, or Change & Drift Brief. Use targeted
section smoke tests for those paths so a broad concurrency run does not report
stale skipped controls.

It does not click grant, save, queue, email-send, retry, suspend/resume, or
warehouse setting mutation controls. Use `--no-load-buttons` for navigation-only
browser concurrency. By default, configured load buttons that are not visible in
the current default view are reported as skipped instead of failed; use
`--missing-load-button fail` when validating that a specific button must remain
present.

If Playwright is not installed in the local test environment:

```powershell
.\.venv\Scripts\python.exe -m pip install playwright
.\.venv\Scripts\python.exe -m playwright install chromium
```

If browser tooling cannot be installed, keep using `perf_runner.py` and rely on
`PERF_TEST_APP_USAGE_REPORT_V` for section timing.

7. In Snowflake, run:

```sql
-- Safe setup.
@perf_tests/sql/01_perf_test_setup.sql;

-- Safe default data simulation.
@perf_tests/sql/02_generate_synthetic_light_medium.sql;

-- Benchmark report views.
@perf_tests/sql/04_benchmark_report.sql;
```

8. Review:

```sql
SELECT * FROM PERF_TEST_SCALE_SUMMARY_V;
SELECT * FROM PERF_TEST_EXPENSIVE_QUERY_CANDIDATES_V LIMIT 50;
SELECT * FROM PERF_TEST_APP_USAGE_REPORT_V ORDER BY P95_DURATION_MS DESC;
SELECT * FROM PERF_TEST_SNOWFLAKE_QUERY_REPORT_V ORDER BY P95_ELAPSED_SEC DESC;
SELECT * FROM PERF_TEST_COST_ESTIMATE_V ORDER BY SHARED_WAREHOUSE_CREDITS DESC;
SELECT * FROM PERF_TEST_PRODUCTION_READINESS_V;
```

Alternative local runner, when Snowflake connector environment variables are available:

```powershell
$env:SNOWFLAKE_ACCOUNT="..."
$env:SNOWFLAKE_USER="..."
$env:SNOWFLAKE_PASSWORD="..."
$env:SNOWFLAKE_ROLE="SNOW_ACCOUNTADMINS"
$env:SNOWFLAKE_WAREHOUSE="COMPUTE_WH"
$env:SNOWFLAKE_DATABASE="DBA_MAINT_DB"
$env:SNOWFLAKE_SCHEMA="OVERWATCH"
.\.venv\Scripts\python.exe .\perf_tests\run_snowflake_safe_suite.py
```

The runner executes `01_perf_test_setup.sql`, calls
`SP_PERF_TEST_GUARDRAIL_CHECK('LIGHTWEIGHT_METADATA', FALSE)`, and stops before
synthetic data generation unless the guardrail returns `OK`.

9. Cleanup:

```sql
@perf_tests/sql/99_cleanup_perf_test.sql;
```

## Pass/Fail Standards

| Signal | Pass | Watch | Fail |
|---|---:|---:|---:|
| Initial HTTP p95 | <= 2500 ms | <= 5000 ms | > 5000 ms |
| Live browser step p95 | <= 10000 ms | <= 20000 ms | > 20000 ms |
| HTTP error rate | 0% | <= 2% | > 2% |
| Snowflake query p95 | <= 8 sec | <= 20 sec | > 20 sec |
| Remote spill | 0-5 GB | 5-25 GB | > 25 GB |
| Failed dashboard queries | 0 | 1 explained failure | > 1 unexplained failure |
| Readiness gates | CI, section smoke, mart validation, and first-paint scan guards pass | One gate needs documented review | Any required gate fails without accepted mitigation |

## What This Will Catch

- Slow initial Streamlit response or server-side lag.
- Repeated expensive query patterns through `OVERWATCH_USAGE_LOG`.
- Sections returning too many rows or large pandas results.
- Shared warehouse cost exposure during dashboard sessions.
- Remote spill, queue pressure, partition-scan issues, and cache misses.
- Synthetic task/procedure/user/workload skew at 5 TB metadata scale.

## What This Will Not Prove By Itself

- It does not click every in-app widget. Use the browser smoke tests for targeted UI flows.
- HTTP load is not a perfect substitute for Snowflake Streamlit viewer concurrency.
- Warehouse metering is shared, so `PERF_TEST_COST_ESTIMATE_V` is estimated unless OVERWATCH is isolated to a test warehouse.
- Metadata simulation proves logic and query shape, not storage engine behavior at physical 5 TB.

## Production Recommendations

- Keep app default pages mart-backed and lazy-load deep evidence.
- Push aggregation/filtering into Snowflake SQL; do not pull raw 5 TB-like rows into pandas.
- Keep result tables capped and paginated.
- Use materialized views or dynamic tables only for repeated, high-value aggregations.
- Use clustering/Search Optimization only after query profile proves pruning gaps.
- Use Query Acceleration only after spill/scan/latency evidence shows single-query acceleration need.
- Isolate full-scale tests from business workload warehouses when possible.

## Rollback

Run `sql/99_cleanup_perf_test.sql`. It drops only objects prefixed with
`PERF_TEST_` plus `SP_PERF_TEST_GUARDRAIL_CHECK`.

To remove app instrumentation, revert the changes in:

- `.overwatch_final/utils/query.py`
- `.overwatch_final/utils/logging.py`

The instrumentation is passive unless `OVERWATCH_PERF_RUN_ID` or
`st.session_state["_overwatch_perf_run_id"]` is set.
