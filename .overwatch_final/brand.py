"""OVERWATCH brand mark and lockup helpers."""

from __future__ import annotations

import html


OVERWATCH_BRAND_NAME = "OVERWATCH"
OVERWATCH_BRAND_TAGLINE = "SNOWFLAKE MONITOR"


def render_overwatch_logo_svg(size: int = 32, title: str = OVERWATCH_BRAND_NAME) -> str:
    """Return the Sentinel Prism SVG mark.

    The mark is intentionally abstract: an angular aperture/O, one diagonal
    prism cut, and a quiet inner diamond. It avoids literal eyes, shields,
    crosshairs, plus signs, or snowflake clones.
    """
    safe_title = html.escape(str(title or OVERWATCH_BRAND_NAME), quote=True)
    safe_size = max(16, min(int(size or 32), 96))
    return f"""
<svg class="ow-logo-mark" width="{safe_size}" height="{safe_size}" viewBox="0 0 48 48"
     role="img" aria-label="{safe_title}" focusable="false" xmlns="http://www.w3.org/2000/svg">
    <title>{safe_title}</title>
    <path class="ow-logo-prism" fill="currentColor" fill-rule="evenodd"
          d="M24 4.8 39.8 13.9 39.8 32.1 24 43.2 8.2 32.1 8.2 13.9 24 4.8ZM24 10.8 13.8 17.1 13.8 29.2 24 36.9 34.2 29.2 34.2 17.1 24 10.8Z"/>
    <path class="ow-logo-cut" fill="currentColor"
          d="M17.1 31.3 31.9 13.4H37L22.2 31.3H17.1Z"/>
    <path class="ow-logo-core" fill="currentColor"
          d="M24 18.6 29.6 24 24 29.4 18.4 24 24 18.6Z"/>
</svg>
""".strip()


def render_sidebar_brand() -> str:
    """Return sidebar brand HTML for Streamlit markdown rendering."""
    return f"""
<div class="ow-sidebar-brand">
    <div class="ow-brand-lockup">
        <span class="ow-sidebar-logo">
            {render_overwatch_logo_svg(42, OVERWATCH_BRAND_NAME)}
        </span>
        <span class="ow-brand-copy">
            <strong>{OVERWATCH_BRAND_NAME}</strong>
            <small>{OVERWATCH_BRAND_TAGLINE}</small>
        </span>
    </div>
</div>
""".strip()


__all__ = [
    "OVERWATCH_BRAND_NAME",
    "OVERWATCH_BRAND_TAGLINE",
    "render_overwatch_logo_svg",
    "render_sidebar_brand",
]
