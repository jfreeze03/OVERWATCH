# OVERWATCH Application Review — UI, Performance & UX

Review date: July 3, 2026
Reviewed commit base: `main` @ `c9ef6bc`
Scope: `/.overwatch_final/` (app runtime), `tests/`, `perf_tests/`, `.streamlit/`

This review grades the app and every primary section, then makes concrete
recommendations for improving **UI**, **query performance**, **app
performance**, and **user experience (UX)**, plus a ranked plan for
**consolidation and removal**. Grades use the existing rubric in
`DBA_CONTROL_PLANE_SCORECARD.md` (data correctness, operator value, admin
safety, verification, governance, performance, UX clarity), extended with the
four dimensions the review was asked to score.

---

## 1. How this review was produced (evidence)

| Check | Result |
|---|---|
| `python -m compileall .overwatch_final` | Pass |
| `ruff check .` | Pass (all checks passed) |
| `python -m unittest discover -s tests` | 1707 tests, **1702 pass** |
| Reachability trace from the 6 registered entrypoints | See §5 |

The 5 non-passing tests are **environment-bound, not code defects**:

- 4 in `test_launch_readiness.py` require live Snowflake proof artifacts
  (billing reconciliation live run, Snowflake execution validation) that cannot
  run in an offline sandbox.
- 1 in `test_warehouse_health_split.py` fails only because `jinja2` (needed by
  `pandas.DataFrame.style`) is not installed locally. This surfaces a real but
  minor finding: `sections/warehouse_health_view_heatmap.py:77` uses
  `pivot.style.background_gradient(...)`, and `jinja2` is an **implicit**
  dependency not pinned in `requirements.txt`.

Overall code health is strong: clean lint, clean compile, a very large and
mostly green test suite, mature performance contracts, and disciplined
mart-first data access.

---

## 2. Overall grade

**Overall: B (78 / 100)**

OVERWATCH is an unusually mature Streamlit application with production-grade
data discipline (mart-first loads, first-paint query budgets, guarded SQL,
tiered caching) and a coherent 6-section operating model. It is held back by
three systemic issues:

1. **Maintainability debt** — a 4,187-line monolithic `theme.py`, ~90 `utils/`
   modules, and ~198 `sections/` files, of which a meaningful fraction are
   orphaned or duplicated (see §5).
2. **Enforcement gaps** — several strong safety mechanisms (first-paint budget,
   cache invalidation, query contracts) are **record-only in production** and
   strict only under test mode, so their real-world benefit is partial.
3. **UX depth** — navigation nests up to 5–6 levels in the heaviest sections,
   with alias sprawl and inconsistent first-paint patterns.

| Dimension | Grade | One-line assessment |
|---|:--:|---|
| Query performance | **A−** | Mart-first, tiered caching, budgets — best-in-class for a Streamlit DBA app; weakened by record-only enforcement and cache-key gaps. |
| App performance | **B+** | Lazy dispatch, deferred imports, idle pause; cold-start still blocks on a synchronous packet query and pre-first-paint session work. |
| UI / visual system | **C+** | Cohesive Snowflake-branded look; a monolithic CSS file with dual token systems and 648 `!important` rules. |
| UX / information architecture | **B−** | Clear 6-section model and shared Command Brief; deep nesting, alias sprawl, no skeletons. |
| Code health / maintainability | **B−** | Clean lint/tests, but heavy dead-code and duplication burden. |

---

## 3. Section-by-section grades

Each of the six registered sections is graded on the four requested dimensions
plus an overall. Evidence points to `.overwatch_final/`.

### 3.1 Executive Landing — **B+ (83)**
`sections/executive_landing_shell.py` → 7 lazy `executive_landing_*_view`
modules.

- **UI: B+** — Command Brief + segmented workflow tabs; compact, consistent
  with the shared kit.
- **Query perf: A−** — First paint reads a single decision packet
  (`autoload_section_command_brief`), heavy snapshot deferred behind an explicit
  "Load Full Executive Snapshot" action gated by `EVIDENCE_CLICK_QUERY_BUDGET`
  (`executive_landing_shell.py:225-235`).
- **App perf: A−** — Overview returns early without heavy scans; workflow views
  imported only when selected.
- **UX: B** — 7 workflows is on the high end; the standalone
  `sections/executive_landing.py` facade is dead (superseded by the shell) and
  should be retired.

### 3.2 DBA Control Room — **B (76)**
`sections/dba_control_room/` package (render ~1,895 lines).

- **UI: C+** — The densest surface: command queue, operability boards, multiple
  full `st.dataframe` dumps, production-readiness button grid, and executive
  scorecard can stack in one flow (`dba_control_room/render.py:249-309`).
- **Query perf: A−** — Mart-backed brief; live state deferred.
- **App perf: B** — Large render module with many bespoke gates; heavier to load
  and reason about than peer sections.
- **UX: C+** — Exceeds the rubric's "3–5 operator metrics before a table"
  guideline; the whole `account_health_*` family (~18 files) it replaced is now
  orphaned and should be removed.

### 3.3 Alert Center — **B (77)**
`sections/alert_center.py` (+ `alert_center_*` views, `utils/alert_*`).

- **UI: B** — Strong lifecycle model (active alerts, severity lanes, history,
  admin).
- **Query perf: A−** — Mart-first with labeled delayed telemetry.
- **App perf: B** — Deep admin lane splitting is fine but adds module count.
- **UX: C+** — Up to **6 navigation levels** (section → primary tab → status
  lens → admin sub-lens → brief → table). It also keeps a **parallel** entry
  path (`build_first_paint_summary_spec` / `render_section_first_paint_shell` at
  `alert_center.py:451-470`) alongside the shared Command Brief — standardize on
  one.

### 3.4 Cost & Contract — **B+ (81)**
`sections/cost_contract.py` → dynamic `cost_center`, `recommendations`,
`cortex_monitor`, `storage_monitor`, `spcs_tracker`.

- **UI: B** — Rich cost explorer, forecast, chargeback; advanced tools tucked
  behind an expander (good pattern, `cost_contract.py:277-299`).
- **Query perf: A** — Formula-aligned metering, mart-first attribution, official
  billing sources documented in the cost formula contract.
- **App perf: B** — Largest dynamic-module fan-out; the `cost_center_*` (~14),
  `warehouse_health_*` (~18), and `recommendations` families overlap heavily.
- **UX: B** — Good; the `warehouse_health` render layer should fold into
  `recommendations`/`cost_contract_advisor` (used as a library already).

### 3.5 Workload Operations — **B (75)**
`sections/workload_operations.py` → `query_analysis`, `contention_center`,
`dba_tools`, `task_management`, `pipeline_health`, `stored_proc_tracker`.

- **UI: B−** — Solid, but the front door has a **double Command Brief**:
  `render()` renders tabs/brief, then `_render_workload_overview` re-renders the
  brief (`workload_operations.py:558-563` vs `725-727`).
- **Query perf: A−** — Query investigation and pipeline lenses lazy-load.
- **App perf: B** — Fine; heavy alias map (`workload_operations.py:405-483`).
- **UX: C+** — `live_monitor.py` is fully dead (replaced by
  `contention_center`); `change_drift_*` (~8 files) is unwired (Change Analysis
  uses `utils.change_intelligence` inline instead). Both should be removed.

### 3.6 Security Monitoring — **B (77)**
`sections/security_posture.py` → `security_access`, `data_sharing`.

- **UI: B** — Overview, failed logins, risky grants, privilege sprawl, sharing.
- **Query perf: A−** — Mart-first posture with labeled sources.
- **App perf: B+** — Returns early on entry; clean lazy sub-views.
- **UX: B−** — 8 workflows plus lens pills; alias sprawl for retired
  "Security Posture"/"Security & Access" names.

**Section grade summary**

| Section | UI | Query perf | App perf | UX | Overall |
|---|:--:|:--:|:--:|:--:|:--:|
| Executive Landing | B+ | A− | A− | B | **B+ (83)** |
| DBA Control Room | C+ | A− | B | C+ | **B (76)** |
| Alert Center | B | A− | B | C+ | **B (77)** |
| Cost & Contract | B | A | B | B | **B+ (81)** |
| Workload Operations | B− | A− | B | C+ | **B (75)** |
| Security Monitoring | B | A− | B+ | B− | **B (77)** |

---

## 4. Cross-cutting layer grades

### 4.1 Query / data layer — **A− (88)**
`utils/query.py`, `utils/session.py`, `utils/mart*.py`, `utils/shared_metrics*.py`

Strengths: tiered `st.cache_data` TTLs (`CACHE_TIERS` — live 30s → metadata 4h),
mart-first-then-`ACCOUNT_USAGE`-fallback loaders, single-row first-paint decision
packets, SQL lint (`query_contracts.py`: bans `SELECT *`, unbounded
`ACCOUNT_USAGE`, leading-wildcard `ILIKE`), auto `LIMIT` injection, guarded
sessions, and idle query pause.

Weaknesses:
- **Cache invalidation is effectively disabled on refresh.** Every call site of
  `clear_all_cache()` passes `clear_streamlit_cache=False`
  (`filters.py:343`, `layout.py:396`), so "Refresh" clears session state but not
  `st.cache_data`; stale Snowflake results can persist up to the tier TTL (4h for
  metadata). `force_refresh(ttl_key)` exists (`query.py:1644`) but is never
  called by sections.
- **`_cache_context()` omits inputs that change displayed economics**:
  `GLOBAL_SCHEMA`, `EXCEPTIONS_ONLY_MODE`, and credit/AI/storage rates
  (`query.py:973-987`). Changing the credit price can return a stale cached row.
- **N+1 metadata probing**: `filter_existing_columns`
  (`utils/compatibility.py:300-365`) can issue one `LIMIT 0` per column on live
  fallback.

### 4.2 App shell / performance — **B+ (84)**
`app.py`, `shell.py`, `section_dispatch.py`, `performance.py`

Strengths: thin lazy entrypoint (`app.py` imports Streamlit → shell after
`set_page_config`), per-navigation lazy module dispatch, deferred heavy imports,
render-scoped query budgets, idle pause, benchmark-only perf tracing.

Weaknesses:
- **Pre-first-paint session work**: `shell.py:123-127` →
  `refresh_current_role_for_access` → `get_session()` can open Snowflake and run
  `SELECT CURRENT_ROLE()` **before** the 1-query first-paint budget applies.
- **First-paint enforcement is record-only in production**
  (`performance.py:400-403`): violations are logged but do not block; strict mode
  only under `OVERWATCH_TEST_MODE`/fixtures.
- **Synchronous cold start**: every section entry blocks on the packet
  `run_query` when the session brief cache is cold.
- **Unbounded module retention**: `section_dispatch._loaded` caches every visited
  section module for the process lifetime — good for speed, a memory concern for
  long-lived Streamlit-in-Snowflake workers.

### 4.3 UI / theme system — **C+ (72)**
`theme.py` (4,187 lines), `layout.py`, `filters.py`, `sections/shell_helpers.py`

Strengths: two cohesive Snowflake-branded themes (carbon dark default, terminal
light), CSS-variable-driven, `focus-visible` rings, `.ow-sr-only` utility, status
badges carry text labels, responsive breakpoints at 900/760/620px.

Weaknesses:
- **Monolithic and hard to change**: one ~2,450-line CSS string literal, **648
  `!important` declarations**, and **two parallel token systems** (`--bg-*` legacy
  vs `--ow-*` compact shell) that are guaranteed to drift.
- **Config/theme mismatch**: `.streamlit/config.toml` sets `base = "light"` but
  the app defaults to `carbon` (dark) and overrides Streamlit theming entirely.
- **Accessibility gaps**: operational labels at `0.63rem`, no documented WCAG
  contrast audit, `aria-hidden` misuse on inline scope controls
  (`filters.py:352`), no skip-to-main, and the 900px breakpoint hides attention
  metadata (information loss on narrow/embedded panes).
- **Dead UX hooks**: `render_setup_health_board` and `render_app_header` are
  no-ops (`shell_helpers.py:210-219`, `layout.py:151-153`).

### 4.4 Navigation / IA — **B− (74)**
`route_registry.py`, `navigation.py`, `sections/shell_helpers.py`

Strengths: clean 6-section model in 3 groups; shared `render_primary_section_tabs`
/ `render_secondary_lens_pills`; deep-link aliases preserve old bookmarks.

Weaknesses: **40+ legacy aliases** (`route_registry.py:88-126`) map retired names
to workflow presets — good for links, confusing for operators and for dead-code
analysis; multiple overlapping navigation surfaces (sidebar buttons + Command
Brief route actions + primary tabs + lens pills + breadcrumbs); the IA map exists
only in code, not surfaced to users.

---

## 5. Consolidation & removal recommendations

Only **6 sections are registered** in `config.py:SECTION_MODULES`, yet there are
~198 `sections/` files and ~90 `utils/` files. A reachability trace from the 6
entrypoints (following static imports, `importlib.import_module` strings, and
`lazy_util` re-exports) identifies clear dead code and duplication.

> Caution: the repo's own `tools/contracts/cleanup_inventory.py` computes
> reachability from **static AST imports only** and roots at the dead
> `sections.executive_landing` facade, so it under-reports dynamic reachability.
> Each removal must also update `contracts/session_open_allowlist.py`,
> `contracts/direct_sql_allowlist.py`, `tools/contracts/retained_runtime_modules.py`,
> and the affected tests, which currently keep several dead modules "alive" only
> through text/allowlist references.

### Tier 1 — Remove (production-dead; referenced only by tests/contracts)

| Candidate | Files | Confidence | Notes |
|---|:--:|:--:|---|
| `sections/ui_compat.py` | 1 | Very high | Zero references anywhere in `.overwatch_final/`. |
| `sections/native_monitoring.py` | 1 | Very high | Only a text-scan test references it. |
| `sections/live_monitor.py` | 1 | Very high | Replaced by `contention_center`; a stale test still expects `live_monitor.render()`. |
| `sections/usage_overview.py` | 1 | Very high | No runtime importer. |
| `sections/adoption_analytics.py` | 1 | Very high | Route alias sets state; module never imported. |
| `sections/platform_topology.py` | 1 | Very high | Allowlist + tests only. |
| `sections/executive_landing.py` (facade) | 1 | High | Superseded by `executive_landing_shell.py`. |
| `sections/object_change_monitor.py` | 1 | High | Only reachable via the unwired `change_drift` contracts. |

### Tier 2 — Remove whole families (migration completed elsewhere)

| Candidate | Files | Confidence | Caution |
|---|:--:|:--:|---|
| `sections/account_health_*` | ~18 | High | Functionality absorbed into DBA Control Room. Keep `utils/mart_account_health.py` (still used by marts) and any setup DDL builders. |
| `sections/change_drift_*` | ~8 | High | Change Analysis uses `utils.change_intelligence` inline. Verify `change_drift_brief_view` retention references before deleting. |

### Tier 3 — Consolidate (keep behavior, shrink surface)

| Candidate | Action | Confidence |
|---|---|:--:|
| `sections/warehouse_health_*` (~18) | Fold render paths into `recommendations` / `cost_contract_advisor`; keep SQL/helper modules. | Medium-high |
| `query_analysis` + `query_investigation_root_cause` + `detailed_diagnosis` + `query_search` | Merge into one package with sub-renderers (already lazy-linked). | Medium |
| `cost_center_*` vs `cost_contract_*` | Inline `cost_center` views into `cost_contract_workflow`. | Medium (large refactor) |
| `sections/service_health.py` | Merge into `dba_control_room/health.py` (only used in an Admin expander). | Medium |
| `utils/ask_overwatch.py` | Remove if the Ask OVERWATCH UI is permanently gone (tests only prove evidence grounding). | Medium |

### Tier 4 — Do NOT remove without deep audit

`metric_semantic_registry.py` (central to all command briefs),
`decision_workspace_*` (shell bootstrap + every section first paint),
`section_command_*` / `button_action_contracts` (contract infra),
`contention_center.py`, `dba_tools_*`, and the `contracts/` allowlists.

Estimated impact: removing Tier 1–2 deletes **~33–43 files (~15–20% of
`sections/`)** with low risk, provided allowlists and tests are updated in the
same change.

---

## 6. Prioritized recommendations

### P0 — Highest value, low-to-moderate effort
1. **Fix cache invalidation semantics.** Make explicit "Refresh" and
   metric-settings changes call `clear_all_cache(clear_streamlit_cache=True)` (or
   `bump_global_cache_salt()`), and add `GLOBAL_SCHEMA`, `EXCEPTIONS_ONLY_MODE`,
   and credit/AI/storage rates to `_cache_context()` (`query.py:973-987`).
2. **Close the first-paint gap in production.** Defer
   `refresh_current_role_for_access` → `get_session()` until after first paint, or
   use a secrets-only role for the gate (`shell.py:123-127`). Consider enabling
   strict first-paint enforcement for `decision_packet` violations in prod.
3. **Remove Tier-1 dead files** and sync allowlists/tests. Immediate reduction in
   surface area and cognitive load with near-zero risk.
4. **Pin `jinja2`** in `requirements.txt` (used implicitly by
   `pandas.style.background_gradient` in `warehouse_health_view_heatmap.py:77`).

### P1 — Consistency & maintainability
5. **Split `theme.py`** into `tokens`, `streamlit-overrides`, `components`, and
   per-theme files; **unify the `--bg-*` and `--ow-*` token systems**; drive the
   `!important` count down by scoping overrides to a `body.overwatch-theme-*` class.
6. **Standardize section entry** on the shared Command Brief only — remove Alert
   Center's parallel `render_section_first_paint_shell` path and fix Workload
   Operations' double-brief render.
7. **Consolidate Tier-2 families** (`account_health_*`, `change_drift_*`).
8. **Reduce navigation depth** in Alert Center and DBA Control Room (merge status
   lenses into primary tabs or brief filters; one "Advanced diagnostics" entry).
9. **Batch column-compatibility probes** into a single `LIMIT 0` to cut N+1
   metadata queries (`compatibility.py:300-365`).

### P2 — Polish, accessibility, responsiveness
10. **Add a Command Brief skeleton state** to cover the gap between the transition
    overlay and the mart response.
11. **Accessibility pass**: minimum 12px (0.75rem) operational labels, WCAG-AA
    contrast audit for carbon muted text, remove `aria-hidden` misuse
    (`filters.py:352`), add `prefers-reduced-motion`, add a skip-to-main link.
12. **Fix cache-hit telemetry** — set `cache_layer` after execution and distinguish
    `cache_hit` from `use_cache` (`performance.py:1010`, `query.py:1352`).
13. **Cap or LRU-bound `section_dispatch._loaded`** for long-lived SiS workers.
14. **Fix narrow-viewport command bar** — stack the 5 filter columns below 900px.

### P3 — Strategic
15. **Retire dead UX hooks** (`render_setup_health_board`, `render_app_header`
    no-ops) or implement them.
16. **Surface the IA map** (section × workflow) and show a toast when a legacy
    alias resolves, so bookmarks remain trustworthy.
17. **Revisit `mart_loader` tier** — `historical`/3600s for "latest snapshot"
    control-room reads may hide freshness; consider `command_summary`/`standard`.

---

## 7. Bottom line

OVERWATCH is a **B, production-capable** application with an **A−-grade data
layer** and a **C+-grade UI maintainability story**. The fastest wins are
operational, not architectural: repair cache invalidation, close the
first-paint session gap, and delete the ~15–20% of `sections/` that is dead or
duplicated. Doing so raises real-world performance, shrinks maintenance cost,
and clears the way for the UI/UX polish (theme modularization, depth reduction,
accessibility) that would move the app from B to A−.
