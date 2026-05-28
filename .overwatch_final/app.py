# app.py — OVERWATCH V3 · Main Entry Point
# ─────────────────────────────────────────────────────────────────────────────
# Includes:
#   - Role-based section visibility (ROLE_SECTIONS in config.py)
#   - ALFA default company seeded before radio renders
#   - Cache invalidation on company switch
#   - Saved Views / Bookmarks sidebar panel
# ─────────────────────────────────────────────────────────────────────────────
import streamlit as st
from datetime import datetime, timedelta

st.set_page_config(
    page_title="OVERWATCH — Snowflake DBA Monitor",
    page_icon="👁️",
    layout="wide",
    initial_sidebar_state="expanded",
)

from theme import inject_theme, render_theme_picker
from config import (
    ALL_SECTIONS, NAV_GROUPS, DEFAULTS, COMPANY_CONFIG,
    DEFAULT_COMPANY, ROLE_SECTIONS,
)
from utils.display import clear_all_cache
from utils.session import get_session
from utils.query import sql_literal
from utils.company_filter import invalidate_company_cache
from utils.bookmarks import (
    build_bookmark_ddl, save_bookmark, load_bookmarks,
    apply_bookmark, delete_bookmark,
)
import sections

inject_theme()

# ── Seed ALFA default before radio ────────────────────────────────────────────
if "active_company" not in st.session_state:
    st.session_state["active_company"] = DEFAULT_COMPANY


# ── Role resolution (cached 5 min) ────────────────────────────────────────────
def _get_current_role() -> str:
    try:
        return (get_session().sql("SELECT CURRENT_ROLE() AS r").collect()[0]["R"] or "").upper()
    except Exception:
        return ""


def _resolve_visible_sections() -> list[str]:
    role = _get_current_role()
    for key, sec_list in ROLE_SECTIONS.items():
        if key in role:
            return sec_list
    return ALL_SECTIONS


NAV_ALIASES = {
    "Usage Overview": "📊 Usage Overview",
    "Adoption Analytics": "📈 Adoption Analytics",
    "Service Health": "🩺 Service Health",
    "Detailed Diagnosis": "🧪 Detailed Diagnosis",
    "Pipeline Health": "🚚 Pipeline Health",
    "Platform Topology": "🕸️ Platform Topology",
    "Credit Contract": "📉 Credit Contract",
    "Snowflake Value": "🏆 Snowflake Value",
    "💡 Optimization": "🏭 Warehouse Health",
}


def _normalize_nav_section(section: str) -> str:
    return NAV_ALIASES.get(section, section)


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    # Header
    st.markdown("""
    <div style="text-align:center; padding:16px 0;">
        <div style="font-size:2.5rem; margin-bottom:4px;">👁️</div>
        <div style="font-size:1.2rem; font-weight:800;
                    background:linear-gradient(90deg,#38bdf8,#818cf8);
                    -webkit-background-clip:text; -webkit-text-fill-color:transparent;">
            OVERWATCH
        </div>
        <div style="font-size:0.7rem; color:#64748b; letter-spacing:2px; text-transform:uppercase;">
            Snowflake DBA Command Center
        </div>
        <div style="margin-top:8px;">
            <span class="status-badge badge-healthy live-indicator">● LIVE</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    # ── Company filter ────────────────────────────────────────────────────────
    _prev_company = st.session_state.get("_prev_active_company", DEFAULT_COMPANY)
    active_company = st.radio(
        "Company view",
        list(COMPANY_CONFIG.keys()),
        horizontal=True,
        key="active_company",
    )
    if _prev_company != active_company:
        invalidate_company_cache()
    st.session_state["_prev_active_company"] = active_company

    st.divider()

    # ── Navigation ────────────────────────────────────────────────────────────
    visible_sections = _resolve_visible_sections()
    current_role     = _get_current_role()
    matched_profile  = next((k for k in ROLE_SECTIONS if k in current_role), "DBA")
    profile_color    = {
        "ANALYST": "#fbbf24", "MANAGER": "#c084fc", "REPORT": "#fbbf24",
    }.get(matched_profile, "#38bdf8")
    role_label = current_role[:20] or "DBA"

    with st.expander("Command Palette", expanded=False):
        cmd = st.text_input(
            "Search or jump",
            placeholder="warehouse, user, query_id, task, database, cost, alerts",
            key="command_palette_input",
        )
        cmd_type = st.selectbox(
            "Target",
            ["Auto", "Warehouse", "User", "Query ID", "Task", "Database", "Section"],
            key="command_palette_type",
        )
        if st.button("Go", key="command_palette_go", disabled=not cmd):
            value = str(cmd).strip()
            upper = value.upper()
            target = "🏠 Account Health"
            if cmd_type == "Warehouse" or (cmd_type == "Auto" and ("WH" in upper or "WAREHOUSE" in upper)):
                st.session_state["global_warehouse"] = value
                st.session_state["wh_filter"] = value
                target = "🏭 Warehouse Health"
            elif cmd_type == "User":
                st.session_state["global_user"] = value
                target = "💸 Cost Center"
            elif cmd_type == "Query ID" or (cmd_type == "Auto" and len(value) >= 20 and "-" in value):
                st.session_state["qs_qid"] = value
                target = "🕰️ Query Search & History"
            elif cmd_type == "Task" or (cmd_type == "Auto" and "TASK" in upper):
                st.session_state["tm_search"] = value
                target = "⚙️ Task Management"
            elif cmd_type == "Database" or (cmd_type == "Auto" and upper.startswith(("DB_", "ALFA", "TRXS"))):
                st.session_state["global_database"] = value
                target = "🗄️ Storage Monitor"
            elif "COST" in upper or "SPEND" in upper:
                target = "💸 Cost Center"
            elif "ALERT" in upper or "RECOMMEND" in upper or "ACTION" in upper:
                target = "💡 Recommendations & Anomalies"
            elif "VALUE" in upper or "ROI" in upper or "SAVING" in upper:
                target = "🏆 Snowflake Value"
            elif "DBA" in upper or "WAREHOUSE SETTING" in upper:
                target = "🛠️ DBA Tools"
            else:
                for section in visible_sections:
                    if upper in section.upper():
                        target = section
                        break
            st.session_state["nav_section"] = target if target in visible_sections else visible_sections[0]
            st.rerun()

    st.caption(f"{role_label} · {matched_profile} VIEW")
    st.caption("NAVIGATE")

    active_section = _normalize_nav_section(st.session_state.get("nav_section", visible_sections[0]))
    if active_section not in visible_sections:
        active_section = visible_sections[0]
        st.session_state["nav_section"] = active_section

    def _set_section(section: str) -> None:
        st.session_state["nav_section"] = section

    for group_name, group_all in NAV_GROUPS.items():
        group_visible = [s for s in group_all if s in visible_sections]
        if not group_visible:
            continue
        st.caption(group_name)
        for section_name in group_visible:
            is_active = section_name == active_section
            st.button(
                f"● {section_name}" if is_active else section_name,
                key=f"nav_btn_{group_name}_{section_name}",
                type="primary" if is_active else "secondary",
                use_container_width=True,
                on_click=_set_section,
                args=(section_name,),
            )

    st.divider()

    # ── Saved Views / Bookmarks ───────────────────────────────────────────────
    with st.expander("🔖 Saved Views", expanded=False):
        try:
            _session = get_session()
        except Exception as e:
            _session = None
            st.caption(f"Saved views unavailable until Snowflake is connected. ({e})")
        bookmarks = load_bookmarks(_session) if _session else []

        if bookmarks:
            st.caption("Click a bookmark to jump directly to that view.")
            for bm in bookmarks:
                shared_badge = " 🌐" if bm["shared"] else ""
                uses_badge   = f" · {bm['uses']}×" if bm["uses"] else ""
                col_bm, col_del = st.columns([5, 1])
                with col_bm:
                    if st.button(
                        f"{'📌' if bm['shared'] else '🔖'} {bm['name']}{shared_badge}{uses_badge}",
                        key=f"bm_apply_{bm['id']}",
                        help=f"Section: {bm['section']}\nCreated: {bm['created']}",
                        use_container_width=True,
                    ):
                        apply_bookmark(_session, bm)  # calls st.rerun()
                with col_del:
                    if st.button("✕", key=f"bm_del_{bm['id']}", help="Delete bookmark"):
                        if delete_bookmark(_session, bm["id"]):
                            st.rerun()
        else:
            st.caption("No saved views yet.")

        st.divider()
        st.caption("Save current view")
        new_bm_name = st.text_input(
            "Bookmark name",
            placeholder="e.g. Monday Credit Check",
            label_visibility="collapsed",
            key="bm_name_input",
            max_chars=100,
        )
        bm_shared = st.checkbox("Share with all users", key="bm_shared_toggle")
        if st.button("💾 Save View", key="bm_save_btn", disabled=not new_bm_name):
            if not _session:
                st.warning("Connect Snowflake before saving views.")
            elif save_bookmark(_session, new_bm_name, bm_shared):
                st.success(f"✅ Saved '{new_bm_name}'")
                st.session_state.pop("bm_name_input", None)
                st.rerun()

        # Setup DDL (hidden until needed)
        with st.expander("📋 Setup DDL", expanded=False):
            ddl = build_bookmark_ddl()
            st.code(ddl[:400] + "...", language="sql")
            st.download_button(
                "📥 Full DDL",
                ddl,
                file_name="overwatch_bookmarks_setup.sql",
                mime="text/plain",
                key="bm_ddl_dl",
            )

    st.divider()

    # ── Settings ──────────────────────────────────────────────────────────────
    with st.expander("Global Filters", expanded=False):
        default_end = datetime.now().date()
        default_start = default_end - timedelta(days=7)
        date_range = st.date_input(
            "Date range",
            value=(
                st.session_state.get("global_start_date", default_start),
                st.session_state.get("global_end_date", default_end),
            ),
            key="_global_date_range_input",
        )
        if isinstance(date_range, tuple) and len(date_range) == 2:
            st.session_state["global_start_date"] = date_range[0]
            st.session_state["global_end_date"] = date_range[1]
        st.text_input("Warehouse contains", key="global_warehouse")
        st.text_input("User contains", key="global_user")
        st.text_input("Role contains", key="global_role")
        st.text_input("Database contains", key="global_database")

        if st.button("Clear Global Filters", key="global_filters_clear"):
            for _k in [
                "global_start_date", "global_end_date", "global_warehouse",
                "global_user", "global_role", "global_database",
                "_global_date_range_input",
            ]:
                st.session_state.pop(_k, None)
            clear_all_cache()
            st.rerun()

    st.divider()

    with st.expander("⚙️ Settings", expanded=False):
        render_theme_picker()
        st.divider()
        credit_price = st.number_input(
            "$/credit (compute)",
            min_value=0.50, max_value=20.00,
            value=st.session_state.get("credit_price", DEFAULTS["credit_price"]),
            step=0.10, key="_credit_price_input",
        )
        st.session_state["credit_price"] = credit_price

        storage_cost = st.number_input(
            "$/TB/month (storage)",
            min_value=1.0, max_value=100.0,
            value=st.session_state.get("storage_cost_per_tb", DEFAULTS["storage_cost_per_tb"]),
            step=1.0, key="_storage_cost_input",
        )
        st.session_state["storage_cost_per_tb"] = storage_cost

        st.selectbox(
            "Live refresh interval",
            [15, 30, 60, 120], index=1,
            format_func=lambda x: f"{x}s",
            key="rt_interval",
        )

    st.divider()

    company_color = COMPANY_CONFIG.get(active_company, {}).get("color", "#38bdf8")
    st.markdown(f"""
    <div style="font-size:0.65rem; color:#475569; text-align:center;">
        <div style="color:{company_color}; font-weight:700; margin-bottom:4px;">{active_company} view</div>
        <div>💰 ${credit_price:.2f}/credit</div>
        <div style="margin-top:4px;">ACCOUNT_USAGE ≤45min lag · IS: live</div>
    </div>
    """, unsafe_allow_html=True)


# ── Main header ───────────────────────────────────────────────────────────────
h1, h2, h3 = st.columns([3, 2, 1])
with h1:
    company_color = COMPANY_CONFIG.get(active_company, {}).get("color", "#38bdf8")
    st.markdown(f"""
    <h1 style="margin:0;padding:0;font-size:2rem;">
        👁️ OVERWATCH
        <span style="font-size:0.75rem;font-weight:400;color:{company_color};
                     background:rgba(255,255,255,0.05);border:1px solid {company_color}33;
                     border-radius:4px;padding:2px 8px;margin-left:8px;">{active_company}</span>
    </h1>
    """, unsafe_allow_html=True)
with h2:
    st.markdown(f"""
    <div style="text-align:right;padding-top:12px;">
        <span style="color:#64748b;font-size:0.75rem;">
            {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · ${credit_price:.2f}/cr
        </span>
    </div>
    """, unsafe_allow_html=True)
with h3:
    if st.button("🔄 Refresh All", key="global_refresh"):
        clear_all_cache()
        st.rerun()

# ── Ask OVERWATCH ─────────────────────────────────────────────────────────────
with st.expander("🤖 Ask OVERWATCH  (Cortex AI)", expanded=False):
    ask_q = st.text_input(
        "Ask a question about your Snowflake usage...",
        placeholder="e.g. Who spent the most credits last week?",
        key="ask_overwatch_input",
        max_chars=500,
    )
    if ask_q and st.button("Ask", key="ask_overwatch_btn"):
        with st.spinner("Thinking with Cortex..."):
            try:
                safe_q      = ask_q.strip()[:500]
                prompt      = (
                    "You are OVERWATCH, a Snowflake monitoring assistant for ALFA Insurance. "
                    f"Current company filter: {active_company}. "
                    f"User role: {current_role or 'unknown'}. "
                    f'The user asked: "{safe_q}" '
                    "Respond with: 1) a concise answer, 2) which OVERWATCH section to navigate to, "
                    "3) recommended filters. Be brief and technical."
                )
                result = get_session().sql(
                    f"SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large2', {sql_literal(prompt)}) AS answer"
                ).collect()
                st.markdown(result[0]["ANSWER"])
            except Exception as e:
                st.info(f"Cortex AI unavailable ({e}).")

st.markdown("---")

# ── Section dispatch ──────────────────────────────────────────────────────────
active_section = _normalize_nav_section(st.session_state.get("nav_section", visible_sections[0]))
if active_section not in visible_sections:
    active_section = visible_sections[0]
    st.session_state["nav_section"] = active_section

try:
    sections.dispatch(active_section)
except Exception as e:
    st.warning("Snowflake is not connected yet, so this section cannot load live data.")
    st.caption(str(e))
    st.info(
        "Add Snowflake credentials in Streamlit secrets or run inside Snowsight with an active session, "
        "then refresh the app."
    )
