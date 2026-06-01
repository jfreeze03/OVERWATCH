# theme.py — OVERWATCH V3 · 5-theme system
# ─────────────────────────────────────────────────────────────────────────────
# THEMES:
#   1. midnight   — Original dark glassmorphism (cyan/indigo/purple)
#   2. corporate  — Traditional light: white cards, navy sidebar, ALFA blue
#   3. terminal   — Snowflake White: classic white with Snowflake blue
#   4. black_ice  — Dark high-contrast lime/cyan accents
#   5. carbon     — Snowflake Dark: classic dark with Snowflake blue
#
# Architecture: All structural styles reference CSS custom properties.
# Switching theme = injecting a new :root { } block. Zero JS required.
# Theme picker renders as 5 clickable swatches in the sidebar Settings.
# Preference persists in session_state; optional DB persistence via Bookmarks.
#
# Usage in app.py:
#   from theme import inject_theme, render_theme_picker
#   inject_theme()
#   # inside sidebar Settings expander:
#   render_theme_picker()
# ─────────────────────────────────────────────────────────────────────────────
import streamlit as st

THEME_VERSION = "2026-05-31-compact-workflow-ui-v2"

_DEFAULT_THEME = "midnight"
_THEME_ALIASES = {
    "aurora": "black_ice",
}

# ── Theme metadata (used for the picker UI) ───────────────────────────────────
THEMES = {
    "midnight": {
        "label":    "Henson Basic",
        "swatch":   "#38bdf8",
        "bg":       "#0a0e1a",
    },
    "corporate": {
        "label":    "ALFA",
        "swatch":   "#b00020",
        "bg":       "#ffffff",
    },
    "terminal": {
        "label":    "Snowflake White",
        "swatch":   "#29B5E8",
        "bg":       "#ffffff",
    },
    "black_ice": {
        "label":    "Black Ice",
        "swatch":   "#a3e635",
        "bg":       "#05070b",
    },
    "carbon": {
        "label":    "Snowflake Dark",
        "swatch":   "#29B5E8",
        "bg":       "#0B1117",
    },
}

# ── CSS variable blocks — one per theme ───────────────────────────────────────

_VARS = {

# ─── 1. MIDNIGHT — original dark glassmorphism ───────────────────────────────
"midnight": """
:root {
    --bg-app:          linear-gradient(135deg, #0a0e1a 0%, #0d1525 50%, #0a1628 100%);
    --bg-sidebar:      linear-gradient(180deg, #0d1525 0%, #111d33 100%);
    --bg-card:         rgba(15, 23, 42, 0.60);
    --bg-card-hover:   rgba(15, 23, 42, 0.85);
    --bg-input:        rgba(15, 23, 42, 0.80);
    --bg-tab-list:     rgba(15, 23, 42, 0.40);
    --bg-expander:     rgba(15, 23, 42, 0.40);

    --border-subtle:   rgba(56, 189, 248, 0.10);
    --border-normal:   rgba(56, 189, 248, 0.20);
    --border-strong:   rgba(56, 189, 248, 0.45);
    --border-sidebar:  rgba(56, 189, 248, 0.10);

    --text-primary:    #e2e8f0;
    --text-secondary:  #94a3b8;
    --text-muted:      #64748b;
    --text-input:      #e2e8f0;
    --text-heading:    transparent;

    --accent:          #38bdf8;
    --accent-rgb:      56, 189, 248;
    --accent2:         #818cf8;
    --accent3:         #c084fc;
    --h1-gradient:     linear-gradient(90deg, #38bdf8, #818cf8, #c084fc);

    --metric-shadow:        0 4px 24px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.05);
    --metric-hover-shadow:  0 8px 32px rgba(56,189,248,0.12), inset 0 1px 0 rgba(255,255,255,0.08);
    --btn-bg:          linear-gradient(135deg, rgba(56,189,248,0.15), rgba(129,140,248,0.15));
    --btn-bg-hover:    linear-gradient(135deg, rgba(56,189,248,0.30), rgba(129,140,248,0.30));
    --btn-border:      rgba(56, 189, 248, 0.30);
    --btn-hover-shadow: 0 0 20px rgba(56,189,248,0.20);
    --slider-track:    linear-gradient(90deg, #2563eb, #38bdf8);
    --tab-active-bg:   rgba(56, 189, 248, 0.15);
    --tab-active-col:  #38bdf8;
    --hr-bg:           linear-gradient(90deg, transparent, rgba(56,189,248,0.30), transparent);
    --scrollbar-track: rgba(15, 23, 42, 0.50);
    --scrollbar-thumb: rgba(56, 189, 248, 0.30);
    --scrollbar-hover: rgba(56, 189, 248, 0.55);
    --font-body:       'Inter', 'DM Sans', system-ui, sans-serif;
    --font-mono:       'DM Mono', 'Fira Code', monospace;
    --extra-css:       '';
}
""",

# ─── 2. CORPORATE — traditional light, navy sidebar, ALFA blue ───────────────
"corporate": """
:root {
    --bg-app:          #ffffff;
    --bg-sidebar:      #ffffff;
    --bg-card:         #ffffff;
    --bg-card-hover:   #f8fafc;
    --bg-input:        #ffffff;
    --bg-tab-list:     #f1f5f9;
    --bg-expander:     #ffffff;

    --border-subtle:   #e5e7eb;
    --border-normal:   #cbd5e1;
    --border-strong:   #0f7894;
    --border-sidebar:  #e2e8f0;

    --text-primary:    #1f2937;
    --text-secondary:  #334155;
    --text-muted:      #64748b;
    --text-input:      #111827;
    --text-heading:    #b00020;

    --accent:          #b00020;
    --accent-rgb:      176, 0, 32;
    --accent2:         #0f7894;
    --accent3:         #475569;
    --h1-gradient:     linear-gradient(90deg, #b00020 0%, #b00020 44%, #3f3f46 44%, #3f3f46 100%);

    --metric-shadow:        0 1px 10px rgba(15, 23, 42, 0.06), 0 1px 2px rgba(15, 23, 42, 0.05);
    --metric-hover-shadow:  0 8px 24px rgba(15, 120, 148, 0.16), 0 2px 8px rgba(15, 23, 42, 0.08);
    --btn-bg:          #ffffff;
    --btn-bg-hover:    #f8fafc;
    --btn-border:      rgba(15, 120, 148, 0.46);
    --btn-hover-shadow: 0 2px 12px rgba(15, 120, 148, 0.18);
    --slider-track:    linear-gradient(90deg, #b00020, #0f7894);
    --tab-active-bg:   rgba(176, 0, 32, 0.08);
    --tab-active-col:  #b00020;
    --hr-bg:           linear-gradient(90deg, transparent, #e2e8f0, transparent);
    --scrollbar-track: #f1f5f9;
    --scrollbar-thumb: rgba(15, 120, 148, 0.34);
    --scrollbar-hover: rgba(176, 0, 32, 0.35);
    --font-body:       'Inter', 'DM Sans', 'Segoe UI', system-ui, sans-serif;
    --font-mono:       'DM Mono', 'Cascadia Mono', monospace;
    --extra-css:       '';
}
""",

# ─── 3. SNOWFLAKE WHITE — classic white with Snowflake brand blues ───────────
"terminal": """
:root {
    --bg-app:          #ffffff;
    --bg-sidebar:      #f7fbfd;
    --bg-card:         #ffffff;
    --bg-card-hover:   #f3f8fb;
    --bg-input:        #ffffff;
    --bg-tab-list:     #eef7fb;
    --bg-expander:     #ffffff;

    --border-subtle:   #d9ebf3;
    --border-normal:   #b8d8e5;
    --border-strong:   #29B5E8;
    --border-sidebar:  #d7e8f0;

    --text-primary:    #24323D;
    --text-secondary:  #11567F;
    --text-muted:      #5f7180;
    --text-input:      #24323D;
    --text-heading:    #003545;

    --accent:          #29B5E8;
    --accent-rgb:      41, 181, 232;
    --accent2:         #11567F;
    --accent3:         #71D3DC;
    --h1-gradient:     linear-gradient(90deg, #003545, #11567F, #29B5E8);

    --metric-shadow:        0 1px 10px rgba(0, 53, 69, 0.08), 0 1px 2px rgba(0, 53, 69, 0.06);
    --metric-hover-shadow:  0 8px 24px rgba(41, 181, 232, 0.18), 0 2px 8px rgba(0, 53, 69, 0.08);
    --btn-bg:          #ffffff;
    --btn-bg-hover:    #eef7fb;
    --btn-border:      rgba(41, 181, 232, 0.46);
    --btn-hover-shadow: 0 2px 14px rgba(41, 181, 232, 0.22);
    --slider-track:    linear-gradient(90deg, #11567F, #29B5E8);
    --tab-active-bg:   rgba(41, 181, 232, 0.13);
    --tab-active-col:  #11567F;
    --hr-bg:           linear-gradient(90deg, transparent, #cfe6ef, transparent);
    --scrollbar-track: #eef7fb;
    --scrollbar-thumb: rgba(41, 181, 232, 0.35);
    --scrollbar-hover: rgba(17, 86, 127, 0.45);
    --font-body:       'Lato', 'Inter', 'DM Sans', 'Segoe UI', system-ui, sans-serif;
    --font-mono:       'DM Mono', 'Cascadia Mono', monospace;
    --extra-css:       '';
}
""",

# ─── 4. BLACK ICE — high-contrast dark with lime/cyan accents ────────
"black_ice": """
:root {
    --bg-app:          linear-gradient(160deg, #05070b 0%, #0b1220 48%, #111827 100%);
    --bg-sidebar:      linear-gradient(180deg, #05070b 0%, #0b1220 58%, #111827 100%);
    --bg-card:         rgba(8, 13, 24, 0.78);
    --bg-card-hover:   rgba(12, 20, 35, 0.94);
    --bg-input:        rgba(5, 8, 15, 0.92);
    --bg-tab-list:     rgba(10, 16, 28, 0.66);
    --bg-expander:     rgba(8, 13, 24, 0.76);

    --border-subtle:   rgba(163, 230, 53, 0.12);
    --border-normal:   rgba(163, 230, 53, 0.26);
    --border-strong:   rgba(34, 211, 238, 0.62);
    --border-sidebar:  rgba(163, 230, 53, 0.16);

    --text-primary:    #f8fafc;
    --text-secondary:  #d9f99d;
    --text-muted:      #94a3b8;
    --text-input:      #f8fafc;
    --text-heading:    transparent;

    --accent:          #a3e635;
    --accent-rgb:      163, 230, 53;
    --accent2:         #22d3ee;
    --accent3:         #38bdf8;
    --h1-gradient:     linear-gradient(90deg, #f8fafc, #a3e635, #22d3ee);

    --metric-shadow:        0 4px 24px rgba(0,0,0,0.50), inset 0 1px 0 rgba(163,230,53,0.08);
    --metric-hover-shadow:  0 8px 32px rgba(163,230,53,0.16), inset 0 1px 0 rgba(34,211,238,0.12);
    --btn-bg:          linear-gradient(135deg, rgba(163,230,53,0.12), rgba(34,211,238,0.10));
    --btn-bg-hover:    linear-gradient(135deg, rgba(163,230,53,0.25), rgba(34,211,238,0.20));
    --btn-border:      rgba(163, 230, 53, 0.34);
    --btn-hover-shadow: 0 0 20px rgba(163,230,53,0.24);
    --slider-track:    linear-gradient(90deg, #a3e635, #22d3ee);
    --tab-active-bg:   rgba(163, 230, 53, 0.14);
    --tab-active-col:  #d9f99d;
    --hr-bg:           linear-gradient(90deg, transparent, rgba(163,230,53,0.28), transparent);
    --scrollbar-track: rgba(5, 8, 15, 0.72);
    --scrollbar-thumb: rgba(163, 230, 53, 0.32);
    --scrollbar-hover: rgba(34, 211, 238, 0.56);
    --font-body:       'Inter', system-ui, sans-serif;
    --font-mono:       'JetBrains Mono', 'Cascadia Mono', monospace;
    --extra-css:       '';
}
""",

# ─── 5. SNOWFLAKE DARK — classic dark with Snowflake brand blues ─────────────
"carbon": """
:root {
    --bg-app:          linear-gradient(160deg, #0B1117 0%, #101A22 48%, #003545 100%);
    --bg-sidebar:      linear-gradient(180deg, #071018 0%, #0D1B24 55%, #003545 100%);
    --bg-card:         rgba(13, 27, 36, 0.82);
    --bg-card-hover:   rgba(18, 42, 55, 0.96);
    --bg-input:        rgba(6, 16, 23, 0.92);
    --bg-tab-list:     rgba(11, 27, 38, 0.66);
    --bg-expander:     rgba(10, 24, 32, 0.76);

    --border-subtle:   rgba(41, 181, 232, 0.12);
    --border-normal:   rgba(41, 181, 232, 0.26);
    --border-strong:   rgba(41, 181, 232, 0.62);
    --border-sidebar:  rgba(113, 211, 220, 0.16);

    --text-primary:    #eef8fb;
    --text-secondary:  #9bddea;
    --text-muted:      #7b9cab;
    --text-input:      #eef8fb;
    --text-heading:    transparent;

    --accent:          #29B5E8;
    --accent-rgb:      41, 181, 232;
    --accent2:         #71D3DC;
    --accent3:         #11567F;
    --h1-gradient:     linear-gradient(90deg, #eef8fb, #71D3DC, #29B5E8);

    --metric-shadow:        0 4px 24px rgba(0,0,0,0.48), inset 0 1px 0 rgba(113,211,220,0.08);
    --metric-hover-shadow:  0 8px 32px rgba(41,181,232,0.16), inset 0 1px 0 rgba(113,211,220,0.12);
    --btn-bg:          linear-gradient(135deg, rgba(41,181,232,0.12), rgba(113,211,220,0.10));
    --btn-bg-hover:    linear-gradient(135deg, rgba(41,181,232,0.28), rgba(113,211,220,0.22));
    --btn-border:      rgba(41, 181, 232, 0.34);
    --btn-hover-shadow: 0 0 20px rgba(41,181,232,0.24);
    --slider-track:    linear-gradient(90deg, #11567F, #29B5E8);
    --tab-active-bg:   rgba(41, 181, 232, 0.15);
    --tab-active-col:  #71D3DC;
    --hr-bg:           linear-gradient(90deg, transparent, rgba(41,181,232,0.32), transparent);
    --scrollbar-track: rgba(3, 12, 18, 0.70);
    --scrollbar-thumb: rgba(41, 181, 232, 0.32);
    --scrollbar-hover: rgba(113, 211, 220, 0.56);
    --font-body:       'Lato', 'Inter', 'DM Sans', system-ui, sans-serif;
    --font-mono:       'DM Mono', 'Cascadia Mono', monospace;
    --extra-css:       '';
}
""",
}

# ── Shared structural styles (all colors via variables) ───────────────────────
_STRUCTURAL_CSS = """
<style>
{vars}

/* ═══════════════════════════════════════════ OVERWATCH V3 THEME ENGINE ═══ */

/* ── Base ── */
.stApp, .stApp > * {
    background: var(--bg-app) !important;
    font-family: var(--font-body) !important;
}
.block-container {
    padding-top: 1rem !important;
    padding-bottom: 2rem !important;
    max-width: 1500px !important;
}
[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stDecoration"],
#MainMenu,
footer {
    display: none !important;
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: var(--bg-sidebar) !important;
    border-right: 1px solid var(--border-sidebar) !important;
}
[data-testid="stSidebar"] .stRadio > label,
[data-testid="stSidebar"] label {
    color: var(--text-secondary) !important;
    font-family: var(--font-body) !important;
}
[data-testid="stIconMaterial"],
[data-testid="stIconMaterial"] *,
.stApp span[class*="material"],
.stApp i[class*="material"] {
    display: inline-block !important;
    width: 0 !important;
    min-width: 0 !important;
    max-width: 0 !important;
    height: 0 !important;
    overflow: hidden !important;
    color: transparent !important;
    font-size: 0 !important;
    line-height: 0 !important;
    opacity: 0 !important;
}
[data-testid="stIconMaterial"]::before,
[data-testid="stIconMaterial"]::after,
.stApp span[class*="material"]::before,
.stApp span[class*="material"]::after {
    content: "" !important;
    display: none !important;
}
[data-testid="stSidebar"] .stRadio > div > label:hover {
    color: var(--accent) !important;
    background: rgba(var(--accent-rgb), 0.06);
    border-radius: 6px;
}
[data-testid="stSidebar"] .stRadio > div > label[data-checked="true"] {
    background: rgba(var(--accent-rgb), 0.12);
    border-left: 3px solid var(--accent);
    padding-left: 12px;
    border-radius: 0 6px 6px 0;
}

/* ── Metric cards ── */
[data-testid="stMetric"] {
    background: var(--bg-card) !important;
    backdrop-filter: blur(12px);
    border: 1px solid var(--border-subtle) !important;
    border-radius: 8px !important;
    padding: 12px 14px !important;
    box-shadow: var(--metric-shadow) !important;
    transition: border-color 0.18s ease, box-shadow 0.18s ease;
}
[data-testid="stMetric"]:hover {
    border-color: var(--border-strong) !important;
    box-shadow: var(--metric-hover-shadow) !important;
}
[data-testid="stMetricLabel"] {
    color: var(--text-muted) !important;
    font-size: 0.72rem !important;
    text-transform: uppercase;
    letter-spacing: 0;
    font-family: var(--font-body) !important;
}
[data-testid="stMetricValue"] {
    color: var(--text-primary) !important;
    font-weight: 700 !important;
    font-size: 1.35rem !important;
    font-family: var(--font-body) !important;
}

/* ── Headings ── */
h1 {
    background: var(--h1-gradient) !important;
    -webkit-background-clip: text !important;
    -webkit-text-fill-color: transparent !important;
    background-clip: text !important;
    font-weight: 800 !important;
    letter-spacing: 0;
    font-family: var(--font-body) !important;
}
h2, h3 {
    color: var(--text-primary) !important;
    border-bottom: 0;
    padding-bottom: 2px;
    margin-top: 0.55rem !important;
    font-family: var(--font-body) !important;
}
p, li { color: var(--text-primary); font-family: var(--font-body) !important; }
[data-testid="stMarkdownContainer"],
[data-testid="stMarkdownContainer"] *:not([class*="icon"]):not([class*="material"]) {
    color: inherit;
    font-family: var(--font-body);
}

/* ── DataFrames ── */
[data-testid="stDataFrame"] {
    border: 1px solid var(--border-subtle) !important;
    border-radius: 8px;
    overflow: hidden;
}

/* ── Buttons ── */
.stButton > button {
    background: var(--btn-bg) !important;
    border: 1px solid var(--btn-border) !important;
    color: var(--text-primary) !important;
    border-radius: 7px !important;
    font-weight: 600;
    font-family: var(--font-body) !important;
    transition: border-color 0.18s ease, background 0.18s ease, color 0.18s ease;
    backdrop-filter: blur(8px);
}
.stButton > button p {
    color: inherit !important;
    white-space: nowrap !important;
}
.stButton > button:hover {
    background: var(--btn-bg-hover) !important;
    border-color: var(--border-strong) !important;
    box-shadow: var(--btn-hover-shadow) !important;
}
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, var(--accent), var(--accent2)) !important;
    border: none !important;
    color: #ffffff !important;
    box-shadow: 0 4px 16px rgba(var(--accent-rgb), 0.35) !important;
}
.stButton > button[kind="primary"] p {
    color: #ffffff !important;
}
.stButton > button[kind="primary"]:hover {
    box-shadow: 0 6px 24px rgba(var(--accent-rgb), 0.55) !important;
}

/* ── Expanders ── */
[data-testid="stExpander"] {
    background: var(--bg-expander) !important;
    border: 1px solid var(--border-subtle) !important;
    border-radius: 8px;
    backdrop-filter: blur(8px);
}

/* ── Dividers ── */
hr {
    border: none !important;
    height: 1px;
    background: var(--hr-bg) !important;
    margin: 16px 0;
}

/* ── Charts ── */
[data-testid="stArrowVegaLiteChart"],
[data-testid="stVegaLiteChart"] {
    background: transparent !important;
    border-radius: 10px;
}

/* ── Inputs ── */
.stSelectbox > div > div,
.stTextInput > div > div > input,
.stNumberInput > div > div > input,
.stTextArea > div > div > textarea {
    background: var(--bg-input) !important;
    border: 1px solid var(--border-normal) !important;
    border-radius: 8px !important;
    color: var(--text-input) !important;
    font-family: var(--font-body) !important;
}
.stSelectbox > div > div:focus-within,
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {
    border-color: var(--border-strong) !important;
    box-shadow: 0 0 12px rgba(var(--accent-rgb), 0.12) !important;
}

/* ── Slider ── */
.stSlider > div > div > div > div {
    background: var(--slider-track) !important;
}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    row-gap: 6px;
    background: var(--bg-tab-list);
    border-radius: 8px;
    padding: 4px;
    overflow-x: auto;
    flex-wrap: wrap;
    scrollbar-width: thin;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 6px;
    color: var(--text-secondary) !important;
    font-weight: 700;
    font-family: var(--font-body) !important;
    min-height: 32px;
    white-space: nowrap;
    padding: 5px 9px;
    border: 1px solid transparent;
}
.stTabs [aria-selected="true"] {
    background: var(--tab-active-bg) !important;
    color: var(--tab-active-col) !important;
    border-color: rgba(var(--accent-rgb), 0.28);
}

/* ── Captions ── */
.stCaption, [data-testid="stCaptionContainer"] {
    color: var(--text-muted) !important;
    font-family: var(--font-body) !important;
}

/* ── Code blocks ── */
code, pre, .stCodeBlock {
    font-family: var(--font-mono) !important;
    background: var(--bg-input) !important;
    border: 1px solid var(--border-subtle) !important;
    border-radius: 6px;
    color: var(--accent) !important;
}

/* ── Scrollbars ── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--scrollbar-track); }
::-webkit-scrollbar-thumb { background: var(--scrollbar-thumb); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--scrollbar-hover); }

/* ── Animations ── */
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.5} }
@keyframes black-ice-shift {
    0%   { background-position: 0% 50%; }
    50%  { background-position: 100% 50%; }
    100% { background-position: 0% 50%; }
}
.live-indicator { animation: pulse 2s ease-in-out infinite; }

/* Mission Control shell */
.ow-sidebar-brand {
    padding: 8px 4px 6px;
    text-align: center;
}
.ow-brand-row,
.ow-main-title {
    display: flex;
    align-items: center;
    gap: 10px;
    color: var(--text-primary);
    font-weight: 900;
    letter-spacing: 0;
}
.ow-brand-row {
    justify-content: center;
    font-size: 1.06rem;
}
.ow-brand-dot {
    width: 24px;
    height: 14px;
    display: inline-block;
    border-radius: 50%;
    background: var(--accent);
    box-shadow: 0 0 12px rgba(var(--accent-rgb), 0.32);
    flex: 0 0 auto;
}
.ow-sidebar-subtitle {
    margin-top: 5px;
    color: var(--text-muted);
    font-size: 0.62rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}
.ow-live-pill,
.ow-company-pill {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: 999px;
    border: 1px solid var(--border-normal);
    padding: 3px 9px;
    color: var(--accent);
    background: rgba(var(--accent-rgb), 0.08);
    font-size: 0.68rem;
    font-weight: 900;
    letter-spacing: 0.05em;
    text-transform: uppercase;
}
.ow-live-pill {
    margin: 8px auto 0;
}
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
    gap: 0.45rem;
}
[data-testid="stSidebar"] .stCaption {
    color: var(--text-muted) !important;
    font-size: 0.68rem !important;
    font-weight: 900 !important;
    letter-spacing: 0.09em !important;
    text-transform: uppercase !important;
    margin-top: 0.6rem !important;
}
[data-testid="stSidebar"] .stButton > button {
    justify-content: flex-start !important;
    min-height: 36px;
    border-radius: 7px !important;
    font-size: 0.84rem !important;
    font-weight: 760 !important;
    box-shadow: none !important;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"] {
    background: rgba(var(--accent-rgb), 0.17) !important;
    border: 1px solid rgba(var(--accent-rgb), 0.45) !important;
    color: var(--accent) !important;
    box-shadow: inset 3px 0 0 var(--accent) !important;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"] p {
    color: var(--accent) !important;
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] .ow-brand-row,
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] .ow-brand-row span:last-child {
    color: var(--text-primary) !important;
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] .ow-sidebar-subtitle {
    color: var(--text-muted) !important;
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] .ow-live-pill {
    color: var(--accent) !important;
}
[data-testid="stSidebar"] .stExpander {
    border-radius: 8px !important;
}

/* ── Status badges ── */
.status-badge {
    display: inline-block; padding: 2px 8px; border-radius: 12px;
    font-size: 0.7rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;
}
.badge-healthy  { background: rgba(34,197,94,0.20); color:#4ade80; border:1px solid rgba(34,197,94,0.30); }
.badge-warning  { background: rgba(251,191,36,0.20); color:#fbbf24; border:1px solid rgba(251,191,36,0.30); }
.badge-critical { background: rgba(239,68,68,0.20);  color:#f87171; border:1px solid rgba(239,68,68,0.30); }

/* ── Metric card container (custom) ── */
.metric-card {
    background: var(--bg-card);
    border: 1px solid var(--border-subtle);
    border-radius: 8px; padding: 16px; margin: 8px 0;
    backdrop-filter: blur(12px);
}
.glow-text { text-shadow: 0 0 10px rgba(var(--accent-rgb), 0.5); }
.stAlert { border-radius: 10px; backdrop-filter: blur(8px); }

/* Clean DBA shell */
.ow-topbar {
    border-bottom: 1px solid var(--border-subtle);
    padding: 0.2rem 0 0.85rem;
    margin-bottom: 0.75rem;
}
.ow-section-kicker {
    color: var(--text-muted);
    font-size: 0.68rem;
    font-weight: 850;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-bottom: 0.35rem;
}
.ow-section-row {
    display: flex;
    gap: 0.72rem;
    align-items: flex-start;
}
.ow-section-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 2.25rem;
    height: 1.65rem;
    border-radius: 7px;
    border: 1px solid var(--border-normal);
    background: rgba(var(--accent-rgb), 0.08);
    color: var(--accent);
    font-size: 0.62rem;
    font-weight: 900;
    letter-spacing: 0;
}
.ow-section-title {
    color: var(--text-primary);
    font-size: clamp(1.45rem, 2vw, 2rem);
    font-weight: 850;
    line-height: 1.05;
    letter-spacing: 0;
}
.ow-section-subtitle {
    color: var(--text-secondary);
    font-size: 0.86rem;
    margin-top: 0.3rem;
}
.ow-scope-row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
    margin-top: 0.7rem;
}
.ow-scope-chip {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    border: 1px solid var(--border-subtle);
    border-radius: 999px;
    padding: 0.22rem 0.55rem;
    background: rgba(var(--accent-rgb), 0.05);
    color: var(--text-secondary);
    font-size: 0.72rem;
    white-space: nowrap;
}
.ow-scope-chip span {
    color: var(--text-muted);
    font-weight: 700;
}
.ow-scope-chip strong {
    color: var(--text-primary);
    font-weight: 750;
}
.ow-muted-chip {
    background: transparent;
}
.ow-run-context {
    color: var(--text-muted);
    font-size: 0.72rem;
    text-align: right;
    line-height: 1.55;
    padding-top: 0.45rem;
    margin-bottom: 0.5rem;
}
.ow-empty-state {
    max-width: 780px;
    margin: 2.25rem 0;
    padding: 1.25rem 0;
    border-top: 1px solid var(--border-subtle);
    border-bottom: 1px solid var(--border-subtle);
}
.ow-empty-title {
    color: var(--text-primary);
    font-size: 1.2rem;
    font-weight: 800;
    margin-bottom: 0.45rem;
}
.ow-empty-list {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    margin-top: 0.45rem;
}
.ow-empty-list span {
    border: 1px solid var(--border-subtle);
    border-radius: 999px;
    padding: 0.25rem 0.6rem;
    color: var(--text-secondary);
    font-size: 0.75rem;
}
.ow-section-transition {
    position: fixed;
    inset: 0;
    z-index: 9999;
    display: grid;
    place-items: center;
    padding: 2rem;
    background:
        radial-gradient(circle at 50% 42%, rgba(var(--accent-rgb), 0.12), transparent 34rem),
        var(--bg-app);
    backdrop-filter: blur(10px);
}
.ow-section-transition-card {
    width: min(620px, calc(100vw - 3rem));
    border: 1px solid var(--border-normal);
    border-radius: 8px;
    padding: 1.15rem 1.25rem;
    background: var(--bg-card);
    box-shadow: var(--metric-shadow);
}
.ow-section-transition-kicker {
    color: var(--text-muted);
    font-size: 0.68rem;
    font-weight: 850;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}
.ow-section-transition-title {
    color: var(--text-primary);
    font-size: 1.05rem;
    font-weight: 850;
    margin-top: 0.2rem;
}
.ow-section-transition-copy {
    color: var(--text-secondary);
    font-size: 0.84rem;
    line-height: 1.45;
    margin-top: 0.3rem;
}
.ow-section-transition-bar {
    position: relative;
    overflow: hidden;
    height: 3px;
    border-radius: 999px;
    margin-top: 0.95rem;
    background: rgba(var(--accent-rgb), 0.14);
}
.ow-section-transition-bar span {
    position: absolute;
    inset: 0 auto 0 0;
    width: 42%;
    border-radius: inherit;
    background: linear-gradient(90deg, transparent, var(--accent), var(--accent2));
    animation: ow-section-loading 1.1s ease-in-out infinite;
}
@keyframes ow-section-loading {
    0% { transform: translateX(-105%); }
    100% { transform: translateX(245%); }
}
.ow-brief-strip {
    border-top: 1px solid var(--border-subtle);
    border-bottom: 1px solid var(--border-subtle);
    margin: 0.85rem 0 1rem;
    padding: 0.65rem 0;
}
.ow-table-heading span:first-child {
    color: var(--text-primary);
    font-size: 0.83rem;
    font-weight: 850;
}
.ow-brief-grid {
    display: grid;
    gap: 0.55rem 1rem;
    margin-top: 0.45rem;
}
.ow-brief-item {
    min-width: 0;
}
.ow-brief-label {
    color: var(--text-muted);
    font-size: 0.66rem;
    font-weight: 850;
    letter-spacing: 0.05em;
    text-transform: uppercase;
}
.ow-brief-detail {
    color: var(--text-secondary);
    font-size: 0.83rem;
    line-height: 1.35;
    margin-top: 0.12rem;
}
.ow-section-guide {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 0.65rem;
    margin: 0.2rem 0 0.85rem;
}
.ow-section-guide-card {
    min-width: 0;
    border-top: 1px solid var(--border-subtle);
    padding: 0.55rem 0.05rem 0;
}
.ow-section-guide-label {
    color: var(--text-muted);
    font-size: 0.64rem;
    font-weight: 850;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    white-space: nowrap;
}
.ow-section-guide-detail {
    color: var(--text-secondary);
    font-size: 0.8rem;
    line-height: 1.35;
    margin-top: 0.18rem;
}
.ow-confidence-meter {
    margin: 0.15rem 0 0.8rem;
    border-top: 1px solid var(--border-subtle);
    border-bottom: 1px solid var(--border-subtle);
    padding: 0.55rem 0 0.6rem;
}
.ow-confidence-meter-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1rem;
    margin-bottom: 0.4rem;
}
.ow-confidence-meter-kicker {
    color: var(--text-muted);
    font-size: 0.7rem;
    font-weight: 850;
    letter-spacing: 0.06em;
    margin-right: 0.45rem;
    text-transform: uppercase;
}
.ow-confidence-meter-title {
    color: var(--text-primary);
    font-size: 0.9rem;
    font-weight: 850;
}
.ow-confidence-score {
    color: var(--text-primary);
    font-size: 1.18rem;
    font-weight: 850;
    line-height: 1;
    text-align: right;
    white-space: nowrap;
}
.ow-confidence-score span {
    color: var(--text-muted);
    font-size: 0.72rem;
    font-weight: 750;
    margin-left: 0.12rem;
}
.ow-confidence-exact { background: #22c55e; }
.ow-confidence-allocated { background: #38bdf8; }
.ow-confidence-delayed { background: #f59e0b; }
.ow-confidence-manual { background: #a78bfa; }
.ow-confidence-unavailable { background: #ef4444; }
.ow-confidence-gauge {
    height: 28px;
    margin: 0.1rem 0 0.2rem;
    position: relative;
}
.ow-confidence-gauge-track {
    background:
        linear-gradient(
            90deg,
            #ef4444 0%,
            #f97316 24%,
            #f59e0b 42%,
            #38bdf8 68%,
            #22c55e 100%
        );
    border: 1px solid rgba(255,255,255,0.22);
    border-radius: 999px;
    box-shadow:
        inset 0 1px 2px rgba(15,23,42,0.28),
        0 0 0 1px rgba(15,23,42,0.08);
    height: 16px;
    left: 0;
    opacity: 0.94;
    position: absolute;
    right: 0;
    top: 7px;
}
.ow-confidence-gauge-marker {
    background: var(--text-primary);
    border: 2px solid var(--bg-card);
    border-radius: 999px;
    box-shadow: 0 6px 14px rgba(15,23,42,0.22);
    height: 28px;
    position: absolute;
    top: 1px;
    transform: translateX(-50%);
    width: 10px;
}
.ow-confidence-gauge-marker::after {
    background: var(--text-primary);
    border-radius: 999px;
    bottom: -6px;
    content: "";
    height: 6px;
    left: 50%;
    position: absolute;
    transform: translateX(-50%);
    width: 2px;
}
.ow-confidence-foot {
    align-items: center;
    display: flex;
    gap: 0.7rem;
    justify-content: space-between;
}
.ow-confidence-meta {
    color: var(--text-muted);
    font-size: 0.68rem;
    white-space: nowrap;
}
.ow-confidence-mix {
    align-items: center;
    display: flex;
    flex-wrap: wrap;
    gap: 0.55rem;
    min-width: 0;
}
.ow-confidence-mix-item {
    align-items: center;
    color: var(--text-secondary);
    display: inline-flex;
    font-size: 0.68rem;
    font-weight: 800;
    gap: 0.25rem;
    line-height: 1;
    white-space: nowrap;
}
.ow-confidence-dot {
    border-radius: 999px;
    display: inline-block;
    height: 0.45rem;
    margin-right: 0.05rem;
    width: 0.45rem;
}
.ow-evidence-contract {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.7rem;
    margin: 0.15rem 0 0.35rem;
}
.ow-evidence-contract-card {
    min-width: 0;
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    padding: 0.75rem 0.8rem;
    background: var(--bg-expander);
    color: var(--text-secondary);
    font-size: 0.78rem;
    line-height: 1.35;
}
.ow-evidence-contract-card div {
    margin-top: 0.38rem;
}
.ow-evidence-contract-card div:first-child {
    margin-top: 0;
}
.ow-evidence-contract-card span {
    display: block;
    color: var(--text-muted);
    font-size: 0.62rem;
    font-weight: 850;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    margin-bottom: 0.08rem;
}
.ow-evidence-contract-source {
    color: var(--text-primary);
    font-weight: 850;
    font-size: 0.82rem;
}
.ow-table-heading {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 1rem;
    margin: 0.75rem 0 0.35rem;
}
.ow-table-heading span:last-child {
    color: var(--text-muted);
    font-size: 0.72rem;
}
[data-testid="stMarkdownContainer"] .ow-section-title,
[data-testid="stMarkdownContainer"] .ow-empty-title,
[data-testid="stMarkdownContainer"] .ow-table-heading span:first-child,
[data-testid="stMarkdownContainer"] .ow-confidence-meter-title,
[data-testid="stMarkdownContainer"] .ow-confidence-score,
[data-testid="stMarkdownContainer"] .ow-scope-chip strong {
    color: var(--text-primary) !important;
}
[data-testid="stMarkdownContainer"] .ow-section-subtitle,
[data-testid="stMarkdownContainer"] .ow-scope-chip,
[data-testid="stMarkdownContainer"] .ow-empty-list span,
[data-testid="stMarkdownContainer"] .ow-section-guide-detail,
[data-testid="stMarkdownContainer"] .ow-confidence-mix-item,
[data-testid="stMarkdownContainer"] .ow-evidence-contract-card,
[data-testid="stMarkdownContainer"] .ow-brief-detail {
    color: var(--text-secondary) !important;
}
[data-testid="stMarkdownContainer"] .ow-section-kicker,
[data-testid="stMarkdownContainer"] .ow-scope-chip span,
[data-testid="stMarkdownContainer"] .ow-run-context,
[data-testid="stMarkdownContainer"] .ow-section-guide-label,
[data-testid="stMarkdownContainer"] .ow-confidence-meter-kicker,
[data-testid="stMarkdownContainer"] .ow-confidence-score span,
[data-testid="stMarkdownContainer"] .ow-confidence-meta,
[data-testid="stMarkdownContainer"] .ow-evidence-contract-card span,
[data-testid="stMarkdownContainer"] .ow-brief-label,
[data-testid="stMarkdownContainer"] .ow-table-heading span:last-child {
    color: var(--text-muted) !important;
}
[data-testid="stMarkdownContainer"] .ow-evidence-contract-source {
    color: var(--text-primary) !important;
}
[data-testid="stMarkdownContainer"] .ow-section-icon {
    color: var(--accent) !important;
}
@media (max-width: 900px) {
    .ow-brief-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
    }
    .ow-section-guide {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .ow-evidence-contract {
        grid-template-columns: 1fr;
    }
    .ow-run-context {
        text-align: left;
    }
}
@media (max-width: 620px) {
    .ow-section-row,
    .ow-table-heading {
        align-items: flex-start;
        flex-direction: column;
    }
    .ow-section-guide {
        grid-template-columns: 1fr;
    }
    .ow-confidence-meter-head {
        flex-direction: column;
    }
    .ow-confidence-score {
        text-align: left;
    }
    .ow-confidence-foot {
        align-items: flex-start;
        flex-direction: column;
        gap: 0.45rem;
    }
    .ow-brief-grid {
        grid-template-columns: 1fr !important;
    }
}

/* ═══════════════════ SNOWFLAKE WHITE theme extras ═══════════════════ */
.terminal-extra [data-testid="stMetric"] {
    border-top: 3px solid rgba(41,181,232,0.75) !important;
}

/* ═══════════════════ CORPORATE theme extras ═══════════════════ */
/* Sidebar text needs to be white on navy background */
.corporate-extra [data-testid="stSidebar"] label,
.corporate-extra [data-testid="stSidebar"] .stRadio > label,
.corporate-extra [data-testid="stSidebar"] p {
    color: #334155 !important;
}
.corporate-extra [data-testid="stSidebar"] .stRadio > div > label:hover {
    color: #b00020 !important;
    background: rgba(176,0,32,0.06);
}
.corporate-extra [data-testid="stSidebar"] .stRadio > div > label[data-checked="true"] {
    color: #b00020 !important;
    background: rgba(176,0,32,0.10);
    border-left: 3px solid #b00020;
}
.corporate-extra [data-testid="stSidebar"] .stButton > button[kind="secondary"] {
    color: #1f2937 !important;
    background: #ffffff !important;
    border-color: #d7e2ea !important;
    box-shadow: none !important;
}
.corporate-extra [data-testid="stSidebar"] .stButton > button[kind="secondary"]:hover {
    color: #b00020 !important;
    background: #f8fafc !important;
    border-color: rgba(176,0,32,0.28) !important;
}
.corporate-extra [data-testid="stSidebar"] .stButton > button[kind="primary"] {
    color: #ffffff !important;
    background: linear-gradient(135deg, #b00020, #0f7894) !important;
}
/* Corporate: body text stays dark on light backgrounds */
.corporate-extra p,
.corporate-extra li,
.corporate-extra label:not([data-testid="stSidebar"] *) {
    color: #1f2937 !important;
}
.corporate-extra h2, .corporate-extra h3 {
    color: #b00020 !important;
}
/* Corporate metrics: white cards, dark text */
.corporate-extra [data-testid="stMetric"] {
    border-top: 3px solid rgba(176,0,32,0.72) !important;
}
.corporate-extra [data-testid="stMetricValue"] { color: #2f3437 !important; }
.corporate-extra [data-testid="stMetricLabel"] { color: #6c7478 !important; }
.corporate-extra .stTabs [data-baseweb="tab-list"] {
    border-bottom: 2px solid rgba(176,0,32,0.65);
}
.corporate-extra .stTabs [data-baseweb="tab"] {
    color: #4d5559 !important;
    font-weight: 650;
}

</style>
"""

# ── Theme picker HTML ─────────────────────────────────────────────────────────
_THEME_EXTRAS = {
    "corporate": """
<style>
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stRadio > label,
[data-testid="stSidebar"] p {
    color: #334155 !important;
}
[data-testid="stSidebar"] .stButton > button {
    color: #1f2937 !important;
    background: #ffffff !important;
    border-color: #d7e2ea !important;
    box-shadow: none !important;
}
[data-testid="stSidebar"] .stButton > button p {
    color: inherit !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    color: #b00020 !important;
    background: rgba(176,0,32,0.06) !important;
    border-color: rgba(176,0,32,0.28) !important;
}
[data-testid="stSidebar"] .stRadio > div > label:hover {
    color: #b00020 !important;
    background: rgba(176,0,32,0.06);
}
[data-testid="stSidebar"] .stRadio > div > label[data-checked="true"] {
    color: #b00020 !important;
    background: rgba(176,0,32,0.10);
    border-left: 3px solid #b00020;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"],
[data-testid="stSidebar"] .stButton > button[kind="primary"] p {
    color: #b00020 !important;
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] .ow-live-pill {
    color: #b00020 !important;
}
[data-testid="stMetric"] {
    border-top: 3px solid rgba(176,0,32,0.72) !important;
}
[data-testid="stMetricValue"] { color: #2f3437 !important; }
[data-testid="stMetricLabel"] { color: #6c7478 !important; }
[data-testid="stExpander"] {
    background: #ffffff !important;
    border-color: #d7e2ea !important;
}
[data-testid="stExpander"] details,
[data-testid="stExpander"] summary,
[data-testid="stExpander"] summary p,
[data-testid="stExpander"] summary span,
[data-testid="stExpander"] [data-testid="stMarkdownContainer"],
[data-testid="stExpander"] [data-testid="stMarkdownContainer"] p {
    color: #1f2937 !important;
}
[data-testid="stExpander"] summary:hover,
[data-testid="stExpander"] summary:hover p,
[data-testid="stExpander"] summary:hover span {
    color: #b00020 !important;
}
[data-testid="stWidgetLabel"],
[data-testid="stWidgetLabel"] p,
.stTextInput label,
.stTextInput label p {
    color: #1f2937 !important;
}
.stTextInput input::placeholder,
.stTextArea textarea::placeholder {
    color: #64748b !important;
    opacity: 1 !important;
}
.stTabs [data-baseweb="tab-list"] {
    border-bottom: 2px solid rgba(176,0,32,0.65);
}
.stTabs [data-baseweb="tab"] {
    color: #4d5559 !important;
    font-weight: 650;
}
.stTabs [aria-selected="true"] {
    color: #b00020 !important;
}
</style>
""",
    "terminal": """
<style>
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stRadio > label,
[data-testid="stSidebar"] p {
    color: #24323D !important;
}
[data-testid="stSidebar"] .stButton > button {
    color: #24323D !important;
    background: #ffffff !important;
    border-color: #b8d8e5 !important;
    box-shadow: none !important;
}
[data-testid="stSidebar"] .stButton > button p {
    color: inherit !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    color: #11567F !important;
    background: #eef7fb !important;
    border-color: rgba(41,181,232,0.48) !important;
}
[data-testid="stSidebar"] .stRadio > div > label:hover {
    color: #11567F !important;
    background: rgba(41,181,232,0.08);
}
[data-testid="stSidebar"] .stRadio > div > label[data-checked="true"] {
    color: #11567F !important;
    background: rgba(41,181,232,0.13);
    border-left: 3px solid #29B5E8;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"],
[data-testid="stSidebar"] .stButton > button[kind="primary"] p {
    color: #11567F !important;
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] .ow-live-pill {
    color: #11567F !important;
}
[data-testid="stMetric"] {
    border-top: 3px solid rgba(41,181,232,0.75) !important;
}
[data-testid="stMetricValue"] { color: #24323D !important; }
[data-testid="stMetricLabel"] { color: #5f7180 !important; }
.stTabs [data-baseweb="tab-list"] {
    border-bottom: 2px solid rgba(41,181,232,0.55);
}
.stTabs [data-baseweb="tab"] {
    color: #24323D !important;
    font-weight: 650;
}
.stTabs [aria-selected="true"] {
    color: #11567F !important;
}
</style>
""",
}

_STREAMLIT_ICON_FIX = """
<style>
.stApp [data-testid="stIconMaterial"],
[data-testid="stSidebar"] [data-testid="stIconMaterial"],
.stExpander [data-testid="stIconMaterial"],
summary [data-testid="stIconMaterial"],
[data-testid="stSidebar"] .material-symbols-rounded,
[data-testid="stSidebar"] .material-symbols-outlined,
[data-testid="stSidebar"] .material-icons,
[data-testid="stSidebar"] span[translate="no"],
.stExpander .material-symbols-rounded,
.stExpander .material-symbols-outlined,
.stExpander .material-icons,
.stExpander span[translate="no"],
details summary .material-symbols-rounded,
details summary .material-symbols-outlined,
details summary .material-icons,
details summary span[translate="no"] {
    display: inline-block !important;
    width: 0 !important;
    min-width: 0 !important;
    max-width: 0 !important;
    height: 0 !important;
    overflow: hidden !important;
    color: transparent !important;
    font-size: 0 !important;
    line-height: 0 !important;
    opacity: 0 !important;
}
.stApp [data-testid="stIconMaterial"] *,
[data-testid="stSidebar"] [data-testid="stIconMaterial"] * {
    display: inline-block !important;
    width: 0 !important;
    height: 0 !important;
    overflow: hidden !important;
    color: transparent !important;
    font-size: 0 !important;
    line-height: 0 !important;
    opacity: 0 !important;
}
</style>
"""


def _normalize_theme_key(theme_key: str | None) -> str:
    theme_key = str(theme_key or _DEFAULT_THEME)
    theme_key = _THEME_ALIASES.get(theme_key, theme_key)
    return theme_key if theme_key in THEMES else _DEFAULT_THEME


def _get_theme() -> str:
    theme_key = _normalize_theme_key(st.session_state.get("active_theme", _DEFAULT_THEME))
    if st.session_state.get("active_theme") != theme_key:
        st.session_state["active_theme"] = theme_key
    return theme_key


_COMBINED_CSS_CACHE: dict[str, str] = {}


def _combined_theme_css(theme_key: str) -> str:
    cached = _COMBINED_CSS_CACHE.get(theme_key)
    if cached:
        return cached
    vars_block = _VARS.get(theme_key, _VARS[_DEFAULT_THEME])
    combined = (
        _STRUCTURAL_CSS.replace("{vars}", vars_block)
        + _THEME_EXTRAS.get(theme_key, "")
        + _STREAMLIT_ICON_FIX
    )
    _COMBINED_CSS_CACHE[theme_key] = combined
    return combined


def inject_theme() -> None:
    """
    Inject CSS variables + structural styles for the current theme.
    Call once at the top of app.py before any other st.* calls.
    Also applies theme-specific body class for extra overrides.
    """
    theme_key = _get_theme()
    st.markdown(_combined_theme_css(theme_key), unsafe_allow_html=True)


def render_theme_picker(persist: bool = False) -> None:
    """
    Render the 5-theme picker as clickable swatch buttons.
    Place this inside the sidebar Settings expander in app.py.

    Each option shows only the theme name.
    The active theme gets a highlight border.

    Args:
        persist: Write preference to OVERWATCH_BOOKMARKS for cross-session persistence.
    """
    current = _get_theme()
    options = list(THEMES.keys())
    index = options.index(current) if current in options else 0
    selected = st.radio(
        "Theme",
        options,
        index=index,
        format_func=lambda key: THEMES[key]["label"],
        key="theme_picker_radio",
    )
    if selected != current:
        st.session_state["active_theme"] = selected
        if persist:
            _save_theme_preference(selected)
        st.rerun()


def restore_theme_preference() -> None:
    """
    Restore a persisted theme from OVERWATCH_BOOKMARKS on first session load.
    Call before inject_theme() in app.py. Only needed when persist=True.
    """
    if "active_theme" in st.session_state:
        return
    try:
        from utils.session import get_session
        from config import ALERT_DB, ALERT_SCHEMA
        from utils.query import safe_identifier, sql_literal
        session = get_session()
        sf_user = str(st.session_state.get("_overwatch_actor", "OVERWATCH") or "OVERWATCH")
        bookmark_table = (
            f"{safe_identifier(ALERT_DB)}."
            f"{safe_identifier(ALERT_SCHEMA)}."
            f"{safe_identifier('OVERWATCH_BOOKMARKS')}"
        )
        rows = session.sql(f"""
            SELECT STATE_JSON FROM {bookmark_table}
            WHERE SF_USER = {sql_literal(sf_user)}
              AND BOOKMARK_NAME = {sql_literal("_theme_pref")}
            ORDER BY CREATED_AT DESC LIMIT 1
        """).collect()
        if rows:
            import json
            state = json.loads(rows[0]["STATE_JSON"] or "{}")
            st.session_state["active_theme"] = _normalize_theme_key(
                state.get("active_theme", _DEFAULT_THEME)
            )
    except Exception:
        pass


def _save_theme_preference(theme_key: str) -> None:
    import json
    try:
        from utils.session import get_session
        from config import ALERT_DB, ALERT_SCHEMA
        from utils.query import safe_identifier, sql_literal
        session = get_session()
        sf_user = str(st.session_state.get("_overwatch_actor", "OVERWATCH") or "OVERWATCH")
        bookmark_table = (
            f"{safe_identifier(ALERT_DB)}."
            f"{safe_identifier(ALERT_SCHEMA)}."
            f"{safe_identifier('OVERWATCH_BOOKMARKS')}"
        )
        state_json = sql_literal(json.dumps({"active_theme": theme_key}))
        bookmark_name = sql_literal("_theme_pref")
        sf_user_safe = sql_literal(sf_user)
        session.sql(f"""
            DELETE FROM {bookmark_table}
            WHERE SF_USER = {sf_user_safe} AND BOOKMARK_NAME = {bookmark_name}
        """).collect()
        session.sql(f"""
            INSERT INTO {bookmark_table}
                (SF_USER, BOOKMARK_NAME, SECTION, STATE_JSON, IS_SHARED)
            VALUES ({sf_user_safe}, {bookmark_name}, '', PARSE_JSON({state_json}), FALSE)
        """).collect()
    except Exception:
        pass
