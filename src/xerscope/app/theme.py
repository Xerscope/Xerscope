"""The app's look: its style sheet, with the chart and status colours as CSS variables."""

from __future__ import annotations

import base64
import functools
from pathlib import Path

import streamlit as st

from xerscope.viz.charts import ACCENT, SERIES, STATUS

STYLE = Path(__file__).parent / "style.css"
STATIC = Path(__file__).parent / "static"
# The theme's fonts (.streamlit/config.toml, [[theme.fontFaces]]): family -> file in app/static/.
FONT_FILES = {"Onest": "Onest-latin-wght.woff2", "JetBrains Mono": "JetBrainsMono-latin-wght.woff2"}


def theme_loaded() -> bool:
    """Say whether Streamlit read the app's .streamlit/config.toml.

    ``xerscope app`` runs from that folder, and Streamlit 1.66 also reads it next to the script. An older
    Streamlit started from another folder reads none: the page then shows Streamlit's defaults (its own
    fonts and colours, no static folder, every interface listened on).
    """
    return st.get_option("theme.font") is not None and bool(st.get_option("server.enableStaticServing"))


@functools.cache
def font_fallback_css() -> str:
    """Return @font-face rules with the two fonts inlined, for a run without the config.

    The fonts are data: URLs (~100 KB): the static folder is not served then, so the theme's font URLs
    would 404.
    """
    rules = []
    for family, name in FONT_FILES.items():
        data = base64.b64encode((STATIC / name).read_bytes()).decode("ascii")
        rules.append(
            f'@font-face {{ font-family: "{family}"; font-weight: 100 900; font-display: swap; '
            f"src: url(data:font/woff2;base64,{data}) format('woff2'); }}"
        )
    rules.append('.stApp { font-family: "Onest", sans-serif; }')
    rules.append('.stApp code, .stApp pre { font-family: "JetBrains Mono", monospace; }')
    return "\n".join(rules)


def apply_style() -> None:
    """Send style.css with the app's colours, once per run; it takes no space.

    The series colours and the status colours hold on both themes, the accent is a CSS light-dark() pair
    resolved by the color-scheme Streamlit sets on the app, and the rest follows the page's text colour, so
    a theme switch needs no rerun. Without the config (``theme_loaded``), the fonts are inlined so the page
    at least reads in the app's faces.
    """
    accent = f"light-dark({ACCENT['light']}, {ACCENT['dark']})"
    series = {f"s{index}": colour for index, colour in enumerate(SERIES, start=1)}
    status = {f"status-{name}": colour for name, colour in STATUS.items()}
    colours = {"accent": accent} | series | status
    variables = "".join(f"--{name}: {value};" for name, value in colours.items())
    fallback = "" if theme_loaded() else font_fallback_css()
    st.html(f"<style>:root {{{variables}}}\n{fallback}\n{STYLE.read_text(encoding='utf-8')}</style>")
