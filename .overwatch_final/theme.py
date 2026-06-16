# theme.py - OVERWATCH theme system
# THEMES:
#   1. carbon     - Snowflake Dark: default dark shell with Snowflake blue
#   2. terminal   - Snowflake White: classic white with Snowflake blue
#
# Architecture: All structural styles reference CSS custom properties.
# Switching theme = injecting a new :root { } block. Zero JS required.
# Preference persists in session_state for the active browser session.
#
# Usage in app.py:
#   from theme import inject_theme, render_theme_picker
#   inject_theme()
#   # inside sidebar Settings expander:
#   render_theme_picker()
import streamlit as st

THEME_VERSION = "2026-06-16-theme-contrast-v9"

_DEFAULT_THEME = "carbon"
_ACTIVE_THEME_KEY = "_overwatch_active_theme"
_THEME_QUERY_PARAM = "overwatch_theme"
_THEME_ALIASES = {
    "aurora": "carbon",
    "black_ice": "carbon",
    "midnight": "carbon",
    "roll_tide": "carbon",
    "war_eagle": "carbon",
    "corporate": "carbon",
    "henson": "carbon",
}

# Theme metadata (used for the picker UI)
THEMES = {
    "carbon": {
        "label":    "Snowflake Dark",
        "swatch":   "#29B5E8",
        "bg":       "#0B1117",
    },
    "terminal": {
        "label":    "Snowflake White",
        "swatch":   "#29B5E8",
        "bg":       "#eef6fb",
    },
}

# CSS variable blocks - one per theme

_VARS = {

# 5. SNOWFLAKE DARK - classic dark with Snowflake brand blues
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

# 6. SNOWFLAKE WHITE - white workspace with Snowflake blue command accents
"terminal": """
:root {
    --bg-app:          #f6fbff;
    --bg-sidebar:      #ffffff;
    --bg-card:         #ffffff;
    --bg-card-hover:   #f1f8fd;
    --bg-input:        #ffffff;
    --bg-tab-list:     #e7f3fa;
    --bg-expander:     #ffffff;

    --border-subtle:   rgba(0, 104, 183, 0.16);
    --border-normal:   rgba(0, 104, 183, 0.30);
    --border-strong:   rgba(0, 104, 183, 0.58);
    --border-sidebar:  rgba(0, 104, 183, 0.18);

    --text-primary:    #102a43;
    --text-secondary:  #31566b;
    --text-muted:      #607b8a;
    --text-input:      #102a43;
    --text-heading:    #102a43;

    --accent:          #0068B7;
    --accent-rgb:      0, 104, 183;
    --accent2:         #29B5E8;
    --accent3:         #71D3DC;
    --h1-gradient:     linear-gradient(90deg, #102a43, #0068B7, #29B5E8);

    --metric-shadow:        0 1px 2px rgba(15, 42, 67, 0.08), 0 8px 24px rgba(0, 104, 183, 0.08);
    --metric-hover-shadow:  0 2px 5px rgba(15, 42, 67, 0.10), 0 10px 28px rgba(0, 104, 183, 0.14);
    --btn-bg:          linear-gradient(135deg, #ffffff, #edf8fd);
    --btn-bg-hover:    linear-gradient(135deg, #f8fdff, #d9f1fb);
    --btn-border:      rgba(0, 104, 183, 0.34);
    --btn-hover-shadow: 0 2px 9px rgba(0, 104, 183, 0.12);
    --slider-track:    linear-gradient(90deg, #0068B7, #29B5E8);
    --tab-active-bg:   #0068B7;
    --tab-active-col:  #ffffff;
    --hr-bg:           linear-gradient(90deg, transparent, rgba(0,104,183,0.28), transparent);
    --scrollbar-track: #e7f3fa;
    --scrollbar-thumb: rgba(0, 104, 183, 0.34);
    --scrollbar-hover: rgba(0, 104, 183, 0.56);
    --font-body:       'Lato', 'Inter', 'DM Sans', system-ui, sans-serif;
    --font-mono:       'DM Mono', 'Cascadia Mono', monospace;
    --extra-css:       '';
}
""",

}

# Shared structural styles (all colors via variables)
_STRUCTURAL_CSS = """
<style>
{vars}

/* OVERWATCH THEME ENGINE */

/* Base */
.stApp, .stApp > * {
    background: var(--bg-app) !important;
    color: var(--text-primary) !important;
    font-family: var(--font-body) !important;
}
.stApp,
.stApp p,
.stApp li,
.stApp label,
.stApp span:not([class*="icon"]):not([class*="material"]),
.stApp div:not([data-testid="stIconMaterial"]) {
    color: var(--text-primary);
}
.block-container {
    padding-top: 1rem !important;
    padding-left: 2.1rem !important;
    padding-right: 2.1rem !important;
    padding-bottom: 2rem !important;
    max-width: 1600px !important;
}
[data-testid="stToolbar"],
[data-testid="stDecoration"],
#MainMenu,
footer {
    display: none !important;
}

/* Sidebar */
[data-testid="stSidebar"] {
    background: var(--bg-sidebar) !important;
    border-right: 1px solid var(--border-sidebar) !important;
}
[data-testid="stSidebarContent"],
[data-testid="stSidebarUserContent"] {
    background: transparent !important;
    color: var(--text-primary) !important;
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

/* Metric cards */
[data-testid="stMetric"] {
    background: var(--bg-card) !important;
    backdrop-filter: blur(12px);
    border: 1px solid var(--border-subtle) !important;
    border-radius: 8px !important;
    padding: 12px 14px !important;
    min-height: 86px;
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
    white-space: normal !important;
    overflow-wrap: anywhere !important;
    text-overflow: clip !important;
    line-height: 1.15 !important;
}
[data-testid="stMetricLabel"] * {
    white-space: normal !important;
    overflow-wrap: anywhere !important;
    text-overflow: clip !important;
    line-height: 1.15 !important;
}
[data-testid="stMetricValue"] {
    color: var(--text-primary) !important;
    font-weight: 700 !important;
    font-size: 1.35rem !important;
    font-family: var(--font-body) !important;
}

/* Headings */
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
p, li { color: var(--text-primary) !important; font-family: var(--font-body) !important; }
[data-testid="stMarkdownContainer"],
[data-testid="stMarkdownContainer"] *:not([class*="icon"]):not([class*="material"]) {
    color: var(--text-primary) !important;
    font-family: var(--font-body);
}

/* DataFrames */
[data-testid="stDataFrame"] {
    border: 1px solid var(--border-subtle) !important;
    border-radius: 8px;
    overflow: hidden;
}

/* Buttons */
.stButton > button,
[data-testid="stButton"] button,
button[data-testid^="stBaseButton"] {
    background: var(--btn-bg) !important;
    border: 1px solid var(--btn-border) !important;
    color: var(--text-primary) !important;
    border-radius: 7px !important;
    font-weight: 600;
    font-family: var(--font-body) !important;
    min-height: 2.15rem;
    padding: 0.32rem 0.58rem;
    transition: border-color 0.18s ease, background 0.18s ease, color 0.18s ease;
    backdrop-filter: blur(8px);
}
.stButton > button p,
[data-testid="stButton"] button p,
button[data-testid^="stBaseButton"] p {
    color: inherit !important;
    white-space: normal !important;
    overflow-wrap: anywhere !important;
    line-height: 1.15 !important;
    font-size: 0.82rem !important;
}
.stButton > button:hover,
[data-testid="stButton"] button:hover,
button[data-testid^="stBaseButton"]:hover {
    background: var(--btn-bg-hover) !important;
    border-color: var(--border-strong) !important;
    box-shadow: var(--btn-hover-shadow) !important;
}
.stButton > button:hover p,
.stButton > button:hover span:not([class*="icon"]):not([class*="material"]),
[data-testid="stButton"] button:hover p,
[data-testid="stButton"] button:hover span:not([class*="icon"]):not([class*="material"]),
button[data-testid^="stBaseButton"]:hover p,
button[data-testid^="stBaseButton"]:hover span:not([class*="icon"]):not([class*="material"]) {
    color: var(--text-primary) !important;
    -webkit-text-fill-color: var(--text-primary) !important;
}
.stButton > button[kind="primary"],
[data-testid="stButton"] button[kind="primary"],
button[data-testid="stBaseButton-primary"] {
    background: linear-gradient(135deg, var(--accent), var(--accent2)) !important;
    border: none !important;
    color: #ffffff !important;
    box-shadow: 0 4px 16px rgba(var(--accent-rgb), 0.35) !important;
}
.stButton > button[kind="primary"] p,
[data-testid="stButton"] button[kind="primary"] p,
button[data-testid="stBaseButton-primary"] p,
.stButton > button[kind="primary"] span:not([class*="icon"]):not([class*="material"]),
[data-testid="stButton"] button[kind="primary"] span:not([class*="icon"]):not([class*="material"]),
button[data-testid="stBaseButton-primary"] span:not([class*="icon"]):not([class*="material"]) {
    color: #ffffff !important;
    -webkit-text-fill-color: #ffffff !important;
}
.stButton > button[kind="primary"]:hover,
[data-testid="stButton"] button[kind="primary"]:hover,
button[data-testid="stBaseButton-primary"]:hover {
    box-shadow: 0 6px 24px rgba(var(--accent-rgb), 0.55) !important;
}
.stButton > button[kind="primary"]:hover p,
.stButton > button[kind="primary"]:hover span:not([class*="icon"]):not([class*="material"]),
[data-testid="stButton"] button[kind="primary"]:hover p,
[data-testid="stButton"] button[kind="primary"]:hover span:not([class*="icon"]):not([class*="material"]),
button[data-testid="stBaseButton-primary"]:hover p,
button[data-testid="stBaseButton-primary"]:hover span:not([class*="icon"]):not([class*="material"]) {
    color: #ffffff !important;
    -webkit-text-fill-color: #ffffff !important;
}
.stButton > button:disabled,
[data-testid="stButton"] button:disabled,
button[data-testid^="stBaseButton"]:disabled {
    background: rgba(var(--accent-rgb), 0.05) !important;
    border-color: var(--border-subtle) !important;
    box-shadow: none !important;
    color: var(--text-muted) !important;
    opacity: 0.76 !important;
}
.stButton > button:disabled p,
[data-testid="stButton"] button:disabled p,
button[data-testid^="stBaseButton"]:disabled p {
    color: var(--text-muted) !important;
}

/* Expanders */
[data-testid="stExpander"] {
    background: var(--bg-expander) !important;
    border: 1px solid var(--border-subtle) !important;
    border-radius: 8px;
    backdrop-filter: blur(8px);
}

/* Dividers */
hr {
    border: none !important;
    height: 1px;
    background: var(--hr-bg) !important;
    margin: 16px 0;
}

/* Charts */
[data-testid="stArrowVegaLiteChart"],
[data-testid="stVegaLiteChart"] {
    background: var(--bg-card) !important;
    border: 1px solid var(--border-subtle) !important;
    border-radius: 8px !important;
    box-shadow: var(--metric-shadow) !important;
    padding: 0.45rem !important;
    overflow: hidden !important;
}
[data-testid="stArrowVegaLiteChart"] canvas,
[data-testid="stVegaLiteChart"] canvas,
[data-testid="stArrowVegaLiteChart"] svg,
[data-testid="stVegaLiteChart"] svg,
.vega-embed,
.vega-embed canvas,
.vega-embed svg {
    background: transparent !important;
}
[data-testid="stArrowVegaLiteChart"] svg text,
[data-testid="stVegaLiteChart"] svg text,
.vega-embed svg text {
    fill: var(--text-secondary) !important;
}
.ow-chart-title {
    color: var(--text-primary);
    font-size: 0.82rem;
    font-weight: 850;
    margin: 0.55rem 0 0.28rem;
}
.ow-chart-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 0.85rem;
    margin: 0.35rem 0 0.85rem;
}

/* Inputs */
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
.stApp [data-baseweb="input"],
.stApp [data-baseweb="base-input"],
.stApp [data-baseweb="select"] > div {
    background: var(--bg-input) !important;
    border-color: var(--border-normal) !important;
    color: var(--text-input) !important;
    font-family: var(--font-body) !important;
}
.stApp [data-baseweb="input"] input,
.stApp [data-baseweb="base-input"] input,
.stApp [data-baseweb="select"] input,
.stApp [data-baseweb="select"] span,
.stApp [data-baseweb="select"] div {
    color: var(--text-input) !important;
    -webkit-text-fill-color: var(--text-input) !important;
}
.stApp [data-baseweb="select"] svg {
    color: var(--text-input) !important;
    fill: var(--text-input) !important;
}
[data-testid="stSelectboxVirtualDropdown"],
div:has(> [data-testid="stSelectboxVirtualDropdown"]),
div:has(> div > [data-testid="stSelectboxVirtualDropdown"]) {
    background: var(--bg-card) !important;
    border-color: var(--border-normal) !important;
    color: var(--text-primary) !important;
}
[data-testid="stSelectboxVirtualDropdown"] [role="option"],
[data-testid="stSelectboxVirtualDropdown"] [role="option"] *,
ul[data-testid="stSelectboxVirtualDropdown"] li,
ul[data-testid="stSelectboxVirtualDropdown"] li * {
    color: var(--text-primary) !important;
    -webkit-text-fill-color: var(--text-primary) !important;
}
[data-testid="stSelectboxVirtualDropdown"] [role="option"],
ul[data-testid="stSelectboxVirtualDropdown"] li {
    background: var(--bg-card) !important;
}
[data-testid="stSelectboxVirtualDropdown"] [role="option"]:hover,
[data-testid="stSelectboxVirtualDropdown"] [role="option"][aria-selected="true"],
ul[data-testid="stSelectboxVirtualDropdown"] li:hover,
ul[data-testid="stSelectboxVirtualDropdown"] li[aria-selected="true"] {
    background: rgba(var(--accent-rgb), 0.16) !important;
    color: var(--text-primary) !important;
}
.stNumberInput button,
.stNumberInput [role="button"],
[data-testid="stNumberInput"] button,
[data-testid="stNumberInput"] [role="button"] {
    background: var(--bg-input) !important;
    border-color: var(--border-normal) !important;
    color: var(--text-input) !important;
    -webkit-text-fill-color: var(--text-input) !important;
}
.stNumberInput button:hover,
.stNumberInput [role="button"]:hover,
[data-testid="stNumberInput"] button:hover,
[data-testid="stNumberInput"] [role="button"]:hover {
    border-color: var(--border-strong) !important;
    box-shadow: 0 0 12px rgba(var(--accent-rgb), 0.12) !important;
}
.stApp [data-baseweb="input"]:focus-within,
.stApp [data-baseweb="base-input"]:focus-within,
.stApp [data-baseweb="select"]:focus-within > div {
    border-color: var(--border-strong) !important;
    box-shadow: 0 0 12px rgba(var(--accent-rgb), 0.12) !important;
}
.stSelectbox > div > div:focus-within,
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {
    border-color: var(--border-strong) !important;
    box-shadow: 0 0 12px rgba(var(--accent-rgb), 0.12) !important;
}

/* Slider */
.stSlider > div > div > div > div {
    background: var(--slider-track) !important;
}

/* Tabs */
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

/* Captions */
.stCaption, [data-testid="stCaptionContainer"] {
    color: var(--text-muted) !important;
    font-family: var(--font-body) !important;
}

/* Code blocks */
code, pre, .stCodeBlock {
    font-family: var(--font-mono) !important;
    background: var(--bg-input) !important;
    border: 1px solid var(--border-subtle) !important;
    border-radius: 6px;
    color: var(--accent) !important;
}

/* Scrollbars */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--scrollbar-track); }
::-webkit-scrollbar-thumb { background: var(--scrollbar-thumb); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--scrollbar-hover); }

/* Animations */
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.5} }
@keyframes black-ice-shift {
    0%   { background-position: 0% 50%; }
    50%  { background-position: 100% 50%; }
    100% { background-position: 0% 50%; }
}
.live-indicator { animation: pulse 2s ease-in-out infinite; }

/* Production navigation shell */
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
[data-testid="stSidebar"] .stButton > button,
[data-testid="stSidebar"] [data-testid="stButton"] button,
[data-testid="stSidebar"] button[data-testid^="stBaseButton"] {
    justify-content: flex-start !important;
    min-height: 36px;
    border-radius: 7px !important;
    font-size: 0.84rem !important;
    font-weight: 760 !important;
    box-shadow: none !important;
}
[data-testid="stSidebar"] .stButton > button p,
[data-testid="stSidebar"] [data-testid="stButton"] button p,
[data-testid="stSidebar"] button[data-testid^="stBaseButton"] p {
    white-space: nowrap !important;
    overflow-wrap: normal !important;
    font-size: 0.84rem !important;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"],
[data-testid="stSidebar"] [data-testid="stButton"] button[kind="primary"],
[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] {
    background: rgba(var(--accent-rgb), 0.17) !important;
    border: 1px solid rgba(var(--accent-rgb), 0.45) !important;
    color: var(--accent) !important;
    box-shadow: inset 3px 0 0 var(--accent) !important;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"] p,
[data-testid="stSidebar"] [data-testid="stButton"] button[kind="primary"] p,
[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] p {
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

/* Status badges */
.status-badge {
    display: inline-block; padding: 2px 8px; border-radius: 12px;
    font-size: 0.7rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;
}
.badge-healthy  { background: rgba(34,197,94,0.20); color:#4ade80; border:1px solid rgba(34,197,94,0.30); }
.badge-warning  { background: rgba(251,191,36,0.20); color:#fbbf24; border:1px solid rgba(251,191,36,0.30); }
.badge-critical { background: rgba(239,68,68,0.20);  color:#f87171; border:1px solid rgba(239,68,68,0.30); }

/* Metric card container (custom) */
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
.ow-filter-strip-shell {
    border-bottom: 1px solid var(--border-subtle);
    margin: -0.2rem 0 0.35rem;
    padding-bottom: 0.2rem;
}
.ow-filter-strip-kicker {
    color: var(--text-muted);
    font-size: 0.66rem;
    font-weight: 850;
    letter-spacing: 0.08em;
    text-transform: uppercase;
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
.ow-shell-snapshot-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(155px, 1fr));
    gap: 0.65rem;
    margin: 0.35rem 0 0.85rem;
}
.ow-shell-snapshot-card {
    min-width: 0;
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    background: rgba(var(--accent-rgb), 0.045);
    padding: 0.68rem 0.78rem;
}
.ow-shell-snapshot-card span,
.ow-shell-snapshot-label {
    display: block;
    color: var(--text-muted);
    font-size: 0.66rem;
    font-weight: 850;
    letter-spacing: 0.04em;
    line-height: 1.22;
    text-transform: uppercase;
    overflow-wrap: anywhere;
}
.ow-shell-snapshot-card strong,
.ow-shell-snapshot-value {
    display: block;
    color: var(--text-primary);
    font-size: 0.96rem;
    font-weight: 850;
    line-height: 1.28;
    margin-top: 0.26rem;
    overflow-wrap: anywhere;
}
.ow-workload-lane-card {
    min-height: 7.1rem;
    display: flex;
    flex-direction: column;
    gap: 0.24rem;
}
.ow-workload-lane-label {
    color: var(--text-muted);
    font-size: 0.66rem;
    font-weight: 850;
    letter-spacing: 0.05em;
    text-transform: uppercase;
}
.ow-workload-lane-state {
    color: var(--text-primary);
    font-size: 1.02rem;
    font-weight: 850;
    line-height: 1.2;
    overflow-wrap: anywhere;
}
.ow-workload-lane-value {
    color: var(--accent2);
    font-size: 0.9rem;
    font-weight: 800;
    line-height: 1.25;
    overflow-wrap: anywhere;
}
.ow-signal-board {
    margin: 0.28rem 0 0.9rem;
}
.ow-signal-title {
    color: var(--text-primary);
    font-size: 0.92rem;
    font-weight: 850;
    margin: 0.2rem 0 0.48rem;
}
.ow-signal-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(175px, 1fr));
    gap: 0.72rem;
}
.ow-signal-card {
    min-width: 0;
    min-height: 6.2rem;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    gap: 0.48rem;
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    background: var(--bg-card);
    box-shadow: var(--metric-shadow);
    padding: 0.78rem 0.86rem;
}
.ow-signal-card-top {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.52rem;
}
.ow-signal-label {
    color: var(--text-muted);
    font-size: 0.66rem;
    font-weight: 850;
    letter-spacing: 0.04em;
    line-height: 1.24;
    text-transform: uppercase;
    overflow-wrap: anywhere;
}
.ow-signal-pill {
    flex: 0 0 auto;
    max-width: 54%;
    border: 1px solid rgba(var(--accent-rgb), 0.16);
    border-radius: 999px;
    background: rgba(var(--accent-rgb), 0.08);
    color: var(--accent);
    font-size: 0.64rem;
    font-weight: 850;
    line-height: 1.1;
    padding: 0.18rem 0.46rem;
    overflow-wrap: anywhere;
    text-align: center;
}
.ow-signal-value {
    color: var(--text-primary);
    font-size: 1.2rem;
    font-weight: 850;
    line-height: 1.15;
    overflow-wrap: anywhere;
}
.ow-signal-detail {
    color: var(--text-secondary);
    font-size: 0.76rem;
    line-height: 1.35;
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
[data-testid="stMarkdownContainer"] .ow-scope-chip strong {
    color: var(--text-primary) !important;
}
[data-testid="stMarkdownContainer"] .ow-section-subtitle,
[data-testid="stMarkdownContainer"] .ow-scope-chip,
[data-testid="stMarkdownContainer"] .ow-empty-list span,
[data-testid="stMarkdownContainer"] .ow-section-guide-detail,
[data-testid="stMarkdownContainer"] .ow-evidence-contract-card,
[data-testid="stMarkdownContainer"] .ow-brief-detail {
    color: var(--text-secondary) !important;
}
[data-testid="stMarkdownContainer"] .ow-section-kicker,
[data-testid="stMarkdownContainer"] .ow-filter-strip-kicker,
[data-testid="stMarkdownContainer"] .ow-scope-chip span,
[data-testid="stMarkdownContainer"] .ow-run-context,
[data-testid="stMarkdownContainer"] .ow-section-guide-label,
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
    .block-container {
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }
    .ow-brief-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
    }
    .ow-shell-snapshot-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
    }
    .ow-signal-grid {
        grid-template-columns: repeat(auto-fit, minmax(165px, 1fr)) !important;
    }
    .ow-section-guide {
        grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
    }
    .ow-evidence-contract {
        grid-template-columns: 1fr !important;
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
        grid-template-columns: 1fr !important;
    }
    .ow-brief-grid {
        grid-template-columns: 1fr !important;
    }
    .ow-shell-snapshot-grid {
        grid-template-columns: 1fr !important;
    }
    .ow-signal-grid {
        grid-template-columns: 1fr !important;
    }
}

/* SNOWFLAKE WHITE theme extras */
.terminal-extra [data-testid="stMetric"] {
    border-top: 3px solid rgba(41,181,232,0.75) !important;
}

</style>
"""

# Theme picker HTML
_THEME_EXTRAS = {
    "carbon": """
<style>
/* Snowflake Dark: make Snowflake blue the dominant navigation treatment. */
.stApp .stButton > button[kind="primary"],
.stApp [data-testid="stButton"] button[kind="primary"],
.stApp button[data-testid="stBaseButton-primary"] {
    color: #ffffff !important;
    background: linear-gradient(135deg, #0068b7, #003545) !important;
    border: 1px solid rgba(113,211,220,0.64) !important;
    box-shadow: 0 4px 18px rgba(41,181,232,0.26) !important;
}
.stApp .stButton > button[kind="primary"] p,
.stApp [data-testid="stButton"] button[kind="primary"] p,
.stApp button[data-testid="stBaseButton-primary"] p {
    color: #ffffff !important;
    -webkit-text-fill-color: #ffffff !important;
}
.stApp .stButton > button[kind="primary"]:hover,
.stApp [data-testid="stButton"] button[kind="primary"]:hover,
.stApp button[data-testid="stBaseButton-primary"]:hover {
    color: #ffffff !important;
    background: linear-gradient(135deg, #0079d6, #004568) !important;
    border-color: rgba(113,211,220,0.90) !important;
}
.stApp .stButton > button[kind="primary"]:hover p,
.stApp [data-testid="stButton"] button[kind="primary"]:hover p,
.stApp button[data-testid="stBaseButton-primary"]:hover p {
    color: #ffffff !important;
    -webkit-text-fill-color: #ffffff !important;
}
.stApp [data-testid="stMain"] .stButton > button[kind="secondary"],
.stApp [data-testid="stMain"] [data-testid="stButton"] button[kind="secondary"],
.stApp [data-testid="stMain"] button[data-testid="stBaseButton-secondary"] {
    color: #eef8fb !important;
    -webkit-text-fill-color: #eef8fb !important;
    background: linear-gradient(135deg, rgba(17,86,127,0.58), rgba(0,53,69,0.72)) !important;
    border-color: rgba(113,211,220,0.56) !important;
}
.stApp [data-testid="stMain"] .stButton > button[kind="secondary"] p,
.stApp [data-testid="stMain"] [data-testid="stButton"] button[kind="secondary"] p,
.stApp [data-testid="stMain"] button[data-testid="stBaseButton-secondary"] p,
.stApp [data-testid="stMain"] .stButton > button[kind="secondary"] span:not([class*="icon"]):not([class*="material"]),
.stApp [data-testid="stMain"] [data-testid="stButton"] button[kind="secondary"] span:not([class*="icon"]):not([class*="material"]),
.stApp [data-testid="stMain"] button[data-testid="stBaseButton-secondary"] span:not([class*="icon"]):not([class*="material"]) {
    color: #eef8fb !important;
    -webkit-text-fill-color: #eef8fb !important;
}
.stApp [data-testid="stMain"] .stButton > button[kind="secondary"]:hover,
.stApp [data-testid="stMain"] [data-testid="stButton"] button[kind="secondary"]:hover,
.stApp [data-testid="stMain"] button[data-testid="stBaseButton-secondary"]:hover {
    color: #ffffff !important;
    -webkit-text-fill-color: #ffffff !important;
    background: linear-gradient(135deg, #0068b7, #003545) !important;
    border-color: rgba(113,211,220,0.96) !important;
    box-shadow: 0 4px 18px rgba(41,181,232,0.34) !important;
}
.stApp [data-testid="stMain"] .stButton > button[kind="secondary"]:hover p,
.stApp [data-testid="stMain"] [data-testid="stButton"] button[kind="secondary"]:hover p,
.stApp [data-testid="stMain"] button[data-testid="stBaseButton-secondary"]:hover p,
.stApp [data-testid="stMain"] .stButton > button[kind="secondary"]:hover span:not([class*="icon"]):not([class*="material"]),
.stApp [data-testid="stMain"] [data-testid="stButton"] button[kind="secondary"]:hover span:not([class*="icon"]):not([class*="material"]),
.stApp [data-testid="stMain"] button[data-testid="stBaseButton-secondary"]:hover span:not([class*="icon"]):not([class*="material"]) {
    color: #ffffff !important;
    -webkit-text-fill-color: #ffffff !important;
}
.stApp [data-testid="stMain"] .ow-signal-card:hover,
.stApp [data-testid="stMain"] .ow-shell-snapshot-card:hover,
.stApp [data-testid="stMain"] .ow-section-guide-card:hover {
    background: rgba(18,42,55,0.98) !important;
    border-color: rgba(113,211,220,0.60) !important;
    box-shadow: 0 8px 28px rgba(41,181,232,0.18) !important;
}
.stApp [data-testid="stMain"] .ow-signal-card:hover,
.stApp [data-testid="stMain"] .ow-signal-card:hover *,
.stApp [data-testid="stMain"] .ow-shell-snapshot-card:hover,
.stApp [data-testid="stMain"] .ow-shell-snapshot-card:hover *,
.stApp [data-testid="stMain"] .ow-section-guide-card:hover,
.stApp [data-testid="stMain"] .ow-section-guide-card:hover * {
    color: #eef8fb !important;
    -webkit-text-fill-color: #eef8fb !important;
}
[data-testid="stSidebar"] .stButton > button,
[data-testid="stSidebar"] [data-testid="stButton"] button,
[data-testid="stSidebar"] button[data-testid^="stBaseButton"] {
    color: var(--text-primary) !important;
    background: linear-gradient(135deg, rgba(41,181,232,0.10), rgba(113,211,220,0.06)) !important;
    border-color: rgba(41,181,232,0.28) !important;
    box-shadow: none !important;
}
[data-testid="stSidebar"] .stButton > button p,
[data-testid="stSidebar"] [data-testid="stButton"] button p,
[data-testid="stSidebar"] button[data-testid^="stBaseButton"] p {
    color: inherit !important;
}
[data-testid="stSidebar"] .stButton > button:hover,
[data-testid="stSidebar"] [data-testid="stButton"] button:hover,
[data-testid="stSidebar"] button[data-testid^="stBaseButton"]:hover {
    color: #ffffff !important;
    background: linear-gradient(135deg, rgba(41,181,232,0.28), rgba(0,104,183,0.52)) !important;
    border-color: rgba(113,211,220,0.70) !important;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"],
[data-testid="stSidebar"] [data-testid="stButton"] button[kind="primary"],
[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] {
    color: #ffffff !important;
    background: linear-gradient(135deg, #003f73, #0068b7) !important;
    border-color: rgba(113,211,220,0.96) !important;
    box-shadow: inset 4px 0 0 #71D3DC, 0 3px 14px rgba(41,181,232,0.30) !important;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"] p,
[data-testid="stSidebar"] [data-testid="stButton"] button[kind="primary"] p,
[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] p {
    color: #ffffff !important;
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary {
    color: #ffffff !important;
    background: linear-gradient(135deg, #0068b7, #003545) !important;
    border: 1px solid rgba(41,181,232,0.70) !important;
    border-bottom: 1px solid rgba(41,181,232,0.70) !important;
    box-shadow: 0 2px 10px rgba(41,181,232,0.18) !important;
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary,
[data-testid="stSidebar"] [data-testid="stExpander"] summary > span,
[data-testid="stSidebar"] [data-testid="stExpander"] summary > span > div,
[data-testid="stSidebar"] [data-testid="stExpander"] summary p,
[data-testid="stSidebar"] [data-testid="stExpander"] summary span {
    color: #ffffff !important;
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover {
    background: linear-gradient(135deg, #29B5E8, #0068b7) !important;
    border-color: rgba(113,211,220,0.95) !important;
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] .ow-live-pill {
    color: #71D3DC !important;
}
[data-testid="stMetric"] {
    border-top: 3px solid rgba(41,181,232,0.75) !important;
}
.stTabs [data-baseweb="tab-list"] {
    background: rgba(11,27,38,0.84) !important;
    border-bottom: 2px solid rgba(41,181,232,0.55);
}
.stTabs [data-baseweb="tab"] {
    color: #9bddea !important;
    font-weight: 700;
}
.stTabs [aria-selected="true"] {
    color: #ffffff !important;
    background: linear-gradient(135deg, #0068b7, #003545) !important;
    border-color: rgba(41,181,232,0.72) !important;
}
</style>
""",
    "terminal": """ <style> /* Snowflake White: reduce glare and make navigation decisively blue. */ .stApp .stButton > button, .stApp [data-testid="stButton"] button, .stApp button[data-testid^="stBaseButton"] {     color: #102a43 !important;     background: linear-gradient(135deg, #ffffff, #edf8fd) !important;     border-color: rgba(0,104,183,0.38) !important; } .stApp .stButton > button:hover, .stApp [data-testid="stButton"] button:hover, .stApp button[data-testid^="stBaseButton"]:hover {     color: #004f8f !important;     background: linear-gradient(135deg, #f8fdff, #d9f1fb) !important;     border-color: rgba(0,104,183,0.58) !important; } .stApp .stButton > button p, .stApp [data-testid="stButton"] button p, .stApp button[data-testid^="stBaseButton"] p {     color: inherit !important; } .stApp .stButton > button[kind="primary"], .stApp [data-testid="stButton"] button[kind="primary"], .stApp button[data-testid="stBaseButton-primary"] {     color: #ffffff !important;     background: linear-gradient(135deg, #0068b7, #29B5E8) !important;     border-color: rgba(0,104,183,0.78) !important; } .stApp .stButton > button[kind="primary"] p, .stApp [data-testid="stButton"] button[kind="primary"] p, .stApp button[data-testid="stBaseButton-primary"] p {     color: #ffffff !important; } .stMain [data-testid="stMarkdownContainer"], .stMain [data-testid="stMarkdownContainer"] p {     color: #102a43 !important; } .stMain [data-testid="stCaptionContainer"], .stMain [data-testid="stCaptionContainer"] p, .stMain [data-testid="stCaptionContainer"] span {     color: #526b7a !important; } [data-testid="stSidebar"] label, [data-testid="stSidebar"] .stRadio > label, [data-testid="stSidebar"] p {     color: #1f4e6b !important; } .stApp [data-testid="stSidebar"] .stButton > button, .stApp [data-testid="stSidebar"] [data-testid="stButton"] button, .stApp [data-testid="stSidebar"] button[data-testid^="stBaseButton"] {     color: #102a43 !important;     background: linear-gradient(135deg, #ffffff, #eaf6fb) !important;     border-color: rgba(0,104,183,0.28) !important;     box-shadow: none !important; } .stApp [data-testid="stSidebar"] .stButton > button p, .stApp [data-testid="stSidebar"] [data-testid="stButton"] button p, .stApp [data-testid="stSidebar"] button[data-testid^="stBaseButton"] p {     color: #102a43 !important; } .stApp [data-testid="stSidebar"] .stButton > button:hover, .stApp [data-testid="stSidebar"] [data-testid="stButton"] button:hover, .stApp [data-testid="stSidebar"] button[data-testid^="stBaseButton"]:hover {     color: #003f73 !important;     background: linear-gradient(135deg, #f8fdff, #d9f1fb) !important;     border-color: rgba(0,104,183,0.55) !important;     box-shadow: 0 2px 9px rgba(0,104,183,0.12) !important; } [data-testid="stSidebar"] .stRadio > div > label:hover {     color: #0068b7 !important;     background: rgba(0,104,183,0.08); } [data-testid="stSidebar"] .stRadio > div > label[data-checked="true"] {     color: #0068b7 !important;     background: rgba(0,104,183,0.13);     border-left: 3px solid #0068b7; } .stApp [data-testid="stSidebar"] .stButton > button[kind="primary"], .stApp [data-testid="stSidebar"] [data-testid="stButton"] button[kind="primary"], .stApp [data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] {     color: #ffffff !important;     background: linear-gradient(135deg, #0068b7, #00528f) !important;     border-color: rgba(0,63,115,0.94) !important;     box-shadow: inset 4px 0 0 #71D3DC, 0 3px 13px rgba(0,104,183,0.24) !important; } .stApp [data-testid="stSidebar"] .stButton > button[kind="primary"] p, .stApp [data-testid="stSidebar"] [data-testid="stButton"] button[kind="primary"] p, .stApp [data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] p {     color: #ffffff !important; } [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] .ow-live-pill {     color: #0068b7 !important; } [data-testid="stMetric"] {     border-top: 3px solid rgba(0,104,183,0.75) !important; } [data-testid="stMetricValue"] { color: #102a43 !important; } [data-testid="stMetricLabel"] { color: #526b7a !important; } [data-testid="stExpander"] {     background: #ffffff !important;     border-color: #b7d5e5 !important; } [data-testid="stExpander"] summary, [data-testid="stExpander"] summary > div, [data-testid="stExpander"] summary p, [data-testid="stExpander"] summary span, [data-testid="stExpander"] details, [data-testid="stExpander"] [data-testid="stMarkdownContainer"], [data-testid="stExpander"] [data-testid="stMarkdownContainer"] p {     color: #102a43 !important; } [data-testid="stExpander"] summary {     background: #ffffff !important;     border-radius: 7px !important; } [data-testid="stSidebar"] [data-testid="stExpander"] summary {     color: #ffffff !important;     background: linear-gradient(135deg, #0068b7, #00528f) !important;     border: 1px solid rgba(0,82,143,0.78) !important;     border-bottom: 1px solid rgba(0,82,143,0.78) !important;     box-shadow: 0 2px 9px rgba(0,104,183,0.16) !important; } [data-testid="stSidebar"] [data-testid="stExpander"] summary, [data-testid="stSidebar"] [data-testid="stExpander"] summary > span, [data-testid="stSidebar"] [data-testid="stExpander"] summary > span > div, [data-testid="stSidebar"] [data-testid="stExpander"] summary p, [data-testid="stSidebar"] [data-testid="stExpander"] summary span {     color: #ffffff !important; } [data-testid="stSidebar"] [data-testid="stExpander"] summary:hover {     background: linear-gradient(135deg, #0079d6, #005fa8) !important;     border-color: rgba(0,104,183,0.90) !important; } [data-testid="stExpander"] summary:hover, [data-testid="stExpander"] summary:hover p, [data-testid="stExpander"] summary:hover span {     color: #0068b7 !important; } [data-testid="stSidebar"] [data-testid="stExpander"] summary:hover, [data-testid="stSidebar"] [data-testid="stExpander"] summary:hover > span, [data-testid="stSidebar"] [data-testid="stExpander"] summary:hover p, [data-testid="stSidebar"] [data-testid="stExpander"] summary:hover span {     color: #ffffff !important; } .stApp .stTabs [data-baseweb="tab-list"] {     background: #dceff7 !important;     border-bottom: 2px solid rgba(0,104,183,0.55); } .stApp .stTabs [data-baseweb="tab"] {     color: #102a43 !important;     font-weight: 650; } .stApp .stTabs [data-baseweb="tab"] p {     color: inherit !important; } .stApp .stTabs [aria-selected="true"] {     color: #ffffff !important;     background: linear-gradient(135deg, #0068b7, #00528f) !important;     border-color: rgba(0,82,143,0.72) !important; } .stApp .stTabs [aria-selected="true"] p {     color: #ffffff !important; } </style> """,
}

_THEME_EXTRAS["carbon"] += """
<style>
/* Snowflake Dark: broad main-surface button contrast so subsection hover states cannot inherit light text on light backgrounds. */
.stApp [data-testid="stMain"] .stButton > button,
.stApp [data-testid="stMain"] [data-testid="stButton"] button,
.stApp [data-testid="stMain"] button[data-testid^="stBaseButton"] {
    color: #eef8fb !important;
    -webkit-text-fill-color: #eef8fb !important;
    background: linear-gradient(135deg, rgba(17,86,127,0.70), rgba(0,53,69,0.88)) !important;
    border-color: rgba(113,211,220,0.62) !important;
}
.stApp [data-testid="stMain"] .stButton > button p,
.stApp [data-testid="stMain"] [data-testid="stButton"] button p,
.stApp [data-testid="stMain"] button[data-testid^="stBaseButton"] p,
.stApp [data-testid="stMain"] .stButton > button span:not([class*="icon"]):not([class*="material"]),
.stApp [data-testid="stMain"] [data-testid="stButton"] button span:not([class*="icon"]):not([class*="material"]),
.stApp [data-testid="stMain"] button[data-testid^="stBaseButton"] span:not([class*="icon"]):not([class*="material"]),
.stApp [data-testid="stMain"] .stButton > button div,
.stApp [data-testid="stMain"] [data-testid="stButton"] button div,
.stApp [data-testid="stMain"] button[data-testid^="stBaseButton"] div {
    color: #eef8fb !important;
    -webkit-text-fill-color: #eef8fb !important;
}
.stApp [data-testid="stMain"] .stButton > button:hover,
.stApp [data-testid="stMain"] [data-testid="stButton"] button:hover,
.stApp [data-testid="stMain"] button[data-testid^="stBaseButton"]:hover {
    color: #ffffff !important;
    -webkit-text-fill-color: #ffffff !important;
    background: linear-gradient(135deg, #0068b7, #003545) !important;
    border-color: rgba(113,211,220,0.98) !important;
    box-shadow: 0 4px 18px rgba(41,181,232,0.34) !important;
}
.stApp [data-testid="stMain"] .stButton > button:hover p,
.stApp [data-testid="stMain"] [data-testid="stButton"] button:hover p,
.stApp [data-testid="stMain"] button[data-testid^="stBaseButton"]:hover p,
.stApp [data-testid="stMain"] .stButton > button:hover span:not([class*="icon"]):not([class*="material"]),
.stApp [data-testid="stMain"] [data-testid="stButton"] button:hover span:not([class*="icon"]):not([class*="material"]),
.stApp [data-testid="stMain"] button[data-testid^="stBaseButton"]:hover span:not([class*="icon"]):not([class*="material"]),
.stApp [data-testid="stMain"] .stButton > button:hover div,
.stApp [data-testid="stMain"] [data-testid="stButton"] button:hover div,
.stApp [data-testid="stMain"] button[data-testid^="stBaseButton"]:hover div {
    color: #ffffff !important;
    -webkit-text-fill-color: #ffffff !important;
}
</style>
"""

_THEME_EXTRAS["terminal"] += """
<style>
/* Snowflake White: match dark-mode selector strength so theme switching cannot leave stale dark button/card rules active. */
.stApp [data-testid="stMain"] .stButton > button[kind="secondary"],
.stApp [data-testid="stMain"] [data-testid="stButton"] button[kind="secondary"],
.stApp [data-testid="stMain"] button[data-testid="stBaseButton-secondary"] {
    color: #102a43 !important;
    -webkit-text-fill-color: #102a43 !important;
    background: linear-gradient(135deg, #ffffff, #edf8fd) !important;
    border-color: rgba(0,104,183,0.38) !important;
}
.stApp [data-testid="stMain"] .stButton > button[kind="secondary"] p,
.stApp [data-testid="stMain"] [data-testid="stButton"] button[kind="secondary"] p,
.stApp [data-testid="stMain"] button[data-testid="stBaseButton-secondary"] p,
.stApp [data-testid="stMain"] .stButton > button[kind="secondary"] span:not([class*="icon"]):not([class*="material"]),
.stApp [data-testid="stMain"] [data-testid="stButton"] button[kind="secondary"] span:not([class*="icon"]):not([class*="material"]),
.stApp [data-testid="stMain"] button[data-testid="stBaseButton-secondary"] span:not([class*="icon"]):not([class*="material"]) {
    color: #102a43 !important;
    -webkit-text-fill-color: #102a43 !important;
}
.stApp [data-testid="stMain"] .stButton > button[kind="secondary"]:hover,
.stApp [data-testid="stMain"] [data-testid="stButton"] button[kind="secondary"]:hover,
.stApp [data-testid="stMain"] button[data-testid="stBaseButton-secondary"]:hover {
    color: #003f73 !important;
    -webkit-text-fill-color: #003f73 !important;
    background: linear-gradient(135deg, #f8fdff, #d9f1fb) !important;
    border-color: rgba(0,104,183,0.58) !important;
    box-shadow: 0 2px 9px rgba(0,104,183,0.12) !important;
}
.stApp [data-testid="stMain"] .stButton > button[kind="secondary"]:hover p,
.stApp [data-testid="stMain"] [data-testid="stButton"] button[kind="secondary"]:hover p,
.stApp [data-testid="stMain"] button[data-testid="stBaseButton-secondary"]:hover p,
.stApp [data-testid="stMain"] .stButton > button[kind="secondary"]:hover span:not([class*="icon"]):not([class*="material"]),
.stApp [data-testid="stMain"] [data-testid="stButton"] button[kind="secondary"]:hover span:not([class*="icon"]):not([class*="material"]),
.stApp [data-testid="stMain"] button[data-testid="stBaseButton-secondary"]:hover span:not([class*="icon"]):not([class*="material"]) {
    color: #003f73 !important;
    -webkit-text-fill-color: #003f73 !important;
}
.stApp [data-testid="stMain"] .ow-signal-card:hover,
.stApp [data-testid="stMain"] .ow-shell-snapshot-card:hover,
.stApp [data-testid="stMain"] .ow-section-guide-card:hover {
    background: #ffffff !important;
    border-color: rgba(0,104,183,0.42) !important;
    box-shadow: 0 2px 8px rgba(0,104,183,0.10) !important;
}
.stApp [data-testid="stMain"] .ow-signal-card:hover,
.stApp [data-testid="stMain"] .ow-signal-card:hover *,
.stApp [data-testid="stMain"] .ow-shell-snapshot-card:hover,
.stApp [data-testid="stMain"] .ow-shell-snapshot-card:hover *,
.stApp [data-testid="stMain"] .ow-section-guide-card:hover,
.stApp [data-testid="stMain"] .ow-section-guide-card:hover * {
    color: #102a43 !important;
    -webkit-text-fill-color: #102a43 !important;
}
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

/* Keep Streamlit's sidebar collapse/reopen control reachable after the
   native header chrome is visually minimized. */
[data-testid="stHeader"] {
    display: flex !important;
    align-items: center !important;
    background: transparent !important;
    pointer-events: none !important;
    height: 2.75rem !important;
    min-height: 2.75rem !important;
}
[data-testid="stHeader"] button,
[data-testid="stHeader"] [role="button"],
[data-testid="stSidebarCollapseButton"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"] {
    display: inline-flex !important;
    visibility: visible !important;
    opacity: 1 !important;
    pointer-events: auto !important;
    min-width: 2.25rem !important;
    min-height: 2.25rem !important;
}
[data-testid="stHeader"] [data-testid="stIconMaterial"],
[data-testid="stHeader"] [data-testid="stIconMaterial"] *,
[data-testid="stHeader"] .material-symbols-rounded,
[data-testid="stHeader"] .material-symbols-outlined,
[data-testid="stHeader"] .material-icons,
[data-testid="stHeader"] span[translate="no"] {
    display: inline-flex !important;
    width: auto !important;
    min-width: 1.25rem !important;
    max-width: none !important;
    height: auto !important;
    overflow: visible !important;
    color: var(--text-primary) !important;
    font-size: 1.25rem !important;
    line-height: 1 !important;
    opacity: 1 !important;
}
[data-testid="stSidebar"][aria-expanded="false"] {
    transform: none !important;
    width: 3.25rem !important;
    min-width: 3.25rem !important;
    max-width: 3.25rem !important;
    flex-basis: 3.25rem !important;
    overflow: hidden !important;
}
[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarContent"] {
    width: 3.25rem !important;
    min-width: 3.25rem !important;
    max-width: 3.25rem !important;
    overflow: hidden !important;
}
[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarContent"] > *:not([data-testid="stSidebarHeader"]) {
    display: none !important;
}
[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarUserContent"] {
    display: none !important;
    visibility: hidden !important;
    pointer-events: none !important;
}
[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarHeader"] {
    display: flex !important;
    justify-content: center !important;
    padding: 0.5rem 0 !important;
}
[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarCollapseButton"] {
    transform: none !important;
    z-index: 1000000 !important;
    background: var(--bg-card) !important;
    border: 1px solid var(--border-strong) !important;
    border-radius: 8px !important;
    box-shadow: var(--metric-shadow) !important;
}
</style>
"""


def _normalize_theme_key(theme_key: str | None) -> str:
    theme_key = str(theme_key or _DEFAULT_THEME)
    theme_key = _THEME_ALIASES.get(theme_key, theme_key)
    return theme_key if theme_key in THEMES else _DEFAULT_THEME


def _query_param_theme() -> str | None:
    try:
        query_params = st.query_params
        raw_theme = query_params.get(_THEME_QUERY_PARAM)
    except Exception:
        try:
            query_params = st.experimental_get_query_params()
            raw_theme = query_params.get(_THEME_QUERY_PARAM)
        except Exception:
            return None
    if isinstance(raw_theme, list):
        raw_theme = raw_theme[-1] if raw_theme else None
    if not raw_theme:
        return None
    return _normalize_theme_key(str(raw_theme))


def _set_query_param_theme(theme_key: str) -> None:
    theme_key = _normalize_theme_key(theme_key)
    try:
        st.query_params[_THEME_QUERY_PARAM] = theme_key
    except Exception:
        try:
            query_params = st.experimental_get_query_params()
            query_params[_THEME_QUERY_PARAM] = theme_key
            st.experimental_set_query_params(**query_params)
        except Exception:
            pass


def _get_theme() -> str:
    query_theme = _query_param_theme()
    persistent_theme = st.session_state.get(_ACTIVE_THEME_KEY)
    existing_theme = st.session_state.get("active_theme")
    picker_theme = st.session_state.get("theme_picker_radio")
    theme_key = _normalize_theme_key(query_theme or persistent_theme or existing_theme or picker_theme or _DEFAULT_THEME)
    if st.session_state.get("_active_theme_version") != THEME_VERSION:
        st.session_state["_active_theme_version"] = THEME_VERSION
    if st.session_state.get("active_theme") != theme_key:
        st.session_state["active_theme"] = theme_key
    if st.session_state.get(_ACTIVE_THEME_KEY) != theme_key:
        st.session_state[_ACTIVE_THEME_KEY] = theme_key
    if st.session_state.get("theme_picker_radio") not in THEMES:
        st.session_state["theme_picker_radio"] = theme_key
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


def _commit_theme_picker_change() -> None:
    selected = _normalize_theme_key(st.session_state.get("theme_picker_radio"))
    st.session_state[_ACTIVE_THEME_KEY] = selected
    st.session_state["active_theme"] = selected
    _set_query_param_theme(selected)


def render_theme_picker() -> None:
    """
    Render the theme picker.
    Place this inside the sidebar Settings expander in app.py.

    Each option shows only the theme name.
    The active theme gets a highlight border.

    """
    current = _get_theme()
    options = list(THEMES.keys())
    if st.session_state.get("theme_picker_radio") != current:
        st.session_state["theme_picker_radio"] = current
    index = options.index(current) if current in options else 0
    st.selectbox(
        "Theme",
        options,
        index=index,
        format_func=lambda key: THEMES[key]["label"],
        key="theme_picker_radio",
        on_change=_commit_theme_picker_change,
    )
