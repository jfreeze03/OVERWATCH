# OVERWATCH 12 Power User Tuning

This guide keeps the release performance gate repeatable without making generated browser artifacts part of the tracked repo.

## Run Profile
- Start OVERWATCH locally or in a staged environment.
- Run the clean scored release profile. `run_12_power_users.py` defaults to `perf_tests/profiles/12_power_users_release_scored.json`, which preserves the broad read-only workload but disables diagnostic substeps and tracing:
  `python perf_tests/run_12_power_users.py --url http://localhost:8503/ --run-id PERF_12_POWER_USERS_RELEASE_RERUN6 --output-dir perf_tests/results --profile perf_tests/profiles/12_power_users_release_scored.json`
- RERUN6 passed the p95 threshold (`7446.09 ms`) but failed readiness (`92/100`) because p99 crossed the p99 tail threshold. The readiness penalty is explicit in runner summaries as `p99_tail` when p99 exceeds `fail_p95_ms * 1.8`.
- Add post-scoring tail replay diagnostics only when investigating a near-pass tail. `--tail-diagnostics` replays the slowest initial-load users and slowest section navigation after scoring has completed, so the trace, screenshot, frontend metrics, browser timing, and perf trace artifacts do not affect release p95, p99, readiness, or blockers:
  `python perf_tests/run_12_power_users.py --url http://localhost:8503/ --run-id PERF_12_POWER_USERS_RELEASE_RERUN6 --output-dir perf_tests/results --profile perf_tests/profiles/12_power_users_release_scored.json --tail-diagnostics`
- Run the broad diagnostic profile only when investigating a failed gate. `perf_tests/profiles/12_power_users_diagnostic.json` and compatibility profile `perf_tests/profiles/12_power_users.json` enable initial-load substeps, section-nav substeps, and the slowest-user trace replay:
  `python perf_tests/run_12_power_users.py --url http://localhost:8503/ --run-id PERF_12_POWER_USERS_DIAGNOSTIC_RERUN6 --output-dir perf_tests/results --profile perf_tests/profiles/12_power_users_diagnostic.json`
- The release p95 threshold is `10000 ms`. Treat p95 above that value, browser errors, skipped configured load buttons, or readiness below `95/100` as release blockers.
- The diagnostic 12-power-user profile records diagnostic-only `initial_load` substeps for `goto_commit`, `domcontentloaded`, `initial_wait`, `shell_title_visible`, `topbar_visible`, `sidebar_visible`, `app_ready`, `section_container_visible`, `perf_trace_collected`, and `idle_wait` when initial idle waiting is enabled. These samples appear under Initial Load Breakdown but do not change release p95, error rate, readiness, or release blockers. Keep these diagnostics out of the clean scored release profile so diagnostic waits do not inflate parent release actions.
- Use the initial-load-only profile to isolate App Shell first render without section navigation or load-button flows. This is diagnostic only and is not the release gate:
  `python perf_tests/run_12_power_users.py --url http://localhost:8503/ --run-id PERF_12_POWER_USERS_INITIAL_LOAD_RERUN6 --output-dir perf_tests/results --profile perf_tests/profiles/12_power_users_initial_load_only.json`
- Use the section-nav-only profile to isolate title-visible and client route waits without load-button noise. `perf_tests/profiles/12_power_users_section_nav_only.json` has no load buttons and is diagnostic only:
  `python perf_tests/run_12_power_users.py --url http://localhost:8503/ --run-id PERF_12_POWER_USERS_SECTION_NAV_RERUN6 --output-dir perf_tests/results --profile perf_tests/profiles/12_power_users_section_nav_only.json`
- Use the import timing probe before browser reruns when App Shell cold start is the bottleneck:
  `python perf_tests/import_timing.py --run-id IMPORT_TIMING_14020F4_RERUN6 --output-dir perf_tests/results --importtime`
- Use the HTTP-only first-response probe to isolate Streamlit/server first byte without Chromium paint overhead:
  `python perf_tests/http_first_response_probe.py --url http://localhost:8503/ --run-id HTTP_FIRST_RESPONSE_14020F4_RERUN6 --output-dir perf_tests/results`
- Use the initial-load concurrency ladder to find the first concurrency level where App Shell first render degrades. This is diagnostic only and is not the release gate:
  `python perf_tests/run_initial_load_ladder.py --url http://localhost:8503/ --run-id-prefix PERF_INITIAL_LOAD_LADDER_RERUN6 --output-dir perf_tests/results`
- Use the diagnostic overhead A/B runner to compare the clean scored profile against full diagnostics with the same workload. `perf_tests/run_diagnostic_overhead_ab.py` reports whether diagnostic capture is materially inflating p95:
  `python perf_tests/run_diagnostic_overhead_ab.py --url http://localhost:8503/ --run-id-prefix PERF_DIAGNOSTIC_OVERHEAD_RERUN6 --output-dir perf_tests/results --repeats 2 --warmup`
- Use the release stability runner to decide whether a near-pass p99/readiness miss is random tail variance or a repeatable blocker. `perf_tests/run_release_stability.py` repeats the clean scored profile and summarizes p95, p99, max, readiness, skipped buttons, errors, and the slowest initial-load sample:
  `python perf_tests/run_release_stability.py --url http://localhost:8503/ --run-id-prefix PERF_RELEASE_STABILITY_RERUN6 --output-dir perf_tests/results --repeats 3`
- Use `--browser-launch-mode per_user` only as a diagnostic control for local-client contention. The clean release gate remains the scored profile; a longer ramp or per-user browser mode can explain host capacity limits, but it should not be treated as an app-code pass without an explicit release decision.
- Use the browser capacity matrix to compare viewport and Chromium launch variants for frontend paint pressure. `perf_tests/run_browser_capacity_matrix.py` reports p95, responseStart, FCP, DOM node count, resource counts, and host resource samples:
  `python perf_tests/run_browser_capacity_matrix.py --url http://localhost:8503/ --run-id-prefix PERF_BROWSER_CAPACITY_RERUN6 --output-dir perf_tests/results`
- Do not add or click mutation controls in broad profiles. Keep grant, save, queue, email/send, retry, suspend/resume, execute, cancel, drop, alter, create, delete, deactivate, and admin mutation controls out of benchmark profiles.

## Server And Browser Diagnostics
- When the runner sends `overwatch_perf_run_id`, `overwatch_perf_user`, and `overwatch_perf_iteration` query parameters, OVERWATCH stores a bounded server phase trace in Streamlit session state and exposes a compact hidden `overwatch-perf-trace` DOM marker. Normal user sessions do not collect or render this trace. Runtime metadata is payload-level and marker samples are capped so the diagnostic marker does not become a first-paint payload bottleneck.
- Server phase trace samples include shell theme injection, startup state, role seeding, admin defaults, idle state, Snowflake availability probe, role refresh, header/topbar/sidebar rendering, filter cache checks, section signature, section dispatch, lazy module import, section render, and Executive Landing shell phases.
- App-entry import timing records `app_entry:import_streamlit`, `app_entry:set_page_config`, `app_entry:import_shell`, `app_entry:import_perf_trace`, and `app_entry:pre_render_total`. These are measured before `perf_trace` is imported and recorded afterward, so they can explain slow first response that occurs before `render_app()`.
- Browser navigation timing records `responseStart`, `responseEnd`, `domInteractive`, `domContentLoadedEventEnd`, `loadEventEnd`, `transferSize`, and `encodedBodySize` when the browser exposes them. Use browser navigation timing with paint timing (`first-paint` and `first-contentful-paint`) to separate server first response from client rendering.
- Section navigation diagnostics record diagnostic-only phases for click, title visibility, transition clear, section container visibility, and perf-trace collection. Release `section_nav` p95 is still computed only from the scored section navigation sample.
- Frontend paint metrics record DOM node count, visible button count, script/style/link counts, stylesheet and CSS rule counts, JS heap data when exposed, long tasks, layout shift, and resource timing grouped by initiator type. Use these with FCP to decide whether a failure is browser/frontend capacity rather than Snowflake or server work.
- Runner host resource samples record best-effort CPU, memory, process count, and browser child process count when `psutil` is available. Missing `psutil` does not block a run.
- Skipped-button diagnostics capture the active section title, visible button labels, visible headings/captions, whether hidden load surfaces were expanded, spinner/transition counts, and a local screenshot path under `perf_tests/results/`. Screenshots are generated evidence and remain outside git.
- Tail replay diagnostics capture the slowest release initial-load users and slowest section navigation after the clean scored run has completed. Use them for Playwright traces, screenshots, frontend metrics, browser navigation timing, paint timing, and server perf trace without reintroducing diagnostic waits into the scored release samples.
- The report sections are named for frontend paint metrics and skipped-button diagnostics so reviewers can find the client-side and missing-control context quickly.

## Query Logging
- Use a unique run ID such as `PERF_12_POWER_USERS_RELEASE` as the query tag for the benchmark session whenever credentials and the target Snowflake session allow it.
- When validating a staged deployment, also capture Snowflake Query History with the run ID, user, role, warehouse, query text hash, elapsed time, bytes scanned, partitions scanned, remote spill, and credits.
- Keep live Snowflake credentials out of generated reports and commit only summarized evidence.

## Reports To Collect
- `perf_tests/results/PERF_12_POWER_USERS_RELEASE_live_concurrent.json`
- `perf_tests/results/PERF_12_POWER_USERS_RELEASE_live_concurrent.md`
- `perf_tests/results/PERF_12_POWER_USERS_RELEASE_expert_review.md`
- `perf_tests/results/PERF_12_POWER_USERS_RELEASE_RERUN6_*_trace.zip` and `*.png` tail replay artifacts when `--tail-diagnostics` is enabled
- `perf_tests/results/PERF_12_POWER_USERS_INITIAL_LOAD_RERUN6_live_concurrent.json`
- `perf_tests/results/PERF_12_POWER_USERS_SECTION_NAV_RERUN6_live_concurrent.json`
- `perf_tests/results/PERF_12_POWER_USERS_DIAGNOSTIC_RERUN6_live_concurrent.json`
- `perf_tests/results/IMPORT_TIMING_14020F4_RERUN6_FINAL_import_timing.json`
- `perf_tests/results/IMPORT_TIMING_14020F4_RERUN6_FINAL_import_timing.md`
- `perf_tests/results/HTTP_FIRST_RESPONSE_14020F4_RERUN6_FINAL_http_first_response.json`
- `perf_tests/results/PERF_INITIAL_LOAD_LADDER_RERUN6_FINAL_initial_load_ladder.json`
- `perf_tests/results/PERF_DIAGNOSTIC_OVERHEAD_RERUN6_diagnostic_overhead_ab.json`
- `perf_tests/results/PERF_RELEASE_STABILITY_RERUN6_FINAL_release_stability.json`
- `perf_tests/results/PERF_BROWSER_CAPACITY_RERUN6_browser_capacity_matrix.json`
- `PERF_TEST_APP_USAGE_REPORT_V`
- `PERF_TEST_SNOWFLAKE_QUERY_REPORT_V`
- `PERF_TEST_EXPENSIVE_QUERY_CANDIDATES_V`
- Snowflake Query History filtered by the benchmark query tag or run ID

## Triage Order
- App Shell `initial_load`: check the Initial Load Breakdown first. `goto_commit` and `domcontentloaded` point at browser/server handshake, `initial_wait` is configured settle time, `shell_title_visible`/`topbar_visible`/`sidebar_visible` show chrome readiness, `app_ready` and `section_container_visible` point at Streamlit first render and section work, `perf_trace_collected` confirms server trace exposure, and `idle_wait` points at post-render spinner/work completion.
- App-entry import timing: high `app_entry:import_shell` means the Python shell import path is delaying first response before `render_app()`. Split optional imports from shell/layout/filter/theme paths only when this phase dominates.
- Server phase trace: if `shell:probe_snowflake_available` dominates, tune connection-probe contention/caching. If `section_dispatch:module_import:*` dominates, split compatibility re-exports from route renderers. If Executive Landing shell phases dominate, keep first paint on local summary frames and move optional workflow work behind explicit controls.
- Browser navigation timing: high `responseStart` with high `goto_commit` points at server first response or cold Streamlit startup. High `domContentLoadedEventEnd` with low server phases points at browser/client rendering.
- Browser paint timing: high `first-contentful-paint` with low app-entry and server phase p95 points at Chromium host capacity, DOM/CSS paint pressure, or Streamlit client-side rendering rather than Snowflake query work.
- Diagnostic overhead A/B: if clean scored p95 is much lower than diagnostic p95, keep diagnostic capture out of the release gate and tune only with explicit diagnostic profiles. If both are high, treat the blocker as real browser/frontend capacity or app behavior.
- Release stability: if median p95 and readiness pass but one run misses p99/readiness, treat the release gate as environment-tail sensitive and collect tail replay diagnostics before changing app code. If the median run still misses readiness, keep the manifest candidate.
- Readiness penalty: `p99_tail` means p95 may already be under the `10000 ms` release threshold, but p99 exceeded `fail_p95_ms * 1.8`; tune App Shell initial-load tail and browser/client first paint before changing mart SQL.
- Tail replay diagnostics: inspect the slowest replay trace, screenshot, frontend metrics, browser timing, and perf trace for the same user/section that produced the release tail. Tail replay is not the release gate.
- Frontend paint metrics: high DOM node count, CSS rule count, long tasks, layout shift, or resource duration with low server phases points at client paint pressure. Reduce first-paint DOM/CSS or Streamlit client work before changing Snowflake query paths.
- Browser capacity matrix: compare current `1440x1000` and smaller `1280x800` viewports plus default, `--disable-dev-shm-usage`, and `--disable-gpu` Chromium modes. If smaller viewport or runtime flags materially reduce FCP without changing server phases, the bottleneck is browser host/frontend capacity.
- HTTP first-response probe: if HTTP time-to-first-byte is low while browser `responseStart` or FCP is high, focus on browser/Chromium resource pressure and client paint. If HTTP time-to-first-byte is high, focus on Streamlit server startup/concurrency and app-entry imports.
- Import timing: rank baselines (`streamlit`, `pandas`, `config`, `theme`, `filters`, `layout`, `navigation`, `runtime_state`, `access_control`, `utils`) and targets (`shell`, `section_dispatch`, `sections.executive_landing_shell`, and section modules). If a route import dominates, split compatibility re-exports from the route renderer before changing release thresholds.
- `section_nav`: rank `top_slowest_sections` and compare navigation p95 to the matching Query History rows. Use section-nav diagnostic substeps to tell click delay from title-visible delay, transition-clear delay, container visibility, server dispatch, and module import. The runner treats the shell transition as clear when it is no longer visible; persistent hidden transition DOM should not be counted as navigation latency.
- `load_button` actions: keep only read-only load buttons in the broad profile and push deep workflows into targeted profiles.
- Skipped buttons: group by label, inspect skipped-button diagnostics, confirm the visible default control still exists, or move the action to a targeted profile with a documented reason.
- Browser errors: fix visible Streamlit errors and console/runtime errors before interpreting latency.
- Snowflake query p95: compare application timing with Query History elapsed time for the same query tag.
- Remote spill: prioritize queries that spill remotely or scan broad ACCOUNT_USAGE windows during first paint.
- Shared warehouse credits: estimate only from isolated benchmark warehouses, or label shared-warehouse costs as approximate.

## Evidence Policy
- Generated files under `perf_tests/results/` are local run evidence and are intentionally stored outside git.
- Release evidence must record the run ID, p95, p99, errors, readiness score, slowest section, slowest action, skipped buttons, live report path, expert review path, and whether the manifest remains candidate or release-ready.
