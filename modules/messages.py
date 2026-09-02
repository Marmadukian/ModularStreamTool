from utils import (
    get_data_path, read_json, write_json,
    escape, quote, get_param, json_response, html_response,
    OVERLAY_THEMES, render_theme_picker, render_item_picker
)

MODULE_ID = "messages"
MODULE_NAME = "Static Text & Announcements"

MESSAGES_FILE = get_data_path("messages_store.json")

TEXT_LAYOUTS = {
    "single": {
        "label": "Single Line Badge",
        "desc": "Fixed 56px height, single-line display centered vertically.",
        "container_css": "display: flex; align-items: center; justify-content: center;",
        "badge_css": """
            height: 56px;
            display: inline-flex;
            align-items: center;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            padding: 0 20px;
        """,
        "inner_html": """
            <span class="text-label">{label}:</span>
            <span class="text-content" id="display-val">{content}</span>
        """
    },
    "multiline": {
        "label": "Multiline Window (OBS Sized)",
        "desc": "Fills the entire OBS Browser Source width & height with structured header and body.",
        "container_css": "display: block; padding: 0;",
        "badge_css": """
            width: 100vw;
            height: 100vh;
            display: flex;
            flex-direction: column;
            border-radius: 16px;
            padding: 20px 24px;
            overflow: hidden;
        """,
        "inner_html": """
            <div class="text-label pb-2 mb-3 border-b border-white/10 shrink-0">{label}</div>
            <div class="text-content overflow-y-auto pr-1 flex-1" id="display-val">{content}</div>
        """
    },
}

SHARED_JS = [
    """
    function promptRenameMessage(oldLabel) {
        const newLabel = prompt(`Rename message label "${oldLabel}" to:`, oldLabel);
        if (newLabel && newLabel.trim() && newLabel.trim() !== oldLabel) {
            window.location.search = `?action=msg_rename&label=${encodeURIComponent(oldLabel)}&new_label=${encodeURIComponent(newLabel.trim())}`;
        }
    }
    """
]

# --- Persistence ---

def load_messages() -> dict:
    return read_json(MESSAGES_FILE, {})

def save_messages(data: dict) -> None:
    write_json(MESSAGES_FILE, data)

# --- Action Dispatcher ---

def handle_common_commands(params):
    action = get_param(params, "action")
    if not action or not action.startswith("msg_"):
        return

    messages = load_messages()
    label = get_param(params, "label").strip()

    if action == "msg_save" and label:
        content = get_param(params, "content")
        messages[label] = content
        save_messages(messages)

    elif action == "msg_delete" and label in messages:
        del messages[label]
        save_messages(messages)

    elif action == "msg_rename" and label in messages:
        new_label = get_param(params, "new_label").strip()
        if new_label and new_label != label:
            messages[new_label] = messages.pop(label)
            save_messages(messages)

# --- Widgets ---

def render_dashboard_widget(params):
    messages = load_messages()
    cards = []

    for label, content in sorted(messages.items()):
        qlabel = quote(label)
        cards.append(f"""
        <div class="bg-slate-900/90 border border-slate-800 rounded-xl p-4 shadow-sm space-y-3">
            <div class="flex items-center justify-between border-b border-slate-800/80 pb-2">
                <div class="flex items-center gap-2 min-w-0">
                    <span class="font-bold text-sm text-indigo-300 uppercase tracking-wider truncate">{escape(label)}</span>
                    <button type="button" onclick="promptRenameMessage('{escape(label)}')" class="text-slate-500 hover:text-indigo-400 text-xs p-1" title="Rename label">✏️</button>
                </div>
                <div class="flex items-center gap-3">
                    <a href="/obs/text_display?theme=deep_indigo&name={qlabel}&layout=single" target="_blank" class="text-[11px] text-indigo-400 hover:underline">OBS ↗</a>
                    <a href="/?action=msg_delete&label={qlabel}" onclick="return confirm('Delete message: {escape(label)}?');" class="text-slate-600 hover:text-rose-400 text-xs font-mono">✕</a>
                </div>
            </div>
            <form action="" method="GET" class="space-y-2">
                <input type="hidden" name="action" value="msg_save" />
                <input type="hidden" name="label" value="{escape(label)}" />
                <textarea name="content" rows="2" class="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500 font-sans">{escape(content)}</textarea>
                <div class="flex justify-end">
                    <button type="submit" class="bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-xs px-3 py-1.5 rounded-lg transition">Update Message</button>
                </div>
            </form>
        </div>
        """)

    cards_html = "".join(cards) if cards else '<div class="text-slate-500 text-xs italic py-4 text-center">No static messages active.</div>'

    return f"""
    <div class="bg-slate-950/60 border border-slate-800 rounded-2xl p-5 space-y-4">
        <div class="flex items-center justify-between border-b border-slate-800 pb-3">
            <div>
                <h2 class="text-sm font-bold uppercase tracking-wider text-indigo-400 flex items-center gap-2">
                    Static Text Displays & Stream Announcements
                    <a href="/obs/text_display" target="_blank" class="text-[10px] text-slate-400 hover:text-indigo-300 lowercase font-mono">(+ obs links)</a>
                </h2>
                <p class="text-xs text-slate-400">Fixed text items with customizable titles</p>
            </div>
        </div>

        <div class="space-y-3">
            {cards_html}
        </div>

        <!-- Add New Message Card -->
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3">
            <h3 class="text-xs font-bold uppercase tracking-wider text-slate-300">+ Create Static Text</h3>
            <form action="" method="GET" class="space-y-3">
                <input type="hidden" name="action" value="msg_save" />
                <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
                    <input 
                        type="text" 
                        name="label" 
                        placeholder="Label Title (e.g. Schedule, Goal, Topic)" 
                        class="bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500" 
                        required 
                    />
                    <div class="md:col-span-2">
                        <textarea 
                            name="content" 
                            placeholder="Display content string..." 
                            rows="1" 
                            class="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500 font-sans" 
                            required></textarea>
                    </div>
                </div>
                <button type="submit" class="bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-xs px-4 py-2 rounded-lg transition">Save Message</button>
            </form>
        </div>
    </div>
    """

def render_remote_widget(params):
    messages = load_messages()
    rows = []

    for label, content in sorted(messages.items()):
        qlabel = quote(label)
        rows.append(f"""
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-3.5 space-y-2">
            <div class="flex items-center justify-between">
                <span class="font-bold text-xs text-indigo-300 uppercase tracking-wider truncate">{escape(label)}</span>
                <a href="/remote?action=msg_delete&label={qlabel}" onclick="return confirm('Delete message: {escape(label)}?');" class="text-slate-600 hover:text-rose-400 text-xs font-mono">✕</a>
            </div>
            <form action="/remote" method="GET" class="space-y-2">
                <input type="hidden" name="action" value="msg_save" />
                <input type="hidden" name="label" value="{escape(label)}" />
                <textarea name="content" rows="2" class="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 font-sans">{escape(content)}</textarea>
                <button type="submit" class="w-full bg-indigo-600 active:bg-indigo-500 text-white font-bold text-xs py-1.5 rounded-lg transition">Update</button>
            </form>
        </div>
        """)

    return f"""
    <div class="space-y-3">
        <h2 class="text-xs font-bold uppercase tracking-wider text-indigo-400">Static Text ({len(messages)})</h2>
        {''.join(rows) if rows else '<div class="text-slate-500 text-xs text-center py-4">No messages available.</div>'}
    </div>
    """

# --- OBS Overlays & Fast Polling ---

def handle_text_overlay(params):
    theme_key = get_param(params, "theme")
    target_name = get_param(params, "name")
    layout_key = get_param(params, "layout", "single")
    is_api = get_param(params, "api") == "1"

    messages = load_messages()

    # Fast JSON endpoint for polling
    if is_api and target_name:
        content = messages.get(target_name, "")
        return json_response({"label": target_name, "content": content})

    # Stage 3: Live Overlay Browser Source
    if theme_key in OVERLAY_THEMES and target_name:
        theme = OVERLAY_THEMES[theme_key]
        layout = TEXT_LAYOUTS.get(layout_key, TEXT_LAYOUTS["single"])
        current_content = messages.get(target_name, "")
        qname = quote(target_name)

        box_shadow = "none" if theme["glow"] == "none" else f"0 4px 20px {theme['glow']}"
        text_shadow = "none" if theme["glow"] == "none" else f"0 0 12px {theme['glow']}"

        rendered_inner = layout["inner_html"].format(
            label=escape(target_name),
            content=escape(current_content)
        )

        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>OBS - {escape(target_name)}</title>
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
            {layout['container_css']}
        }}
        .text-badge {{
            background: {theme['bg']};
            border: 2px solid {theme['border']};
            box-shadow: {box_shadow};
            backdrop-filter: blur(12px);
            {layout['badge_css']}
        }}
        .text-label {{
            font-size: 1.1rem;
            font-weight: 800;
            color: {theme['text_label']};
            text-transform: uppercase;
            letter-spacing: 0.05em;
            text-shadow: 0 1px 3px rgba(0,0,0,0.8);
        }}
        .text-content {{
            font-size: 1.25rem;
            font-weight: 600;
            color: {theme['text_count']};
            text-shadow: {text_shadow};
            white-space: pre-wrap;
            word-break: break-word;
            line-height: 1.45;
        }}
        /* Clean minimal scrollbar if multiline text exceeds the OBS window */
        .text-content::-webkit-scrollbar {{ width: 4px; }}
        .text-content::-webkit-scrollbar-thumb {{ background: {theme['border']}; border-radius: 4px; }}
    </style>
    <script>
        async function updateText() {{
            try {{
                const res = await fetch('/obs/text_display?api=1&name={qname}');
                if (res.ok) {{
                    const d = await res.json();
                    document.getElementById('display-val').innerText = d.content;
                }}
            }} catch(e) {{}}
        }}
        setInterval(updateText, 500);
    </script>
</head>
<body>
    <div class="text-badge">
        {rendered_inner}
    </div>
</body>
</html>"""
        return html_response(html, with_rapid_log=False)

    # Stage 2: Pick Static Text Item
    if theme_key in OVERLAY_THEMES:
        return html_response(render_item_picker(
            base_route="/obs/text_display",
            theme_key=theme_key,
            items=messages,
            item_type_label="Static Text"
        ))

    # Stage 1: Pick Theme
    return html_response(render_theme_picker(
        base_route="/obs/text_display",
        title="Select Text Overlay Theme",
        accent_color="indigo"
    ), with_rapid_log=False)

ROUTES = {
    "/obs/text_display": handle_text_overlay
}