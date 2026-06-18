# OVERWATCH Session State Contract

This contract defines the app-level Streamlit session keys owned by the
OVERWATCH shell after the Phase 1 app split. Section-specific workflow keys
remain owned by their section modules until they are intentionally migrated.

## Ownership Rules

- `runtime_state.py` is the registry for shell-owned keys.
- New app-level keys should be added to `runtime_state.py` before use.
- Shell modules must use `get_state()`, `set_state()`, `pop_state()`,
  `ensure_default_state()`, or `clear_scoped_state()` instead of direct
  `st.session_state["..."]`, `.get(...)`, `.pop(...)`, or `.setdefault(...)`.
- Shared platform utilities that own Snowflake sessions, query execution, and
  cache invalidation must follow the same wrapper rule. Today that includes
  `utils.session`, `utils.query`, and `utils.cache`.
- Global filter SQL helpers are also shared platform code; `utils.company_filter`
  reads filter state through the wrapper layer.
- Idle/pause behavior is production safety state, so `utils.idle` also uses
  runtime-state constants and helpers.
- Snowflake compatibility and metadata probe caches are shared platform state;
  `utils.compatibility` and `utils.metadata` use runtime-state constants for
  those cache keys.
- First-paint command board cache state is shared by multiple top-level
  sections; `utils.command_board` must use the wrapper layer for those keys.
- Persistent recommendation/action queue metadata is shared platform state;
  `utils.action_queue` uses the wrapper layer for role, actor, and metadata
  cache keys.
- Section modules may keep local workflow keys when the state is not shared
  outside that section.
- Compatibility keys for retired routes are routed through constants and
  `set_state()` in `sections.navigation`.

## Persistent Shell Keys

- `active_company`
- `global_start_date`
- `global_end_date`
- `global_environment`
- `credit_price`
- `ai_credit_price`
- `storage_cost_per_tb`
- `alert_email_targets`
- `_overwatch_current_role`
- `_overwatch_current_role_source`

## Filter Keys

These keys define the global filter signature and invalidate loaded telemetry
when they change:

- `_global_date_range_input`
- `global_warehouse`
- `global_user`
- `global_role`
- `global_database`
- `global_schema`
- `global_environment`
- `global_warehouse_select`
- `global_database_select`
- `global_schema_select`
- `global_warehouse_options`
- `global_database_options`
- `global_schema_options`

## Transient Shell Keys

These keys coordinate navigation, transition state, cache invalidation, and
runtime shell behavior:

- `nav_section`
- `_overwatch_active_section`
- `_overwatch_pending_section`
- `_overwatch_pending_autoload_section`
- `_overwatch_pending_autoload_started_at`
- `_overwatch_section_transition_started_at`
- `_overwatch_last_rendered_section`
- `_overwatch_last_section_render_signature`
- `_overwatch_last_section_render_ms`
- `_overwatch_connection_available`
- `_overwatch_connection_unavailable`
- `_overwatch_connection_surface`
- `_overwatch_secondary_chrome_ready`
- `_prev_global_filter_signature`
- `_prev_metric_settings_signature`
- `_overwatch_sidebar_panel`
- `_overwatch_last_operator_activity_ts`
- `_overwatch_queries_paused`
- `_overwatch_query_paused_at_ts`
- `_overwatch_query_pause_reason`
- `_overwatch_query_pause_warning_shown*`

## Cache And Snowflake Session Keys

- `sf_session`
- `_sf_session_created_at`
- `_overwatch_active_query_tag`
- `_overwatch_active_query_tag_section`
- `_overwatch_query_telemetry`
- `_overwatch_query_budget_hits`
- `_overwatch_query_budget_warning_hashes`
- `_overwatch_query_warning_hashes`
- `_overwatch_result_guard_warning_hashes`
- `_overwatch_statement_timeout_seconds`
- `_overwatch_query_budget_window_started_at`
- `_overwatch_query_budget_window_count`
- `_overwatch_query_budget_window_warned`
- `_refresh_salt_global`
- `_overwatch_available_columns`
- `_overwatch_unavailable_column_views`
- `_overwatch_column_probe`
- `_overwatch_show_statement_cache`

The shell may clear `sf_session` and `_sf_session_created_at` from the retry
connection action. Query-tag keys are owned by `utils.session` because they are
Snowflake session attributes rather than layout state. Query telemetry and
refresh salt keys are owned by `utils.query` and `utils.cache`, but the key
names still live in `runtime_state.py`.

## Known Exceptions

- `runtime_state.py` is the only app-shell module allowed to directly call
  `st.session_state["..."]`, `.get(...)`, `.pop(...)`, or `.setdefault(...)`.
- `utils.cache` may enumerate `st.session_state.keys()` to purge dynamic
  section cache prefixes, but it must delete entries through `pop_state()`.
- `utils.company_filter` may enumerate `st.session_state.keys()` for company
  scope invalidation, but it must delete entries through `pop_state()`.
- `sections.navigation` may set section-specific workflow keys, but the key
  names must be constants imported from `runtime_state.py`.
- Existing section modules still contain many raw `st.session_state` keys. That
  is intentionally outside Phase 1 and should be handled section-by-section.
- Streamlit widget keys should use constants when static. Dynamic widget keys,
  such as per-section navigation buttons built from a prefix plus section name,
  are allowed because Streamlit requires stable unique IDs per widget instance.
