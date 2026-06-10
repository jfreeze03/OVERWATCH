# theme.py - OVERWATCH theme system
# THEMES:
#   1. carbon     - Snowflake Dark: default dark shell with Snowflake blue
#   2. terminal   - Snowflake White: classic white with Snowflake blue
#   3. corporate  - Henson: muted light shell with dominant red navigation
#   4. roll_tide  - Roll Tide: Alabama crimson and white
#   5. war_eagle  - War Eagle: Auburn navy and orange
#
# Architecture: All structural styles reference CSS custom properties.
# Switching theme = injecting a new :root { } block. Zero JS required.
# Preference persists in session_state; optional DB persistence via Bookmarks.
#
# Usage in app.py:
#   from theme import inject_theme, render_theme_picker
#   inject_theme()
#   # inside sidebar Settings expander:
#   render_theme_picker()
import streamlit as st

THEME_VERSION = "2026-06-05-roll-tide-war-eagle-v3"

_DEFAULT_THEME = "carbon"
_THEME_ALIASES = {
    "aurora": "carbon",
    "black_ice": "carbon",
    "midnight": "carbon",
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
    "corporate": {
        "label":    "Henson",
        "swatch":   "#b00020",
        "bg":       "#f1f4f7",
    },
    "roll_tide": {
        "label":    "Roll Tide",
        "swatch":   "#981D32",
        "bg":       "#f7f7f6",
    },
    "war_eagle": {
        "label":    "War Eagle",
        "swatch":   "#DD550C",
        "bg":       "#0C213E",
    },
}

# CSS variable blocks - one per theme

_VARS = {

# 2. HENSON - muted light shell with dominant red navigation
"corporate": """
:root {
    --bg-app:          #f1f4f7;
    --bg-sidebar:      linear-gradient(180deg, #fff7f8 0%, #f3e8eb 100%);
    --bg-card:         #ffffff;
    --bg-card-hover:   #f7eef1;
    --bg-input:        #ffffff;
    --bg-tab-list:     #e6ebf0;
    --bg-expander:     #ffffff;

    --border-subtle:   #d6dde5;
    --border-normal:   #b7c4cf;
    --border-strong:   #b00020;
    --border-sidebar:  #d9c5cb;

    --text-primary:    #151f2c;
    --text-secondary:  #28384a;
    --text-muted:      #5a6b7d;
    --text-input:      #111827;
    --text-heading:    #b00020;

    --accent:          #b00020;
    --accent-rgb:      176, 0, 32;
    --accent2:         #0f7894;
    --accent3:         #475569;
    --h1-gradient:     linear-gradient(90deg, #b00020 0%, #b00020 44%, #3f3f46 44%, #3f3f46 100%);

    --metric-shadow:        0 1px 10px rgba(15, 23, 42, 0.08), 0 1px 2px rgba(15, 23, 42, 0.06);
    --metric-hover-shadow:  0 8px 24px rgba(176, 0, 32, 0.16), 0 2px 8px rgba(15, 23, 42, 0.10);
    --btn-bg:          linear-gradient(135deg, #ffffff, #f7eef1);
    --btn-bg-hover:    linear-gradient(135deg, #fff6f8, #f0dce2);
    --btn-border:      rgba(176, 0, 32, 0.34);
    --btn-hover-shadow: 0 2px 12px rgba(176, 0, 32, 0.18);
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

# 3. SNOWFLAKE WHITE - classic white with Snowflake brand blues
"terminal": """
:root {
    --bg-app:          #eef6fb;
    --bg-sidebar:      linear-gradient(180deg, #f1f9fd 0%, #dfeff7 100%);
    --bg-card:         #ffffff;
    --bg-card-hover:   #f0f8fc;
    --bg-input:        #ffffff;
    --bg-tab-list:     #dceff7;
    --bg-expander:     #ffffff;

    --border-subtle:   #c6dcea;
    --border-normal:   #9fc9dd;
    --border-strong:   #0068b7;
    --border-sidebar:  #b7d5e5;

    --text-primary:    #102a43;
    --text-secondary:  #1f4e6b;
    --text-muted:      #526b7a;
    --text-input:      #102a43;
    --text-heading:    #003545;

    --accent:          #0068b7;
    --accent-rgb:      0, 104, 183;
    --accent2:         #29B5E8;
    --accent3:         #71D3DC;
    --h1-gradient:     linear-gradient(90deg, #003545, #11567F, #29B5E8);

    --metric-shadow:        0 1px 10px rgba(0, 53, 69, 0.10), 0 1px 2px rgba(0, 53, 69, 0.07);
    --metric-hover-shadow:  0 8px 24px rgba(0, 104, 183, 0.18), 0 2px 8px rgba(0, 53, 69, 0.10);
    --btn-bg:          linear-gradient(135deg, #ffffff, #edf8fd);
    --btn-bg-hover:    linear-gradient(135deg, #f8fdff, #d9f1fb);
    --btn-border:      rgba(0, 104, 183, 0.38);
    --btn-hover-shadow: 0 2px 14px rgba(0, 104, 183, 0.22);
    --slider-track:    linear-gradient(90deg, #0068b7, #29B5E8);
    --tab-active-bg:   rgba(0, 104, 183, 0.14);
    --tab-active-col:  #0068b7;
    --hr-bg:           linear-gradient(90deg, transparent, #cfe6ef, transparent);
    --scrollbar-track: #eef7fb;
    --scrollbar-thumb: rgba(41, 181, 232, 0.35);
    --scrollbar-hover: rgba(17, 86, 127, 0.45);
    --font-body:       'Lato', 'Inter', 'DM Sans', 'Segoe UI', system-ui, sans-serif;
    --font-mono:       'DM Mono', 'Cascadia Mono', monospace;
    --extra-css:       '';
}
""",

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

# --- 6. ROLL TIDE - Alabama crimson and white --------------------------------
"roll_tide": """
:root {
    --bg-app:          #f7f7f6;
    --bg-sidebar:      linear-gradient(180deg, #ffffff 0%, #f2e8ea 100%);
    --bg-card:         #ffffff;
    --bg-card-hover:   #fbf3f4;
    --bg-input:        #ffffff;
    --bg-tab-list:     #ece7e6;
    --bg-expander:     #ffffff;

    --border-subtle:   #ddd6d5;
    --border-normal:   #c7b9b9;
    --border-strong:   #981D32;
    --border-sidebar:  #d8c7ca;

    --text-primary:    #1d1a1b;
    --text-secondary:  #332b2d;
    --text-muted:      #74645d;
    --text-input:      #111111;
    --text-heading:    #981D32;

    --accent:          #981D32;
    --accent-rgb:      152, 29, 50;
    --accent2:         #74645d;
    --accent3:         #c0b7b3;
    --h1-gradient:     linear-gradient(90deg, #981D32 0%, #981D32 48%, #74645d 48%, #74645d 100%);

    --metric-shadow:        0 1px 10px rgba(29, 26, 27, 0.08), 0 1px 2px rgba(29, 26, 27, 0.06);
    --metric-hover-shadow:  0 8px 24px rgba(152, 29, 50, 0.17), 0 2px 8px rgba(29, 26, 27, 0.10);
    --btn-bg:          linear-gradient(135deg, #ffffff, #fbf3f4);
    --btn-bg-hover:    linear-gradient(135deg, #ffffff, #f4dde2);
    --btn-border:      rgba(152, 29, 50, 0.36);
    --btn-hover-shadow: 0 2px 13px rgba(152, 29, 50, 0.20);
    --slider-track:    linear-gradient(90deg, #981D32, #74645d);
    --tab-active-bg:   rgba(152, 29, 50, 0.10);
    --tab-active-col:  #981D32;
    --hr-bg:           linear-gradient(90deg, transparent, #ded6d6, transparent);
    --scrollbar-track: #f5f1f1;
    --scrollbar-thumb: rgba(152, 29, 50, 0.35);
    --scrollbar-hover: rgba(116, 100, 93, 0.48);
    --font-body:       'Inter', 'DM Sans', 'Segoe UI', system-ui, sans-serif;
    --font-mono:       'DM Mono', 'Cascadia Mono', monospace;
    --extra-css:       '';
}
""",

# --- 7. WAR EAGLE - Auburn navy and orange -----------------------------------
"war_eagle": """
:root {
    --bg-app:          linear-gradient(160deg, #0C213E 0%, #132B49 52%, #3C4C60 100%);
    --bg-sidebar:      linear-gradient(180deg, #07182F 0%, #0C213E 62%, #162F4F 100%);
    --bg-card:         rgba(12, 33, 62, 0.84);
    --bg-card-hover:   rgba(19, 43, 73, 0.96);
    --bg-input:        rgba(8, 24, 47, 0.94);
    --bg-tab-list:     rgba(12, 33, 62, 0.72);
    --bg-expander:     rgba(12, 33, 62, 0.80);

    --border-subtle:   rgba(221, 85, 12, 0.16);
    --border-normal:   rgba(221, 85, 12, 0.34);
    --border-strong:   rgba(221, 85, 12, 0.72);
    --border-sidebar:  rgba(96, 106, 122, 0.24);

    --text-primary:    #f7fbff;
    --text-secondary:  #e7e9eb;
    --text-muted:      #aab5c2;
    --text-input:      #f7fbff;
    --text-heading:    transparent;

    --accent:          #DD550C;
    --accent-rgb:      221, 85, 12;
    --accent2:         #3C4C60;
    --accent3:         #e7e9eb;
    --h1-gradient:     linear-gradient(90deg, #f7fbff, #DD550C, #e7e9eb);

    --metric-shadow:        0 4px 24px rgba(0,0,0,0.48), inset 0 1px 0 rgba(221,85,12,0.08);
    --metric-hover-shadow:  0 8px 32px rgba(221,85,12,0.18), inset 0 1px 0 rgba(231,233,235,0.10);
    --btn-bg:          linear-gradient(135deg, rgba(221,85,12,0.14), rgba(60,76,96,0.20));
    --btn-bg-hover:    linear-gradient(135deg, rgba(221,85,12,0.30), rgba(60,76,96,0.32));
    --btn-border:      rgba(221, 85, 12, 0.40);
    --btn-hover-shadow: 0 0 20px rgba(221,85,12,0.24);
    --slider-track:    linear-gradient(90deg, #DD550C, #e7e9eb);
    --tab-active-bg:   rgba(221, 85, 12, 0.16);
    --tab-active-col:  #f7fbff;
    --hr-bg:           linear-gradient(90deg, transparent, rgba(221,85,12,0.36), transparent);
    --scrollbar-track: rgba(8, 24, 47, 0.76);
    --scrollbar-thumb: rgba(221, 85, 12, 0.38);
    --scrollbar-hover: rgba(231, 233, 235, 0.56);
    --font-body:       'Inter', 'DM Sans', system-ui, sans-serif;
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
    font-family: var(--font-body) !important;
}
.block-container {
    padding-top: 1rem !important;
    padding-bottom: 2rem !important;
    max-width: 1500px !important;
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
p, li { color: var(--text-primary); font-family: var(--font-body) !important; }
[data-testid="stMarkdownContainer"],
[data-testid="stMarkdownContainer"] *:not([class*="icon"]):not([class*="material"]) {
    color: inherit;
    font-family: var(--font-body);
}

/* DataFrames */
[data-testid="stDataFrame"] {
    border: 1px solid var(--border-subtle) !important;
    border-radius: 8px;
    overflow: hidden;
}

/* Buttons */
.stButton > button {
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
.stButton > button p {
    color: inherit !important;
    white-space: normal !important;
    overflow-wrap: anywhere !important;
    line-height: 1.15 !important;
    font-size: 0.82rem !important;
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
    background: transparent !important;
    border-radius: 10px;
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
[data-testid="stSidebar"] .stButton > button {
    justify-content: flex-start !important;
    min-height: 36px;
    border-radius: 7px !important;
    font-size: 0.84rem !important;
    font-weight: 760 !important;
    box-shadow: none !important;
}
[data-testid="stSidebar"] .stButton > button p {
    white-space: nowrap !important;
    overflow-wrap: normal !important;
    font-size: 0.84rem !important;
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
.ow-priority-brief-shell {
    border-top: 1px solid var(--border-subtle);
    margin: 0.85rem 0 0.25rem;
    padding-top: 0.65rem;
}
.ow-priority-brief-row {
    border-left: 3px solid var(--accent);
    border-top: 1px solid var(--border-subtle);
    margin: 0.35rem 0;
    padding: 0.48rem 0.65rem;
    background: rgba(var(--accent-rgb), 0.05);
}
.ow-priority-empty {
    align-items: center;
    border-top: 1px solid var(--border-subtle);
    color: var(--text-secondary);
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem 0.65rem;
    margin: 0.25rem 0 0.45rem;
    padding: 0.48rem 0;
    font-size: 0.78rem;
}
.ow-priority-empty strong {
    color: var(--text-primary);
    font-size: 0.72rem;
    letter-spacing: 0.05em;
    text-transform: uppercase;
}
.ow-priority-empty span:last-child {
    color: var(--text-muted);
}
.ow-priority-brief-head {
    align-items: center;
    color: var(--text-primary);
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem 0.55rem;
    font-size: 0.82rem;
    line-height: 1.3;
}
.ow-priority-rank,
.ow-priority-severity {
    border: 1px solid rgba(var(--accent-rgb), 0.28);
    border-radius: 999px;
    color: var(--text-secondary);
    font-size: 0.64rem;
    font-weight: 850;
    padding: 0.08rem 0.42rem;
    text-transform: uppercase;
}
.ow-priority-evidence,
.ow-priority-next,
.ow-priority-route {
    color: var(--text-secondary);
    font-size: 0.79rem;
    line-height: 1.35;
    margin-top: 0.2rem;
}
.ow-priority-next {
    color: var(--text-primary);
}
.ow-priority-route {
    color: var(--text-muted);
    font-size: 0.72rem;
    font-weight: 750;
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
.ow-section-notes {
    color: var(--text-secondary);
    font-size: 0.8rem;
    line-height: 1.4;
    margin: 0.1rem 0 0.85rem;
}
.ow-section-notes-title {
    color: var(--text-muted);
    font-size: 0.64rem;
    font-weight: 850;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    margin-bottom: 0.25rem;
}
.ow-section-notes ul {
    margin: 0;
    padding-left: 1rem;
}
.ow-section-notes li {
    margin: 0.2rem 0;
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
[data-testid="stMarkdownContainer"] .ow-section-notes,
[data-testid="stMarkdownContainer"] .ow-section-guide-detail,
[data-testid="stMarkdownContainer"] .ow-evidence-contract-card,
[data-testid="stMarkdownContainer"] .ow-brief-detail {
    color: var(--text-secondary) !important;
}
[data-testid="stMarkdownContainer"] .ow-section-kicker,
[data-testid="stMarkdownContainer"] .ow-filter-strip-kicker,
[data-testid="stMarkdownContainer"] .ow-scope-chip span,
[data-testid="stMarkdownContainer"] .ow-run-context,
[data-testid="stMarkdownContainer"] .ow-section-notes-title,
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
    .ow-brief-grid {
        grid-template-columns: 1fr !important;
    }
}

/* SNOWFLAKE WHITE theme extras */
.terminal-extra [data-testid="stMetric"] {
    border-top: 3px solid rgba(41,181,232,0.75) !important;
}

/* CORPORATE theme extras */
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

# Theme picker HTML
_THEME_EXTRAS = {
    "corporate": """
<style>
/* Henson: reduce glare and make navigation decisively red. */
.stButton > button {
    color: #151f2c !important;
    background: linear-gradient(135deg, #ffffff, #f7eef1) !important;
    border-color: rgba(176,0,32,0.34) !important;
}
.stButton > button:hover {
    color: #8f001a !important;
    background: linear-gradient(135deg, #fff6f8, #f0dce2) !important;
    border-color: rgba(176,0,32,0.55) !important;
}
.stButton > button[kind="primary"],
.stButton > button[kind="primary"] p {
    color: #ffffff !important;
}
.stMain [data-testid="stMarkdownContainer"],
.stMain [data-testid="stMarkdownContainer"] p {
    color: #151f2c !important;
}
.stMain [data-testid="stCaptionContainer"],
.stMain [data-testid="stCaptionContainer"] p,
.stMain [data-testid="stCaptionContainer"] span {
    color: #64748b !important;
}
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stRadio > label,
[data-testid="stSidebar"] p {
    color: #28384a !important;
}
[data-testid="stSidebar"] .stButton > button {
    color: #ffffff !important;
    background: linear-gradient(135deg, #b00020, #8f001a) !important;
    border-color: rgba(143,0,26,0.78) !important;
    box-shadow: 0 2px 9px rgba(176,0,32,0.16) !important;
}
[data-testid="stSidebar"] .stButton > button p {
    color: inherit !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    color: #ffffff !important;
    background: linear-gradient(135deg, #c91535, #9f0b25) !important;
    border-color: rgba(176,0,32,0.90) !important;
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
[data-testid="stSidebar"] .stButton > button[kind="primary"] {
    color: #ffffff !important;
    background: linear-gradient(135deg, #7f0017, #b00020) !important;
    border-color: rgba(127,0,23,0.94) !important;
    box-shadow: inset 4px 0 0 #0f7894, 0 3px 13px rgba(176,0,32,0.24) !important;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"] p {
    color: #ffffff !important;
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
[data-testid="stExpander"] summary,
[data-testid="stExpander"] summary > div,
[data-testid="stExpander"] summary p,
[data-testid="stExpander"] summary span {
    color: #151f2c !important;
}
[data-testid="stExpander"] summary {
    background: #ffffff !important;
    border-radius: 7px !important;
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary {
    color: #ffffff !important;
    background: linear-gradient(135deg, #b00020, #8f001a) !important;
    border: 1px solid rgba(143,0,26,0.78) !important;
    border-bottom: 1px solid rgba(143,0,26,0.78) !important;
    box-shadow: 0 2px 9px rgba(176,0,32,0.16) !important;
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary,
[data-testid="stSidebar"] [data-testid="stExpander"] summary > span,
[data-testid="stSidebar"] [data-testid="stExpander"] summary > span > div,
[data-testid="stSidebar"] [data-testid="stExpander"] summary p,
[data-testid="stSidebar"] [data-testid="stExpander"] summary span {
    color: #ffffff !important;
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover {
    background: linear-gradient(135deg, #c91535, #9f0b25) !important;
    border-color: rgba(176,0,32,0.90) !important;
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
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover,
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover > span,
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover p,
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover span {
    color: #ffffff !important;
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
    background: #e6ebf0 !important;
    border-bottom: 2px solid rgba(176,0,32,0.65);
}
.stTabs [data-baseweb="tab"] {
    color: #4d5559 !important;
    font-weight: 650;
}
.stTabs [aria-selected="true"] {
    color: #ffffff !important;
    background: linear-gradient(135deg, #b00020, #8f001a) !important;
    border-color: rgba(143,0,26,0.72) !important;
}
</style>
""",
    "terminal": """
<style>
/* Snowflake White: reduce glare and make navigation decisively blue. */
.stButton > button {
    color: #102a43 !important;
    background: linear-gradient(135deg, #ffffff, #edf8fd) !important;
    border-color: rgba(0,104,183,0.38) !important;
}
.stButton > button:hover {
    color: #004f8f !important;
    background: linear-gradient(135deg, #f8fdff, #d9f1fb) !important;
    border-color: rgba(0,104,183,0.58) !important;
}
.stButton > button[kind="primary"],
.stButton > button[kind="primary"] p {
    color: #ffffff !important;
}
.stMain [data-testid="stMarkdownContainer"],
.stMain [data-testid="stMarkdownContainer"] p {
    color: #102a43 !important;
}
.stMain [data-testid="stCaptionContainer"],
.stMain [data-testid="stCaptionContainer"] p,
.stMain [data-testid="stCaptionContainer"] span {
    color: #526b7a !important;
}
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stRadio > label,
[data-testid="stSidebar"] p {
    color: #1f4e6b !important;
}
[data-testid="stSidebar"] .stButton > button {
    color: #ffffff !important;
    background: linear-gradient(135deg, #0068b7, #00528f) !important;
    border-color: rgba(0,82,143,0.78) !important;
    box-shadow: 0 2px 9px rgba(0,104,183,0.16) !important;
}
[data-testid="stSidebar"] .stButton > button p {
    color: inherit !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    color: #ffffff !important;
    background: linear-gradient(135deg, #0079d6, #005fa8) !important;
    border-color: rgba(0,104,183,0.90) !important;
}
[data-testid="stSidebar"] .stRadio > div > label:hover {
    color: #0068b7 !important;
    background: rgba(0,104,183,0.08);
}
[data-testid="stSidebar"] .stRadio > div > label[data-checked="true"] {
    color: #0068b7 !important;
    background: rgba(0,104,183,0.13);
    border-left: 3px solid #0068b7;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"] {
    color: #ffffff !important;
    background: linear-gradient(135deg, #003f73, #0068b7) !important;
    border-color: rgba(0,63,115,0.94) !important;
    box-shadow: inset 4px 0 0 #71D3DC, 0 3px 13px rgba(0,104,183,0.24) !important;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"] p {
    color: #ffffff !important;
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] .ow-live-pill {
    color: #0068b7 !important;
}
[data-testid="stMetric"] {
    border-top: 3px solid rgba(0,104,183,0.75) !important;
}
[data-testid="stMetricValue"] { color: #102a43 !important; }
[data-testid="stMetricLabel"] { color: #526b7a !important; }
[data-testid="stExpander"] {
    background: #ffffff !important;
    border-color: #b7d5e5 !important;
}
[data-testid="stExpander"] summary,
[data-testid="stExpander"] summary > div,
[data-testid="stExpander"] summary p,
[data-testid="stExpander"] summary span,
[data-testid="stExpander"] details,
[data-testid="stExpander"] [data-testid="stMarkdownContainer"],
[data-testid="stExpander"] [data-testid="stMarkdownContainer"] p {
    color: #102a43 !important;
}
[data-testid="stExpander"] summary {
    background: #ffffff !important;
    border-radius: 7px !important;
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary {
    color: #ffffff !important;
    background: linear-gradient(135deg, #0068b7, #00528f) !important;
    border: 1px solid rgba(0,82,143,0.78) !important;
    border-bottom: 1px solid rgba(0,82,143,0.78) !important;
    box-shadow: 0 2px 9px rgba(0,104,183,0.16) !important;
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary,
[data-testid="stSidebar"] [data-testid="stExpander"] summary > span,
[data-testid="stSidebar"] [data-testid="stExpander"] summary > span > div,
[data-testid="stSidebar"] [data-testid="stExpander"] summary p,
[data-testid="stSidebar"] [data-testid="stExpander"] summary span {
    color: #ffffff !important;
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover {
    background: linear-gradient(135deg, #0079d6, #005fa8) !important;
    border-color: rgba(0,104,183,0.90) !important;
}
[data-testid="stExpander"] summary:hover,
[data-testid="stExpander"] summary:hover p,
[data-testid="stExpander"] summary:hover span {
    color: #0068b7 !important;
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover,
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover > span,
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover p,
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover span {
    color: #ffffff !important;
}
.stTabs [data-baseweb="tab-list"] {
    background: #dceff7 !important;
    border-bottom: 2px solid rgba(0,104,183,0.55);
}
.stTabs [data-baseweb="tab"] {
    color: #102a43 !important;
    font-weight: 650;
}
.stTabs [aria-selected="true"] {
    color: #ffffff !important;
    background: linear-gradient(135deg, #0068b7, #00528f) !important;
    border-color: rgba(0,82,143,0.72) !important;
}
</style>
""",
    "carbon": """
<style>
/* Snowflake Dark: make Snowflake blue the dominant navigation treatment. */
[data-testid="stSidebar"] .stButton > button {
    color: #ffffff !important;
    background: linear-gradient(135deg, #0068b7, #003545) !important;
    border-color: rgba(41,181,232,0.70) !important;
    box-shadow: 0 2px 10px rgba(41,181,232,0.18) !important;
}
[data-testid="stSidebar"] .stButton > button p {
    color: inherit !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    color: #ffffff !important;
    background: linear-gradient(135deg, #29B5E8, #0068b7) !important;
    border-color: rgba(113,211,220,0.95) !important;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"] {
    color: #ffffff !important;
    background: linear-gradient(135deg, #003f73, #0068b7) !important;
    border-color: rgba(113,211,220,0.96) !important;
    box-shadow: inset 4px 0 0 #71D3DC, 0 3px 14px rgba(41,181,232,0.30) !important;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"] p {
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
    "roll_tide": """
<style>
/* Roll Tide: Alabama crimson navigation over a white shell. */
.stButton > button {
    color: #1d1a1b !important;
    background: linear-gradient(135deg, #ffffff, #fbf3f4) !important;
    border-color: rgba(152,29,50,0.36) !important;
}
.stButton > button:hover {
    color: #7f1829 !important;
    background: linear-gradient(135deg, #ffffff, #f4dde2) !important;
    border-color: rgba(152,29,50,0.58) !important;
}
.stButton > button[kind="primary"],
.stButton > button[kind="primary"] p {
    color: #ffffff !important;
}
.stMain [data-testid="stMarkdownContainer"],
.stMain [data-testid="stMarkdownContainer"] p {
    color: #1d1a1b !important;
}
.stMain [data-testid="stCaptionContainer"],
.stMain [data-testid="stCaptionContainer"] p,
.stMain [data-testid="stCaptionContainer"] span {
    color: #74645d !important;
}
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stRadio > label,
[data-testid="stSidebar"] p {
    color: #332b2d !important;
}
[data-testid="stSidebar"] .stButton > button {
    color: #ffffff !important;
    background: linear-gradient(135deg, #981D32, #6f1626) !important;
    border-color: rgba(111,22,38,0.78) !important;
    box-shadow: 0 2px 9px rgba(152,29,50,0.18) !important;
}
[data-testid="stSidebar"] .stButton > button p {
    color: inherit !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    color: #ffffff !important;
    background: linear-gradient(135deg, #b41f3b, #841b2f) !important;
    border-color: rgba(152,29,50,0.92) !important;
}
[data-testid="stSidebar"] .stRadio > div > label:hover {
    color: #981D32 !important;
    background: rgba(152,29,50,0.07);
}
[data-testid="stSidebar"] .stRadio > div > label[data-checked="true"] {
    color: #981D32 !important;
    background: rgba(152,29,50,0.11);
    border-left: 3px solid #981D32;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"] {
    color: #ffffff !important;
    background: linear-gradient(135deg, #6f1626, #981D32) !important;
    border-color: rgba(111,22,38,0.94) !important;
    box-shadow: inset 4px 0 0 #c0b7b3, 0 3px 13px rgba(152,29,50,0.25) !important;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"] p {
    color: #ffffff !important;
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] .ow-live-pill {
    color: #981D32 !important;
}
[data-testid="stMetric"] {
    border-top: 3px solid rgba(152,29,50,0.75) !important;
}
[data-testid="stMetricValue"] { color: #1d1a1b !important; }
[data-testid="stMetricLabel"] { color: #74645d !important; }
[data-testid="stExpander"] {
    background: #ffffff !important;
    border-color: #ddd6d5 !important;
}
[data-testid="stExpander"] summary,
[data-testid="stExpander"] summary > div,
[data-testid="stExpander"] summary p,
[data-testid="stExpander"] summary span {
    color: #1d1a1b !important;
}
[data-testid="stExpander"] summary {
    background: #ffffff !important;
    border-radius: 7px !important;
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary {
    color: #ffffff !important;
    background: linear-gradient(135deg, #981D32, #6f1626) !important;
    border: 1px solid rgba(111,22,38,0.78) !important;
    border-bottom: 1px solid rgba(111,22,38,0.78) !important;
    box-shadow: 0 2px 9px rgba(152,29,50,0.18) !important;
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary,
[data-testid="stSidebar"] [data-testid="stExpander"] summary > span,
[data-testid="stSidebar"] [data-testid="stExpander"] summary > span > div,
[data-testid="stSidebar"] [data-testid="stExpander"] summary p,
[data-testid="stSidebar"] [data-testid="stExpander"] summary span {
    color: #ffffff !important;
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover {
    background: linear-gradient(135deg, #b41f3b, #841b2f) !important;
    border-color: rgba(152,29,50,0.92) !important;
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
    color: #981D32 !important;
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover,
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover > span,
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover p,
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover span {
    color: #ffffff !important;
}
[data-testid="stWidgetLabel"],
[data-testid="stWidgetLabel"] p,
.stTextInput label,
.stTextInput label p {
    color: #1f2937 !important;
}
.stTextInput input::placeholder,
.stTextArea textarea::placeholder {
    color: #74645d !important;
    opacity: 1 !important;
}
.stTabs [data-baseweb="tab-list"] {
    background: #ece7e6 !important;
    border-bottom: 2px solid rgba(152,29,50,0.65);
}
.stTabs [data-baseweb="tab"] {
    color: #4c4140 !important;
    font-weight: 650;
}
.stTabs [aria-selected="true"] {
    color: #ffffff !important;
    background: linear-gradient(135deg, #981D32, #6f1626) !important;
    border-color: rgba(111,22,38,0.72) !important;
}
</style>
""",
    "war_eagle": """
<style>
/* War Eagle: Auburn navy shell with orange action color. */
[data-testid="stSidebar"] .stButton > button {
    color: #ffffff !important;
    background: linear-gradient(135deg, #DD550C, #0C213E) !important;
    border-color: rgba(221,85,12,0.72) !important;
    box-shadow: 0 2px 10px rgba(221,85,12,0.20) !important;
}
[data-testid="stSidebar"] .stButton > button p {
    color: inherit !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    color: #ffffff !important;
    background: linear-gradient(135deg, #f06a16, #132B49) !important;
    border-color: rgba(221,85,12,0.96) !important;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"] {
    color: #ffffff !important;
    background: linear-gradient(135deg, #0C213E, #DD550C) !important;
    border-color: rgba(221,85,12,0.96) !important;
    box-shadow: inset 4px 0 0 #e7e9eb, 0 3px 14px rgba(221,85,12,0.32) !important;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"] p {
    color: #ffffff !important;
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary {
    color: #ffffff !important;
    background: linear-gradient(135deg, #DD550C, #0C213E) !important;
    border: 1px solid rgba(221,85,12,0.72) !important;
    border-bottom: 1px solid rgba(221,85,12,0.72) !important;
    box-shadow: 0 2px 10px rgba(221,85,12,0.20) !important;
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary,
[data-testid="stSidebar"] [data-testid="stExpander"] summary > span,
[data-testid="stSidebar"] [data-testid="stExpander"] summary > span > div,
[data-testid="stSidebar"] [data-testid="stExpander"] summary p,
[data-testid="stSidebar"] [data-testid="stExpander"] summary span {
    color: #ffffff !important;
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover {
    background: linear-gradient(135deg, #f06a16, #132B49) !important;
    border-color: rgba(221,85,12,0.96) !important;
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] .ow-live-pill {
    color: #f6a15c !important;
}
[data-testid="stMetric"] {
    border-top: 3px solid rgba(221,85,12,0.78) !important;
}
.stTabs [data-baseweb="tab-list"] {
    background: rgba(12,33,62,0.84) !important;
    border-bottom: 2px solid rgba(221,85,12,0.58);
}
.stTabs [data-baseweb="tab"] {
    color: #e7e9eb !important;
    font-weight: 700;
}
.stTabs [aria-selected="true"] {
    color: #ffffff !important;
    background: linear-gradient(135deg, #DD550C, #0C213E) !important;
    border-color: rgba(221,85,12,0.74) !important;
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
    Render the theme picker.
    Place this inside the sidebar Settings expander in app.py.

    Each option shows only the theme name.
    The active theme gets a highlight border.

    Args:
        persist: Write preference to OVERWATCH_BOOKMARKS for cross-session persistence.
    """
    current = _get_theme()
    options = list(THEMES.keys())
    if st.session_state.get("theme_picker_radio") not in options:
        st.session_state["theme_picker_radio"] = current
    index = options.index(current) if current in options else 0
    selected = st.selectbox(
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
