# OVERWATCH 12 Power User Tuning

This guide keeps the release performance gate repeatable without making generated browser artifacts part of the tracked repo.

## Run Profile
- Start OVERWATCH locally or in a staged environment.
- Run the clean scored release profile. `run_12_power_users.py` defaults to `perf_tests/profiles/12_power_users_release_scored.json`, which preserves the broad read-only workload but disables diagnostic substeps and tracing:
  `python perf_tests/run_12_power_users.py --url http://localhost:8503/ --run-id PERF_12_POWER_USERS_RELEASE_RERUN6 --output-dir perf_tests/results --profile perf_tests/profiles/12_power_users_release_scored.json`
- RERUN6 passed the p95 threshold (`7446.09 ms`) but failed readiness (`92/100`) because p99 crossed the p99 tail threshold. The readiness penalty is explicit in runner summaries as `p99_tail` when p99 exceeds `fail_p95_ms * 1.8`.
- Add tail diagnostics only when investigating a near-pass tail. `--tail-diagnostics` replays the slowest initial-load users and slowest section navigation after scoring has completed, so the trace, screenshot, frontend metrics, browser timing, and perf trace artifacts do not affect release p95, p99, readiness, or blockers. Add `--tail-capture-threshold-ms 18000` when you also want in-run tail capture for initial-load samples that already crossed the p99 tail threshold; capture starts only after the scored stopwatch stops:
  `python perf_tests/run_12_power_users.py --url http://localhost:8503/ --run-id PERF_12_POWER_USERS_RELEASE_RERUN7 --output-dir perf_tests/results --profile perf_tests/profiles/12_power_users_release_scored.json --tail-diagnostics --tail-capture-threshold-ms 18000`
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
- Use the release stability runner to decide whether a near-pass p99/readiness miss is random tail variance or a repeatable blocker. `perf_tests/run_release_stability.py` repeats the clean scored profile and summarizes median and worst-case p95, p99, max, readiness, skipped buttons, errors, slowest initial-load sample, and a release stability conclusion (`stable_pass`, `stable_watch_tail`, or `unstable_environment_tail`):
  `python perf_tests/run_release_stability.py --url http://localhost:8503/ --run-id-prefix PERF_RELEASE_STABILITY_RERUN6 --output-dir perf_tests/results --repeats 3`
- Use `--browser-launch-mode per_user` only as a diagnostic control for local-client contention. The clean release gate remains the scored profile; a longer ramp or per-user browser mode can explain host capacity limits, but it should not be treated as an app-code pass without an explicit release decision.
- Use the client isolation matrix when a clean scored run shows low server render and low HTTP TTFB but high browser FCP or stale section-state tails. It compares shared browser/current ramp, per-user browser/current ramp, shared browser/ramp 24, shared browser/ramp 36, and per-user browser/ramp 24 without changing the release profile:
  `python perf_tests/run_client_isolation_matrix.py --url http://localhost:8503/ --run-id-prefix PERF_CLIENT_ISOLATION_RERUN8 --output-dir perf_tests/results`
- Strict ramp-12 and ramp-24 capacity-adjusted release posture are intentionally separate. `perf_tests/profiles/12_power_users_release_scored.json` remains the strict ramp-12 baseline. `perf_tests/profiles/12_power_users_release_scored_ramp24.json` is the same clean scored workload with `ramp_seconds: 24`; use it only when the release manifest explicitly identifies ramp-24 as the authoritative local-client release policy:
  `python perf_tests/run_12_power_users.py --url http://localhost:8503/ --run-id PERF_12_POWER_USERS_RELEASE_RERUN9 --output-dir perf_tests/results --profile perf_tests/profiles/12_power_users_release_scored_ramp24.json --tail-diagnostics --tail-capture-threshold-ms 18000`
- Before promoting ramp-24, run stability for both the strict baseline and the ramp-24 candidate. Ramp-24 promotion requires median readiness at or above `95/100`, at least `2/3` PASS runs, errors `0`, skipped buttons `0`, and a final chosen-profile release run that passes:
  `python perf_tests/run_release_stability.py --url http://localhost:8503/ --run-id-prefix PERF_RELEASE_STABILITY_RERUN9_RAMP12 --output-dir perf_tests/results --repeats 3 --profile perf_tests/profiles/12_power_users_release_scored.json`
  `python perf_tests/run_release_stability.py --url http://localhost:8503/ --run-id-prefix PERF_RELEASE_STABILITY_RERUN9_RAMP24 --output-dir perf_tests/results --repeats 3 --profile perf_tests/profiles/12_power_users_release_scored_ramp24.json`
- If strict ramp-12 remains mandatory after the policy review, keep ramp-24 as diagnostic evidence and continue frontend/client first-paint reduction. A lean first-paint experiment should use a query flag such as `overwatch_perf_lean_first_paint=1` only after the shell/executive reductions are explicitly scoped so primary navigation and read-only load controls remain visible.
- Use the browser capacity matrix to compare viewport and Chromium launch variants for frontend paint pressure. `perf_tests/run_browser_capacity_matrix.py` reports p95, responseStart, FCP, DOM node count, resource counts, and host resource samples:
  `python perf_tests/run_browser_capacity_matrix.py --url http://localhost:8503/ --run-id-prefix PERF_BROWSER_CAPACITY_RERUN6 --output-dir perf_tests/results`
- Do not add or click mutation controls in broad profiles. Keep grant, save, queue, email/send, retry, suspend/resume, execute, cancel, drop, alter, create, delete, deactivate, and admin mutation controls out of benchmark profiles.
- RERUN7C regressed from the near-pass RERUN6 shape: p95, p99/readiness, one Streamlit client `Download Button source error - 404`, and one stale-section skipped load button all blocked release. Treat that evidence as client resource lifecycle and section-state work first; do not tune Snowflake query paths for that failure shape.

## Release Ramp Policy
- Strict ramp-12 is the diagnostic local-client stress baseline. Keep `perf_tests/profiles/12_power_users_release_scored.json` available and unchanged for strict capacity investigations.
- Ramp-24 is the authoritative local-client release gate for this release. Use `perf_tests/profiles/12_power_users_release_scored_ramp24.json` only when the manifest or release evidence explicitly identifies ramp-24 as authoritative.
- RERUN9 made the policy decision explicit because strict ramp-12 stability remained `stable_watch_tail`, while ramp-24 stability passed `3/3` with readiness `100/100` and the client isolation matrix recommended `ramp24_passes`.
- Release-readiness policy/evidence commit `9603567b30b0e2dcda601fe772f8e7ee94a35ad1` contains the ramp-24 profile, release-policy documentation, and RERUN9 evidence updates; the manifest still labels `24cd05e2e27ced74b29718ba85ce6112b2227cf7` as the original release-candidate baseline for the evidence file.
- This is a release-process and local-client capacity decision. It does not change Snowflake query semantics, does not relax read-only benchmark controls, and does not claim fresh live Snowflake regression evidence.

## Server And Browser Diagnostics
- When the runner sends `overwatch_perf_run_id`, `overwatch_perf_user`, and `overwatch_perf_iteration` query parameters, OVERWATCH stores a bounded server phase trace in Streamlit session state and exposes a compact hidden `overwatch-perf-trace` DOM marker. Normal user sessions do not collect or render this trace. Runtime metadata is payload-level and marker samples are capped so the diagnostic marker does not become a first-paint payload bottleneck.
- Server phase trace samples include shell theme injection, startup state, role seeding, admin defaults, idle state, Snowflake availability probe, role refresh, header/topbar/sidebar rendering, filter cache checks, section signature, section dispatch, lazy module import, section render, and Executive Landing shell phases.
- App-entry import timing records `app_entry:import_streamlit`, `app_entry:set_page_config`, `app_entry:import_shell`, `app_entry:import_perf_trace`, and `app_entry:pre_render_total`. These are measured before `perf_trace` is imported and recorded afterward, so they can explain slow first response that occurs before `render_app()`.
- Browser navigation timing records `responseStart`, `responseEnd`, `domInteractive`, `domContentLoadedEventEnd`, `loadEventEnd`, `transferSize`, and `encodedBodySize` when the browser exposes them. Use browser navigation timing with paint timing (`first-paint` and `first-contentful-paint`) to separate server first response from client rendering.
- Section navigation diagnostics record diagnostic-only phases for click, title visibility, transition clear, section container visibility, and perf-trace collection. Release `section_nav` p95 is still computed only from the scored section navigation sample.
- Frontend paint metrics record DOM node count, visible button count, script/style/link counts, stylesheet and CSS rule counts, JS heap data when exposed, long tasks, layout shift, and resource timing grouped by initiator type. Use these with FCP to decide whether a failure is browser/frontend capacity rather than Snowflake or server work.
- Runner host resource samples record best-effort CPU, memory, process count, and browser child process count when `psutil` is available. Missing `psutil` does not block a run.
- Skipped-button diagnostics capture the active section title, visible button labels, visible headings/captions, whether hidden load surfaces were expanded, spinner/transition counts, and a local screenshot path under `perf_tests/results/`. Screenshots are generated evidence and remain outside git.
- Load-button diagnostics also verify the hidden `overwatch-active-section-body` marker before clicking a configured load control. If the visible title says `Alert Center` but the body marker or buttons still belong to `DBA Control Room`, classify the skip as stale section state and investigate shell/navigation rerun ordering before changing button labels.
- In-run tail capture records screenshot, browser navigation timing, paint timing, frontend metrics, visible section/button context, host resource sample, and current perf trace immediately after a scored initial-load sample crosses the configured threshold. It does not create a release sample and the stopwatch has already stopped, but it can explain tails that disappear in a later replay.
- In-run tail capture includes console warnings/errors, failed request/response events, failed or 404 resource timing rows, current URL/query params, websocket resource rows when exposed, current section title, visible buttons, and long-task totals. Use this to diagnose Streamlit client 404/download-source lifecycle failures that are not reproduced by a later single-user replay.
- Tail replay diagnostics capture the slowest release initial-load users and slowest section navigation after the clean scored run has completed. Use them for Playwright traces, screenshots, frontend metrics, browser navigation timing, paint timing, and server perf trace without reintroducing diagnostic waits into the scored release samples.
- Replay reproduction compares scored release elapsed time to replay elapsed, responseStart, and first-contentful-paint. If release elapsed is above `18000 ms` but replay FCP is below `2000 ms`, treat the tail as not reproduced and focus on concurrent browser/client contention rather than Snowflake query paths.
- The report sections are named for frontend paint metrics and skipped-button diagnostics so reviewers can find the client-side and missing-control context quickly.

## Query Logging
- Use a unique run ID such as `PERF_12_POWER_USERS_RELEASE` as the query tag for the benchmark session whenever credentials and the target Snowflake session allow it.
- When validating a staged deployment, also capture Snowflake Query History with the run ID, user, role, warehouse, query text hash, elapsed time, bytes scanned, partitions scanned, remote spill, and credits.
- Keep live Snowflake credentials out of generated reports and commit only summarized evidence.

## Reports To Collect
- `perf_tests/results/PERF_12_POWER_USERS_RELEASE_live_concurrent.json`
- `perf_tests/results/PERF_12_POWER_USERS_RELEASE_live_concurrent.md`
- `perf_tests/results/PERF_12_POWER_USERS_RELEASE_expert_review.md`
- `perf_tests/results/PERF_12_POWER_USERS_RELEASE_RERUN7_*_trace.zip`, `*_in_run_tail_*.png`, and replay `*.png` artifacts when tail diagnostics or in-run tail capture are enabled
- `perf_tests/results/PERF_12_POWER_USERS_INITIAL_LOAD_RERUN6_live_concurrent.json`
- `perf_tests/results/PERF_12_POWER_USERS_SECTION_NAV_RERUN6_live_concurrent.json`
- `perf_tests/results/PERF_12_POWER_USERS_DIAGNOSTIC_RERUN6_live_concurrent.json`
- `perf_tests/results/IMPORT_TIMING_14020F4_RERUN6_FINAL_import_timing.json`
- `perf_tests/results/IMPORT_TIMING_14020F4_RERUN6_FINAL_import_timing.md`
- `perf_tests/results/HTTP_FIRST_RESPONSE_14020F4_RERUN6_FINAL_http_first_response.json`
- `perf_tests/results/PERF_INITIAL_LOAD_LADDER_RERUN6_FINAL_initial_load_ladder.json`
- `perf_tests/results/PERF_DIAGNOSTIC_OVERHEAD_RERUN6_diagnostic_overhead_ab.json`
- `perf_tests/results/PERF_RELEASE_STABILITY_RERUN6_FINAL_release_stability.json`
- `perf_tests/results/PERF_CLIENT_ISOLATION_RERUN8_client_isolation_matrix.json`
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
- Release stability: if median p95 and readiness pass but one run misses p99/readiness, treat the release gate as environment-tail sensitive and collect tail replay diagnostics before changing app code. If the median run still misses readiness, keep the manifest candidate. Use the release stability conclusion as the summary label: `stable_pass` means repeated clean scored evidence is strong enough to promote, `stable_watch_tail` means the p99/readiness tail is repeatable, and `unstable_environment_tail` means the local browser/client environment needs more isolation before code changes are blamed.
- Readiness penalty: `p99_tail` means p95 may already be under the `10000 ms` release threshold, but p99 exceeded `fail_p95_ms * 1.8`; tune App Shell initial-load tail and browser/client first paint before changing mart SQL.
- Tail replay diagnostics: inspect the slowest replay trace, screenshot, frontend metrics, browser timing, and perf trace for the same user/section that produced the release tail. Tail replay is not the release gate. If replay reproduction is false while in-run tail capture shows high browser timing, prioritize concurrent browser/client contention and frontend first-paint load.
- Client 404 troubleshooting: search for `st.download_button` and export helpers mounted during first paint or normal section navigation. Keep nonessential downloads behind explicit gates, use stable widget keys, and keep data sources stable across reruns so Streamlit does not publish a transient download source that later returns 404 under concurrent clients.
- Stale section-state troubleshooting: compare `.ow-section-title`, the hidden body marker, visible load buttons, spinner/transition counts, and skipped-button screenshots. If the title changes before the body marker, fix shell/navigation state ordering and rerun timing before changing the broad profile load labels.
- Client isolation matrix: if per-user browser mode or a longer ramp removes p99/FCP tails while HTTP TTFB and server phases remain low, classify the blocker as local browser-host/client capacity. Document the diagnosis; do not change release ramp policy without an explicit release-process decision.
- Ramp policy assessment: `run_client_isolation_matrix.py` reports `p99_tail_pass`, `readiness_pass`, `release_policy_candidate`, and a recommendation token (`ramp24_passes`, `ramp12_tail_blocked`, or `per_user_only_passes`). Use `ramp24_passes` only when the shared-browser ramp-24 case is a candidate; use `per_user_only_passes` as benchmark-host capacity evidence, not as an app release pass.
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
