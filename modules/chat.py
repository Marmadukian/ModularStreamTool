import time
from utils import (
    BASE_DIR,
    read_json,
    write_json,
    escape,
    quote,
    get_param,
    json_response,
    html_response,
    render_obs_overlay,
    render_theme_picker,
    OVERLAY_THEMES,
    render_page,
    get_data_path,
)

MODULE_ID = "chat"
MODULE_NAME = "Stream Chat Overlays"

# In-memory circular buffer for active chat messages
MAX_CHAT_HISTORY = 75
chat_history = []
_msg_counter = 0

CHAT_LAYOUTS = {
    "box": {
        "label": "Boxed Bubbles",
        "desc": "Rounded message cards stacked vertically.",
        "container_css": "flex-direction: column; justify-content: flex-end; padding: 16px; gap: 8px;",
        "item_css": "background: rgba(15, 23, 42, 0.75); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 10px; padding: 8px 12px;",
        "auto_fade": False,
    },
    "minimal": {
        "label": "Minimal Transparent",
        "desc": "Border-free text over transparent background for overlaying on gameplay.",
        "container_css": "flex-direction: column; justify-content: flex-end; padding: 12px; gap: 6px;",
        "item_css": "background: transparent; padding: 2px 0;",
        "auto_fade": False,
    },
    "ephemeral": {
        "label": "Ephemeral (Auto-Fade)",
        "desc": "Messages fade out and disappear after 12 seconds.",
        "container_css": "flex-direction: column; justify-content: flex-end; padding: 16px; gap: 8px;",
        "item_css": "background: rgba(15, 23, 42, 0.85); border-left: 3px solid #10b981; border-radius: 0 8px 8px 0; padding: 6px 12px;",
        "auto_fade": True,
    },
}


# --- Event Ingestion ---


def handle_chat_message(user: str, message: str, tags: dict):
    """Called by twitch_listener whenever a chat message arrives."""
    global chat_history, _msg_counter
    _msg_counter += 1

    color = tags.get("color") or "#38bdf8"
    badges = tags.get("badges", "")

    is_mod = "moderator/1" in badges
    is_broadcaster = "broadcaster/1" in badges
    is_sub = "subscriber" in badges

    badge_label = ""
    if is_broadcaster:
        badge_label = "👑 "
    elif is_mod:
        badge_label = "⚔️ "
    elif is_sub:
        badge_label = "⭐ "

    chat_history.append({
        "id": _msg_counter,
        "user": user,
        "badge": badge_label,
        "color": color,
        "text": message,
        "timestamp": time.time(),
    })

    if len(chat_history) > MAX_CHAT_HISTORY:
        chat_history = chat_history[-MAX_CHAT_HISTORY:]


# --- API & OBS Endpoints ---


def api_get_chat(params):
    """Fast polling endpoint for OBS browser source."""
    after_id = int(get_param(params, "after", "0"))
    if after_id > 0:
        new_msgs = [m for m in chat_history if m["id"] > after_id]
    else:
        new_msgs = chat_history[-25:]  # Seed with recent messages on connect

    return json_response({
        "messages": new_msgs,
        "last_id": chat_history[-1]["id"] if chat_history else after_id,
    })


def handle_chat_overlay(params):
    theme_key = get_param(params, "theme")
    layout_key = get_param(params, "layout", "box")

    # Step 2: Pick Layout
    if theme_key and not get_param(params, "layout"):
        links = []
        for lk, lcfg in CHAT_LAYOUTS.items():
            links.append(f"""
            <a href="/obs/chat?theme={theme_key}&layout={lk}" 
               class="flex flex-col p-3.5 bg-slate-900/90 hover:bg-slate-800 border border-slate-800 hover:border-emerald-500 rounded-xl transition text-decoration-none group gap-1">
                <span class="font-bold text-slate-200 text-sm group-hover:text-white">{escape(lcfg['label'])}</span>
                <span class="text-xs text-slate-400">{escape(lcfg['desc'])}</span>
            </a>
            """)

        return html_response(f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>OBS Chat - Select Layout</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-[#0b0f19] text-slate-200 p-6 min-h-screen flex flex-col justify-center items-center">
    <div class="w-full max-w-md bg-slate-950/80 border border-slate-800 p-5 rounded-2xl shadow-xl space-y-4">
        <div class="border-b border-slate-800 pb-3 flex justify-between items-center">
            <h1 class="text-base font-black text-white">Select Chat Layout</h1>
            <a href="/obs/chat" class="text-xs text-slate-400 hover:text-slate-200">← Back</a>
        </div>
        <div class="space-y-2">
            {''.join(links)}
        </div>
    </div>
</body>
</html>""")

    # Step 3: Render OBS View
    if theme_key in OVERLAY_THEMES and layout_key in CHAT_LAYOUTS:
        layout = CHAT_LAYOUTS[layout_key]
        fade_script = ""
        if layout.get("auto_fade"):
            fade_script = """
                        setTimeout(() => {
                            row.style.transition = 'opacity 1s ease';
                            row.style.opacity = '0';
                            setTimeout(() => row.remove(), 1000);
                        }, 12000);
            """

        custom_css = f"""
        .obs-root {{
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
            backdrop-filter: none !important;
            overflow: hidden;
            display: flex;
            {layout['container_css']}
        }}
        #chat-stream-box {{
            display: flex;
            flex-direction: column;
            justify-content: flex-end;
            width: 100%;
            gap: 6px;
        }}
        .chat-row {{
            width: 100%;
            word-break: break-word;
            line-height: 1.35;
            font-size: 1.05rem;
            {layout['item_css']}
        }}
        .chat-user {{
            font-weight: 800;
            text-shadow: 0 1px 4px rgba(0, 0, 0, 0.9);
        }}
        .chat-text {{
            color: #f8fafc;
            font-weight: 600;
            text-shadow: 0 1px 4px rgba(0, 0, 0, 0.9);
            margin-left: 6px;
        }}
        """

        script_tag = f"""
        <script>
            let lastId = 0;
            const box = document.getElementById('chat-stream-box');

            async function fetchMessages() {{
                try {{
                    const res = await fetch('/api/chat/messages?after=' + lastId);
                    if (!res.ok) return;
                    const data = await res.json();

                    if (data.messages && data.messages.length > 0) {{
                        data.messages.forEach(m => {{
                            const row = document.createElement('div');
                            row.className = 'chat-row';
                            row.innerHTML = `<span class="chat-user" style="color: ${{m.color}}">${{m.badge}}${{m.user}}:</span><span class="chat-text">${{m.text}}</span>`;
                            box.appendChild(row);
                            {fade_script}
                        }});

                        lastId = data.last_id;
                        while (box.children.length > 50) {{
                            box.removeChild(box.firstChild);
                        }}
                    }}
                }} catch(e) {{}}
            }}

            fetchMessages();
            setInterval(fetchMessages, 400);
        </script>
        """

        html = render_obs_overlay(
            title=f"OBS Chat - {layout_key}",
            theme_key=theme_key,
            inner_html='<div id="chat-stream-box"></div>',
            custom_css=custom_css,
        )

        # Force the script tag in before closing body tag so render_obs_overlay can't drop it
        if "</body>" in html:
            html = html.replace("</body>", f"{script_tag}</body>")
        else:
            html += script_tag

        return html_response(html)

    # Step 1: Pick Theme
    return html_response(
        render_theme_picker(
            base_route="/obs/chat",
            title="Select Chat Theme / Palette",
            accent_color="emerald",
        )
    )


# --- Dashboard Widgets ---


def render_dashboard_widget(params):
    print(f"[DEBUG DASH CHAT] chat_history length: {len(chat_history)}, id: {id(chat_history)}")
    recent = chat_history[-8:]
    rows = []
    for m in reversed(recent):
        rows.append(f"""
        <div class="p-2 bg-slate-900 border border-slate-800 rounded-lg text-xs">
            <span class="font-bold" style="color: {m['color']}">{escape(m['badge'])}{escape(m['user'])}:</span>
            <span class="text-slate-300 ml-1">{escape(m['text'])}</span>
        </div>
        """)

    content = "".join(
        rows) if rows else '<div class="text-slate-500 text-xs italic py-4 text-center">Chat quiet. Waiting for messages...</div>'

    return f"""
    <div class="p-5 space-y-4">
        <div class="flex items-center justify-between border-b border-slate-800 pb-3">
            <div>
                <h2 class="text-sm font-bold uppercase tracking-wider text-emerald-400 flex items-center gap-2">
                    Live Chat Stream
                    <a href="/obs/chat" target="_blank" class="text-[10px] text-slate-400 hover:text-emerald-300 lowercase font-mono">(+ obs links)</a>
                </h2>
                <span id="dash-chat-count" class="text-xs text-slate-400">{len(chat_history)} messages buffered in memory</span>
            </div>
        </div>
        <div id="dash-chat-feed" class="space-y-1.5 max-h-48 overflow-y-auto pr-1">
            {content}
        </div>
    </div>

    <script>
        (function() {{
            if (window._chatDashPollingInitialized) return;
            window._chatDashPollingInitialized = true;

            let lastSeenId = 0;
            const feed = document.getElementById('dash-chat-feed');
            const countLabel = document.getElementById('dash-chat-count');

            async function pollDashChat() {{
                try {{
                    const res = await fetch('/api/chat/messages?after=' + lastSeenId);
                    if (!res.ok) return;
                    const data = await res.json();

                    if (data.messages && data.messages.length > 0) {{
                        // Clear placeholder if it exists
                        const emptyNotice = feed.querySelector('.italic');
                        if (emptyNotice) feed.innerHTML = '';

                        data.messages.forEach(m => {{
                            const row = document.createElement('div');
                            row.className = 'p-2 bg-slate-900 border border-slate-800 rounded-lg text-xs';
                            row.innerHTML = `<span class="font-bold" style="color: ${{m.color}}">${{m.badge}}${{m.user}}:</span><span class="text-slate-300 ml-1">${{m.text}}</span>`;
                            feed.prepend(row);
                        }});

                        lastSeenId = data.last_id;

                        // Trim to recent 15
                        while (feed.children.length > 15) {{
                            feed.removeChild(feed.lastChild);
                        }}
                    }}
                }} catch (e) {{}}
            }}

            setInterval(pollDashChat, 1000);
        }})();
    </script>
    """


def render_remote_widget(params):
    recent = chat_history[-5:]
    rows = []
    for m in reversed(recent):
        rows.append(f"""
        <div class="p-2 bg-slate-900 border border-slate-800 rounded-lg text-xs truncate">
            <span class="font-bold" style="color: {m['color']}">{escape(m['user'])}:</span>
            <span class="text-slate-300 ml-1">{escape(m['text'])}</span>
        </div>
        """)

    return f"""
    <div class="space-y-2">
        <h2 class="text-xs font-bold uppercase tracking-wider text-emerald-400">Recent Chat</h2>
        {''.join(rows) if rows else '<div class="text-slate-500 text-xs text-center py-2">No messages.</div>'}
    </div>
    """


ROUTES = {
    "/api/chat/messages": api_get_chat,
    "/obs/chat": handle_chat_overlay,
}