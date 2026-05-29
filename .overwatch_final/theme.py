# theme.py — OVERWATCH V3 · 5-theme system
# ─────────────────────────────────────────────────────────────────────────────
# THEMES:
#   1. midnight   — Original dark glassmorphism (cyan/indigo/purple)
#   2. corporate  — Traditional light: white cards, navy sidebar, ALFA blue
#   3. terminal   — Snowflake White: classic white with Snowflake blue
#   4. aurora     — Dark with shifting teal-to-emerald gradient accents
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

_DEFAULT_THEME = "midnight"

# ── Theme metadata (used for the picker UI) ───────────────────────────────────
THEMES = {
    "midnight": {
        "label":    "Midnight",
        "emoji":    "🌌",
        "swatch":   "#38bdf8",
        "bg":       "#0a0e1a",
        "desc":     "Dark glassmorphism · cyan accent",
    },
    "corporate": {
        "label":    "ALFA Light",
        "emoji":    "🔴",
        "swatch":   "#b00020",
        "bg":       "#ffffff",
        "desc":     "Bright ALFA red, slate & teal",
    },
    "terminal": {
        "label":    "Snowflake White",
        "emoji":    "❄️",
        "swatch":   "#29B5E8",
        "bg":       "#ffffff",
        "desc":     "Classic white · Snowflake blue",
    },
    "aurora": {
        "label":    "Aurora",
        "emoji":    "🌌",
        "swatch":   "#2dd4bf",
        "bg":       "#0d1117",
        "desc":     "Dark · teal-to-emerald gradients",
    },
    "carbon": {
        "label":    "Snowflake Dark",
        "emoji":    "🌙",
        "swatch":   "#29B5E8",
        "bg":       "#0B1117",
        "desc":     "Classic dark · Snowflake blue",
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

# ─── 4. AURORA — dark midnight with shifting teal-emerald-cyan accents ────────
"aurora": """
:root {
    --bg-app:          linear-gradient(160deg, #0d1117 0%, #0d1f2d 40%, #0d1a0f 100%);
    --bg-sidebar:      linear-gradient(180deg, #0d1117 0%, #0d1f1c 100%);
    --bg-card:         rgba(13, 31, 29, 0.65);
    --bg-card-hover:   rgba(13, 31, 29, 0.90);
    --bg-input:        rgba(13, 31, 29, 0.80);
    --bg-tab-list:     rgba(13, 31, 29, 0.45);
    --bg-expander:     rgba(13, 31, 29, 0.45);

    --border-subtle:   rgba(45, 212, 191, 0.12);
    --border-normal:   rgba(45, 212, 191, 0.25);
    --border-strong:   rgba(45, 212, 191, 0.50);
    --border-sidebar:  rgba(45, 212, 191, 0.12);

    --text-primary:    #ecfdf5;
    --text-secondary:  #6ee7b7;
    --text-muted:      #8fb8aa;
    --text-input:      #ecfdf5;
    --text-heading:    transparent;

    --accent:          #2dd4bf;
    --accent-rgb:      45, 212, 191;
    --accent2:         #34d399;
    --accent3:         #6ee7b7;
    --h1-gradient:     linear-gradient(90deg, #2dd4bf, #34d399, #059669);

    --metric-shadow:        0 4px 24px rgba(0,0,0,0.40), inset 0 1px 0 rgba(45,212,191,0.08);
    --metric-hover-shadow:  0 8px 32px rgba(45,212,191,0.15), inset 0 1px 0 rgba(45,212,191,0.12);
    --btn-bg:          linear-gradient(135deg, rgba(45,212,191,0.12), rgba(52,211,153,0.12));
    --btn-bg-hover:    linear-gradient(135deg, rgba(45,212,191,0.28), rgba(52,211,153,0.28));
    --btn-border:      rgba(45, 212, 191, 0.30);
    --btn-hover-shadow: 0 0 20px rgba(45,212,191,0.22);
    --slider-track:    linear-gradient(90deg, #059669, #2dd4bf);
    --tab-active-bg:   rgba(45, 212, 191, 0.14);
    --tab-active-col:  #2dd4bf;
    --hr-bg:           linear-gradient(90deg, transparent, rgba(45,212,191,0.30), transparent);
    --scrollbar-track: rgba(13, 31, 29, 0.50);
    --scrollbar-thumb: rgba(45, 212, 191, 0.28);
    --scrollbar-hover: rgba(45, 212, 191, 0.55);
    --font-body:       'Inter', system-ui, sans-serif;
    --font-mono:       'JetBrains Mono', 'Fira Code', monospace;
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
    border-radius: 12px !important;
    padding: 16px 20px !important;
    box-shadow: var(--metric-shadow) !important;
    transition: all 0.25s ease;
}
[data-testid="stMetric"]:hover {
    border-color: var(--border-strong) !important;
    box-shadow: var(--metric-hover-shadow) !important;
    transform: translateY(-2px);
}
[data-testid="stMetricLabel"] {
    color: var(--text-muted) !important;
    font-size: 0.72rem !important;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    font-family: var(--font-body) !important;
}
[data-testid="stMetricValue"] {
    color: var(--text-primary) !important;
    font-weight: 700 !important;
    font-size: 1.5rem !important;
    font-family: var(--font-body) !important;
}

/* ── Headings ── */
h1 {
    background: var(--h1-gradient) !important;
    -webkit-background-clip: text !important;
    -webkit-text-fill-color: transparent !important;
    background-clip: text !important;
    font-weight: 800 !important;
    letter-spacing: -0.5px;
    font-family: var(--font-body) !important;
}
h2, h3 {
    color: var(--text-primary) !important;
    border-bottom: 1px solid var(--border-subtle);
    padding-bottom: 8px;
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
    border-radius: 10px;
    overflow: hidden;
}

/* ── Buttons ── */
.stButton > button {
    background: var(--btn-bg) !important;
    border: 1px solid var(--btn-border) !important;
    color: var(--text-primary) !important;
    border-radius: 8px !important;
    font-weight: 600;
    font-family: var(--font-body) !important;
    transition: all 0.25s ease;
    backdrop-filter: blur(8px);
}
.stButton > button:hover {
    background: var(--btn-bg-hover) !important;
    border-color: var(--border-strong) !important;
    box-shadow: var(--btn-hover-shadow) !important;
    transform: translateY(-1px);
}
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, var(--accent), var(--accent2)) !important;
    border: none !important;
    color: #ffffff !important;
    box-shadow: 0 4px 16px rgba(var(--accent-rgb), 0.35) !important;
}
.stButton > button[kind="primary"]:hover {
    box-shadow: 0 6px 24px rgba(var(--accent-rgb), 0.55) !important;
}

/* ── Expanders ── */
[data-testid="stExpander"] {
    background: var(--bg-expander) !important;
    border: 1px solid var(--border-subtle) !important;
    border-radius: 10px;
    backdrop-filter: blur(8px);
}

/* ── Dividers ── */
hr {
    border: none !important;
    height: 1px;
    background: var(--hr-bg) !important;
    margin: 24px 0;
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
    background: var(--bg-tab-list);
    border-radius: 10px;
    padding: 4px;
    overflow-x: auto;
    flex-wrap: wrap;
    scrollbar-width: thin;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 8px;
    color: var(--text-secondary) !important;
    font-weight: 500;
    font-family: var(--font-body) !important;
    min-height: 36px;
    white-space: nowrap;
    padding: 6px 10px;
}
.stTabs [aria-selected="true"] {
    background: var(--tab-active-bg) !important;
    color: var(--tab-active-col) !important;
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
@keyframes aurora-shift {
    0%   { background-position: 0% 50%; }
    50%  { background-position: 100% 50%; }
    100% { background-position: 0% 50%; }
}
.live-indicator { animation: pulse 2s ease-in-out infinite; }

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
    border-radius: 16px; padding: 24px; margin: 8px 0;
    backdrop-filter: blur(12px);
}
.glow-text { text-shadow: 0 0 10px rgba(var(--accent-rgb), 0.5); }
.stAlert { border-radius: 10px; backdrop-filter: blur(8px); }

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

_PICKER_CSS = """
<style>
.theme-picker { display: flex; flex-direction: column; gap: 6px; margin: 8px 0; }
.theme-btn {
    display: flex; align-items: center; gap: 10px;
    padding: 8px 12px; border-radius: 8px; cursor: pointer;
    border: 1.5px solid transparent;
    transition: all 0.18s ease;
    font-size: 0.78rem; font-weight: 500;
}
.theme-btn:hover { filter: brightness(1.15); transform: translateX(2px); }
.theme-btn.active { border-color: var(--accent) !important; }
.theme-swatch {
    width: 18px; height: 18px; border-radius: 50%;
    flex-shrink: 0; border: 2px solid rgba(255,255,255,0.15);
}
.theme-name { color: var(--text-primary); font-weight: 600; font-size: 0.75rem; }
.theme-desc { color: var(--text-muted); font-size: 0.65rem; margin-top: 1px; }
</style>
"""

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


def _get_theme() -> str:
    return st.session_state.get("active_theme", _DEFAULT_THEME)


def inject_theme() -> None:
    """
    Inject CSS variables + structural styles for the current theme.
    Call once at the top of app.py before any other st.* calls.
    Also applies theme-specific body class for extra overrides.
    """
    theme_key = _get_theme()
    vars_block = _VARS.get(theme_key, _VARS[_DEFAULT_THEME])

    # Inject the :root variables + structural CSS
    combined = (
        _STRUCTURAL_CSS.replace("{vars}", vars_block)
        + _THEME_EXTRAS.get(theme_key, "")
        + _STREAMLIT_ICON_FIX
    )
    st.markdown(combined, unsafe_allow_html=True)


def render_theme_picker(persist: bool = False) -> None:
    """
    Render the 5-theme picker as clickable swatch buttons.
    Place this inside the sidebar Settings expander in app.py.

    Each button shows: colored swatch circle + theme name + one-line description.
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
        format_func=lambda key: f"{THEMES[key]['emoji']} {THEMES[key]['label']} - {THEMES[key]['desc']}",
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
            saved = state.get("active_theme", _DEFAULT_THEME)
            if saved in THEMES:
                st.session_state["active_theme"] = saved
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
