# OVERWATCH 12 Power User Tuning

This guide keeps the release performance gate repeatable without making generated browser artifacts part of the tracked repo.

## Run Profile
- Start OVERWATCH locally or in a staged environment.
- Run the broad read-only profile:
  `python perf_tests/run_12_power_users.py --url http://localhost:8501/ --run-id PERF_12_POWER_USERS_RELEASE --output-dir perf_tests/results`
- The release p95 threshold is `10000 ms`. Treat p95 above that value, browser errors, skipped configured load buttons, or readiness below `95/100` as release blockers.
- The 12-power-user profile records diagnostic-only `initial_load` substeps for `goto_commit`, `domcontentloaded`, `initial_wait`, `shell_title_visible`, `topbar_visible`, `sidebar_visible`, `app_ready`, `section_container_visible`, `perf_trace_collected`, and `idle_wait` when initial idle waiting is enabled. These samples appear under Initial Load Breakdown but do not change release p95, error rate, readiness, or release blockers.
- Use the initial-load-only profile to isolate App Shell first render without section navigation or load-button flows. This is diagnostic only and is not the release gate:
  `python perf_tests/run_12_power_users.py --url http://localhost:8503/ --run-id PERF_12_POWER_USERS_INITIAL_LOAD_RERUN3 --output-dir perf_tests/results --profile perf_tests/profiles/12_power_users_initial_load_only.json`
- Use the import timing probe before browser reruns when App Shell cold start is the bottleneck:
  `python perf_tests/import_timing.py --run-id IMPORT_TIMING_3E75A32_RERUN3 --output-dir perf_tests/results --importtime`
- Do not add or click mutation controls in broad profiles. Keep grant, save, queue, email/send, retry, suspend/resume, execute, cancel, drop, alter, create, delete, deactivate, and admin mutation controls out of benchmark profiles.

## Server And Browser Diagnostics
- When the runner sends `overwatch_perf_run_id`, `overwatch_perf_user`, and `overwatch_perf_iteration` query parameters, OVERWATCH stores a bounded server phase trace in Streamlit session state and exposes it through a hidden `overwatch-perf-trace` DOM marker. Normal user sessions do not collect or render this trace.
- Server phase trace samples include shell theme injection, startup state, role seeding, admin defaults, idle state, Snowflake availability probe, role refresh, header/topbar/sidebar rendering, filter cache checks, section signature, section dispatch, lazy module import, section render, and Executive Landing shell phases.
- Browser navigation timing records `responseStart`, `responseEnd`, `domInteractive`, `domContentLoadedEventEnd`, `loadEventEnd`, `transferSize`, and `encodedBodySize` when the browser exposes them. Use browser navigation timing with paint timing (`first-paint` and `first-contentful-paint`) to separate server first response from client rendering.

## Query Logging
- Use a unique run ID such as `PERF_12_POWER_USERS_RELEASE` as the query tag for the benchmark session whenever credentials and the target Snowflake session allow it.
- When validating a staged deployment, also capture Snowflake Query History with the run ID, user, role, warehouse, query text hash, elapsed time, bytes scanned, partitions scanned, remote spill, and credits.
- Keep live Snowflake credentials out of generated reports and commit only summarized evidence.

## Reports To Collect
- `perf_tests/results/PERF_12_POWER_USERS_RELEASE_live_concurrent.json`
- `perf_tests/results/PERF_12_POWER_USERS_RELEASE_live_concurrent.md`
- `perf_tests/results/PERF_12_POWER_USERS_RELEASE_expert_review.md`
- `perf_tests/results/PERF_12_POWER_USERS_INITIAL_LOAD_RERUN3_live_concurrent.json`
- `perf_tests/results/IMPORT_TIMING_3E75A32_RERUN3_import_timing.json`
- `perf_tests/results/IMPORT_TIMING_3E75A32_RERUN3_import_timing.md`
- `PERF_TEST_APP_USAGE_REPORT_V`
- `PERF_TEST_SNOWFLAKE_QUERY_REPORT_V`
- `PERF_TEST_EXPENSIVE_QUERY_CANDIDATES_V`
- Snowflake Query History filtered by the benchmark query tag or run ID

## Triage Order
- App Shell `initial_load`: check the Initial Load Breakdown first. `goto_commit` and `domcontentloaded` point at browser/server handshake, `initial_wait` is configured settle time, `shell_title_visible`/`topbar_visible`/`sidebar_visible` show chrome readiness, `app_ready` and `section_container_visible` point at Streamlit first render and section work, `perf_trace_collected` confirms server trace exposure, and `idle_wait` points at post-render spinner/work completion.
- Server phase trace: if `shell:probe_snowflake_available` dominates, tune connection-probe contention/caching. If `section_dispatch:module_import:*` dominates, split compatibility re-exports from route renderers. If Executive Landing shell phases dominate, keep first paint on local summary frames and move optional workflow work behind explicit controls.
- Browser navigation timing: high `responseStart` with high `goto_commit` points at server first response or cold Streamlit startup. High `domContentLoadedEventEnd` with low server phases points at browser/client rendering.
- Import timing: rank baselines (`streamlit`, `pandas`, `config`, `theme`, `filters`, `layout`, `navigation`, `runtime_state`, `access_control`, `utils`) and targets (`shell`, `section_dispatch`, `sections.executive_landing_shell`, and section modules). If a route import dominates, split compatibility re-exports from the route renderer before changing release thresholds.
- `section_nav`: rank `top_slowest_sections` and compare navigation p95 to the matching Query History rows. The runner treats the shell transition as clear when it is no longer visible; persistent hidden transition DOM should not be counted as navigation latency.
- `load_button` actions: keep only read-only load buttons in the broad profile and push deep workflows into targeted profiles.
- Skipped buttons: group by label, confirm the visible default control still exists, or move the action to a targeted profile with a documented reason.
- Browser errors: fix visible Streamlit errors and console/runtime errors before interpreting latency.
- Snowflake query p95: compare application timing with Query History elapsed time for the same query tag.
- Remote spill: prioritize queries that spill remotely or scan broad ACCOUNT_USAGE windows during first paint.
- Shared warehouse credits: estimate only from isolated benchmark warehouses, or label shared-warehouse costs as approximate.

## Evidence Policy
- Generated files under `perf_tests/results/` are local run evidence and are intentionally stored outside git.
- Release evidence must record the run ID, p95, p99, errors, readiness score, slowest section, slowest action, skipped buttons, live report path, expert review path, and whether the manifest remains candidate or release-ready.
