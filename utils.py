import os
import sys
import json
import html
import urllib.parse

# --- 1. Base Directory Handling ---
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# --- 2. Persistence Helpers ---
def get_data_path(filename: str) -> str:
    return os.path.join(DATA_DIR, filename)

def read_json(filepath: str, default=None):
    if default is None:
        default = {}
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default

def write_json(filepath: str, data) -> None:
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except OSError as e:
        print(f"[Error] Writing {filepath}: {e}")

# --- 3. HTTP & Template Helpers ---
def json_response(data: dict or list, status: int = 200):
    return json.dumps(data), ("Content-Type", "application/json")

def html_response(html_str: str, status: int = 200):
    return html_str, ("Content-Type", "text/html")

def escape(val) -> str:
    return html.escape(str(val))

def quote(val) -> str:
    return urllib.parse.quote_plus(str(val))

def get_param(params: dict, key: str, default: str = "") -> str:
    if not isinstance(params, dict):
        return default
    val = params.get(key, [default])
    return val[0] if isinstance(val, list) and val else default

def render_page(title: str, body_content: str, scripts: list = None) -> str:
    """Standard dashboard layout shell with Tailwind."""
    scripts_html = "\n".join([f"<script>{s}</script>" for s in (scripts or [])])
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{escape(title)}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body {{ background: #0b0f19; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
        input[type=number]::-webkit-inner-spin-button, 
        input[type=number]::-webkit-outer-spin-button {{ -webkit-appearance: none; margin: 0; }}
    </style>
    {scripts_html}
</head>
<body class="p-6 max-w-7xl mx-auto space-y-8 pb-24">
    {body_content}
</body>
</html>"""

def render_theme_picker(base_route: str, title: str = "Select Overlay Theme", accent_color: str = "emerald") -> str:
    """Step 1: Renders the categorized color palette selection grid."""
    accent_text = f"text-{accent_color}-400"
    grouped_tiles = {}
    for key, cfg in OVERLAY_THEMES.items():
        cat = cfg.get("category", "Other")
        grouped_tiles.setdefault(cat, []).append(f"""
        <a href="{base_route}?theme={key}" 
           class="flex items-center gap-3 p-3 bg-slate-900 border border-slate-800 hover:border-slate-600 rounded-xl transition group">
            <span class="w-6 h-6 rounded-lg shrink-0 border" style="background: {cfg['bg']}; border-color: {cfg['border']};"></span>
            <div class="flex-1 min-w-0">
                <div class="font-bold text-xs text-slate-200 group-hover:text-white truncate">{cfg['label']}</div>
            </div>
            <span class="text-slate-600 group-hover:text-slate-400 text-xs">→</span>
        </a>
        """)

    categories_html = []
    for cat, tiles in grouped_tiles.items():
        categories_html.append(f"""
        <div class="space-y-2">
            <h2 class="text-xs font-bold uppercase tracking-wider text-slate-400">{cat}</h2>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {''.join(tiles)}
            </div>
        </div>
        """)

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{escape(title)}</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-[#0b0f19] text-slate-200 p-6 min-h-screen flex flex-col justify-center items-center">
    <div class="w-full max-w-2xl bg-slate-950/80 border border-slate-800 p-5 rounded-2xl shadow-xl space-y-5">
        <div class="border-b border-slate-800 pb-3">
            <span class="text-[10px] uppercase font-bold tracking-widest {accent_text}">Step 1 of 2</span>
            <h1 class="text-base font-black text-white">{escape(title)}</h1>
        </div>
        <div class="space-y-4 max-h-[75vh] overflow-y-auto pr-1">
            {''.join(categories_html)}
        </div>
    </div>
</body>
</html>"""


def render_item_picker(base_route: str, theme_key: str, items: dict, item_type_label: str = "Item") -> str:
    """Step 2: Renders selectable items (counters, timers, texts) under the chosen theme."""
    theme = OVERLAY_THEMES.get(theme_key, {})
    links = []

    for name, display_val in sorted(items.items()):
        qname = quote(name)
        links.append(f"""
        <a href="{base_route}?theme={theme_key}&name={qname}" 
           class="flex items-center justify-between p-3.5 bg-slate-900/90 hover:bg-slate-800 border border-slate-800 hover:border-indigo-500 rounded-xl transition text-decoration-none group">
            <span class="font-bold text-slate-200 text-sm group-hover:text-white truncate">{escape(name)}</span>
            <span class="font-mono text-xs text-slate-400 bg-slate-950 px-2.5 py-1 rounded border border-slate-800 font-bold shrink-0">{escape(display_val)}</span>
        </a>
        """)

    items_html = "".join(links) if links else f'<div class="text-slate-500 text-xs italic p-4 text-center">No {item_type_label.lower()}s available.</div>'

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Select {escape(item_type_label)}</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-[#0b0f19] text-slate-200 p-6 min-h-screen flex flex-col justify-center items-center">
    <div class="w-full max-w-xl bg-slate-950/80 border border-slate-800 p-5 rounded-2xl shadow-xl space-y-4">
        <div class="flex items-center justify-between border-b border-slate-800 pb-3">
            <div>
                <span class="text-[10px] uppercase font-bold tracking-widest text-indigo-400">Step 2 of 2</span>
                <h1 class="text-base font-black text-white">Select {escape(item_type_label)}</h1>
            </div>
            <a href="{base_route}" class="text-xs text-slate-400 hover:text-slate-200">← Change Theme</a>
        </div>
        <p class="text-xs text-slate-400">Theme: <strong class="text-white">{theme.get('label', theme_key)}</strong></p>
        <div class="space-y-2 max-h-[60rem] overflow-y-auto pr-1">
            {items_html}
        </div>
    </div>
</body>
</html>"""

def render_obs_overlay(
    title: str,
    theme_key: str,
    inner_html: str,
    custom_css: str = "",
    poll_endpoint: str = "",
    poll_interval_ms: int = 500,
    poll_js: str = "",
) -> str:
    """Standardized full-bleed OBS browser source wrapper."""
    theme = OVERLAY_THEMES.get(theme_key, OVERLAY_THEMES["slate_grey"])
    box_shadow = (
        "none" if theme["glow"] == "none" else f"0 4px 24px {theme['glow']}"
    )
    text_shadow = (
        "none" if theme["glow"] == "none" else f"0 0 12px {theme['glow']}"
    )

    # Optional default polling JS block
    script_block = ""
    if poll_endpoint and poll_js:
        script_block = f"""
        <script>
            async function updateOverlay() {{
                try {{
                    const res = await fetch('{poll_endpoint}');
                    if (!res.ok) return;
                    const data = await res.json();
                    {poll_js}
                }} catch (e) {{}}
            }}
            setInterval(updateOverlay, {poll_interval_ms});
            updateOverlay();
        </script>
        """

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{escape(title)}</title>
    <style>
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        html, body {{
            width: 100vw;
            height: 100vh;
            overflow: hidden;
            background: transparent;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }}
        .obs-root {{
            width: 100%;
            height: 100%;
            background: {theme['bg']};
            border: 2px solid {theme['border']};
            border-radius: 14px;
            box-shadow: {box_shadow};
            backdrop-filter: blur(12px);
            color: {theme['text_count']};
            display: flex;
            align-items: center;
        }}
        .obs-label {{
            color: {theme['text_label']};
            text-shadow: 0 1px 3px rgba(0,0,0,0.8);
            text-transform: uppercase;
            font-weight: 800;
        }}
        .obs-val {{
            color: {theme['text_count']};
            text-shadow: {text_shadow};
            font-family: monospace;
            font-weight: 900;
        }}
        {custom_css}
    </style>
    {script_block}
</head>
<body>
    <div class="obs-root" id="obs-container">
        {inner_html}
    </div>
</body>
</html>"""


# --- 4. Centralized OBS Overlay Theme Palette ---
OVERLAY_THEMES = {
    # ROYGBIV Spectral Themes
    "ruby_red": {
        "label": "Ruby Red",
        "category": "Rainbow",
        "bg": "rgba(30, 7, 7, 0.90)",
        "border": "#ef4444",
        "glow": "rgba(239, 68, 68, 0.45)",
        "text_label": "#fca5a5",
        "text_count": "#ffffff",
    },
    "ember_orange": {
        "label": "Ember Orange",
        "category": "Rainbow",
        "bg": "rgba(36, 16, 5, 0.90)",
        "border": "#f97316",
        "glow": "rgba(249, 115, 22, 0.45)",
        "text_label": "#fdba74",
        "text_count": "#ffffff",
    },
    "solar_yellow": {
        "label": "Solar Yellow",
        "category": "Rainbow",
        "bg": "rgba(33, 26, 4, 0.90)",
        "border": "#eab308",
        "glow": "rgba(234, 179, 8, 0.45)",
        "text_label": "#fde047",
        "text_count": "#ffffff",
    },
    "emerald_green": {
        "label": "Emerald Green",
        "category": "Rainbow",
        "bg": "rgba(5, 30, 20, 0.90)",
        "border": "#10b981",
        "glow": "rgba(16, 185, 129, 0.45)",
        "text_label": "#6ee7b7",
        "text_count": "#ffffff",
    },
    "cyan_blue": {
        "label": "Cobalt Blue",
        "category": "Rainbow",
        "bg": "rgba(8, 20, 44, 0.90)",
        "border": "#3b82f6",
        "glow": "rgba(59, 130, 246, 0.45)",
        "text_label": "#93c5fd",
        "text_count": "#ffffff",
    },
    "deep_indigo": {
        "label": "Deep Indigo",
        "category": "Rainbow",
        "bg": "rgba(15, 15, 42, 0.90)",
        "border": "#6366f1",
        "glow": "rgba(99, 102, 241, 0.45)",
        "text_label": "#a5b4fc",
        "text_count": "#ffffff",
    },
    "amethyst_violet": {
        "label": "Amethyst Violet",
        "category": "Rainbow",
        "bg": "rgba(24, 10, 42, 0.90)",
        "border": "#8b5cf6",
        "glow": "rgba(139, 92, 246, 0.45)",
        "text_label": "#c4b5fd",
        "text_count": "#ffffff",
    },

    # Accents & Neutrals
    "neon_magenta": {
        "label": "Neon Magenta",
        "category": "Accent",
        "bg": "rgba(36, 6, 32, 0.90)",
        "border": "#d946ef",
        "glow": "rgba(217, 70, 239, 0.50)",
        "text_label": "#f0abfc",
        "text_count": "#ffffff",
    },
    "slate_grey": {
        "label": "Slate Grey",
        "category": "Neutral",
        "bg": "rgba(15, 23, 42, 0.92)",
        "border": "#64748b",
        "glow": "rgba(100, 116, 139, 0.35)",
        "text_label": "#cbd5e1",
        "text_count": "#f8fafc",
    },
    "onyx_black": {
        "label": "Onyx Black",
        "category": "Neutral",
        "bg": "rgba(5, 5, 5, 0.95)",
        "border": "#27272a",
        "glow": "rgba(255, 255, 255, 0.10)",
        "text_label": "#a1a1aa",
        "text_count": "#ffffff",
    },
    "frosted_white": {
        "label": "Frosted White",
        "category": "Neutral",
        "bg": "rgba(248, 250, 252, 0.92)",
        "border": "#cbd5e1",
        "glow": "rgba(255, 255, 255, 0.40)",
        "text_label": "#475569",
        "text_count": "#090d16",
    },

    # High Contrast (Accessibility / Extreme Legibility)
    "hc_yellow_black": {
        "label": "High Contrast: Yellow on Black",
        "category": "High Contrast",
        "bg": "#000000",
        "border": "#ffff00",
        "glow": "none",
        "text_label": "#ffffff",
        "text_count": "#ffff00",
    },
    "hc_cyan_black": {
        "label": "High Contrast: Cyan on Black",
        "category": "High Contrast",
        "bg": "#000000",
        "border": "#00ffff",
        "glow": "none",
        "text_label": "#ffffff",
        "text_count": "#00ffff",
    },
    "hc_black_yellow": {
        "label": "High Contrast: Black on Amber",
        "category": "High Contrast",
        "bg": "#facc15",
        "border": "#000000",
        "glow": "none",
        "text_label": "#000000",
        "text_count": "#000000",
    },
    "hc_pure_white": {
        "label": "High Contrast: Monochrome Stark",
        "category": "High Contrast",
        "bg": "#000000",
        "border": "#ffffff",
        "glow": "none",
        "text_label": "#ffffff",
        "text_count": "#ffffff",
    },
}