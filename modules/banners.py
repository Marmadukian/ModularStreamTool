import time
from utils import (
    get_data_path, read_json, write_json,
    escape, quote, get_param, json_response, html_response,
    OVERLAY_THEMES, render_theme_picker, render_obs_overlay
)

MODULE_ID = "banners"
MODULE_NAME = "Banners & Alerts"

BANNERS_FILE = get_data_path("banners_store.json")

SHARED_JS = [
    """
    function promptCustomAlert() {
        const title = prompt("Alert Title (e.g., Follower, Shoutout):");
        if (!title || !title.trim()) return;
        const text = prompt("Alert Message / Subtitle:", "Welcome to the stream!");
        const duration = prompt("Display duration in seconds:", "6");
        window.location.search = `?action=banner_push&title=${encodeURIComponent(title.trim())}&text=${encodeURIComponent(text || '')}&duration=${encodeURIComponent(duration || '6')}`;
    }
    """
]


# --- Persistence & Auto-Expiring Queue Logic ---

def load_banners() -> list:
    data = read_json(BANNERS_FILE, [])
    # Backward compatibility: unwrap old dict formats if present
    if isinstance(data, dict):
        flattened = []
        for items in data.values():
            if isinstance(items, list):
                flattened.extend(items)
        return flattened
    return data if isinstance(data, list) else []


def save_banners(data: list) -> None:
    write_json(BANNERS_FILE, data)


def receive_banner_alert(title: str, text: str = "", duration: int = 6, sound: bool = True):
    """
    Primary ingestion point for events (Twitch IRC, bits, raids, commands, or manual).
    Pushes an alert into the global queue with an active timer.
    """
    queue = load_banners()
    new_id = int(time.time() * 1000) % 10000000
    queue.append({
        "id": new_id,
        "title": title.strip(),
        "text": text.strip(),
        "duration": max(2, int(duration)),
        "sound": sound,
        "received_at": time.time(),
        "started_at": 0.0,  # Starts ticking when OBS fetches it
    })
    save_banners(queue)


def get_active_alert() -> dict:
    """
    Returns the currently active alert.
    Automatically pops expired items once their display duration ends.
    """
    queue = load_banners()
    now = time.time()
    dirty = False

    while queue:
        item = queue[0]
        started = item.get("started_at", 0.0)

        # Item hasn't been rendered yet; mark started now
        if started <= 0.0:
            item["started_at"] = now
            dirty = True
            break

        # Check expiration
        elapsed = now - started
        if elapsed >= item.get("duration", 6):
            queue.pop(0)
            dirty = True
        else:
            break

    if dirty:
        save_banners(queue)

    return queue[0] if queue else None


# --- Action Dispatcher ---

def handle_common_commands(params):
    action = get_param(params, "action")
    if not action or not action.startswith("banner_"):
        return

    queue = load_banners()

    if action == "banner_push":
        title = get_param(params, "title")
        text = get_param(params, "text")
        duration = int(get_param(params, "duration", "6"))
        if title:
            receive_banner_alert(title, text, duration=duration)

    elif action == "banner_test_raid":
        receive_banner_alert("Raid: Pokimane!", "Brought an army of 250 viewers!", duration=8)

    elif action == "banner_test_bits":
        receive_banner_alert("Bits Cheered!", "Cheered 500 bits: Let's goooo!", duration=6)

    elif action == "banner_test_sub":
        receive_banner_alert("New Subscriber!", "Subscribed at Tier 1 (3 Months)!", duration=6)

    elif action == "banner_dismiss":
        if queue:
            queue.pop(0)
            save_banners(queue)

    elif action == "banner_clear":
        save_banners([])


# --- Dashboard & Mobile Remote Widgets ---

def _render_queue_items(items: list) -> str:
    if not items:
        return '<div class="text-slate-500 text-xs italic py-6 text-center">Alert queue empty (ready for events).</div>'

    rendered = []
    for idx, item in enumerate(items):
        is_active = (idx == 0)
        badge_label = "Playing" if is_active else f"#{idx + 1}"
        bg = "bg-slate-900 border-cyan-500/50" if is_active else "bg-slate-950/70 border-slate-800"

        rendered.append(f"""
        <div class="flex items-center justify-between p-2.5 rounded-lg border {bg} text-xs">
            <div class="truncate mr-2">
                <span class="font-bold text-slate-300 font-mono text-[10px] mr-1.5 px-1.5 py-0.5 rounded bg-slate-800">{badge_label}</span>
                <strong class="text-white">{escape(item['title'])}</strong>
                {f'<span class="text-slate-400 text-[11px] ml-1.5">({escape(item["text"])})</span>' if item.get('text') else ''}
            </div>
            <span class="text-[10px] font-mono text-slate-500 shrink-0">{item.get('duration', 6)}s</span>
        </div>
        """)
    return "".join(rendered)


def render_dashboard_widget(params):
    items = load_banners()
    queue_html = _render_queue_items(items)

    return f"""
    <div id="alerts-widget-root" class="bg-slate-950/60 border border-slate-800 rounded-2xl p-5 space-y-4">
        <div class="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-3">
            <div>
                <h2 class="text-sm font-bold uppercase tracking-wider text-cyan-400 flex items-center gap-2">
                    Alert Queue
                    <a href="/obs/banner_display?theme=cyan_blue" target="_blank" class="text-[10px] text-slate-400 hover:text-cyan-300 lowercase font-mono">(+ obs link)</a>
                </h2>
                <p class="text-xs text-slate-400">Live incoming notifications & overlay stream queue</p>
            </div>

            <!-- Quick Test Buttons -->
            <div class="flex flex-wrap items-center gap-1.5">
                <span class="text-[10px] text-slate-500 font-mono mr-1">Test:</span>
                <a href="/?action=banner_test_raid" class="px-2.5 py-1 bg-slate-900 hover:bg-slate-800 text-cyan-400 border border-slate-800 rounded text-xs font-semibold">Raid</a>
                <a href="/?action=banner_test_bits" class="px-2.5 py-1 bg-slate-900 hover:bg-slate-800 text-amber-400 border border-slate-800 rounded text-xs font-semibold">Bits</a>
                <a href="/?action=banner_test_sub" class="px-2.5 py-1 bg-slate-900 hover:bg-slate-800 text-purple-400 border border-slate-800 rounded text-xs font-semibold">Sub</a>
                <button type="button" onclick="promptCustomAlert()" class="px-2.5 py-1 bg-cyan-600 hover:bg-cyan-500 text-white rounded text-xs font-bold transition">Custom</button>
            </div>
        </div>

        <!-- Action Controls -->
        <div class="flex items-center justify-between gap-2">
            <div class="flex gap-2">
                <a href="/?action=banner_dismiss" class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold rounded-lg border border-slate-700">Skip Active ⏭</a>
                <a href="/?action=banner_clear" onclick="return confirm('Clear alert queue?');" class="px-3 py-1.5 bg-slate-800 hover:bg-rose-900/40 text-slate-400 hover:text-rose-300 text-xs rounded-lg border border-slate-700">Clear All</a>
            </div>
            <span id="alerts-count-badge" class="text-[11px] font-mono text-slate-400">{len(items)} alerts waiting</span>
        </div>

        <!-- Alert Queue Container -->
        <div id="alerts-queue-list" class="space-y-1.5 max-h-64 overflow-y-auto pr-1">
            {queue_html}
        </div>

        <!-- Auto-Update Poller -->
        <script>
            (function() {{
                let lastQueueSig = "{len(items)}:{items[0]['id'] if items else 0}";

                async function checkAlertUpdates() {{
                    try {{
                        const res = await fetch('/obs/banner_display?api=1');
                        if (!res.ok) return;
                        const d = await res.json();

                        const currentSig = `${{d.queue_length}}:${{d.id || 0}}`;
                        if (currentSig !== lastQueueSig) {{
                            lastQueueSig = currentSig;
                            const badge = document.getElementById('alerts-count-badge');
                            if (badge) badge.innerText = `${{d.queue_length}} alerts waiting`;

                            if (!d.has_item && d.queue_length === 0) {{
                                const list = document.getElementById('alerts-queue-list');
                                if (list) list.innerHTML = '<div class="text-slate-500 text-xs italic py-6 text-center">Alert queue empty (ready for events).</div>';
                            }} else {{
                                window.location.reload();
                            }}
                        }}
                    }} catch (e) {{}}
                }}
                setInterval(checkAlertUpdates, 2000);
            }})();
        </script>
    </div>
    """


def render_remote_widget(params):
    items = load_banners()
    active = items[0] if items else None
    title_text = active['title'] if active else "No active alerts"
    sub_text = active['text'] if active and active['text'] else ""

    return f"""
    <div class="bg-slate-900 border border-slate-800 rounded-xl p-3.5 space-y-3">
        <div class="flex items-center justify-between">
            <span class="text-xs font-bold uppercase tracking-wider text-cyan-400">Alert Queue ({len(items)})</span>
            <button type="button" onclick="promptCustomAlert()" class="text-xs text-cyan-400 active:underline">+ Custom</button>
        </div>

        <div class="bg-slate-950 border border-slate-800/80 rounded-lg p-2.5">
            <div class="text-sm font-bold text-white truncate">{escape(title_text)}</div>
            {f'<div class="text-xs text-slate-400 truncate mt-0.5">{escape(sub_text)}</div>' if sub_text else ''}
        </div>

        <!-- Quick Test Actions -->
        <div class="grid grid-cols-3 gap-1.5">
            <a href="/remote?action=banner_test_raid" class="text-center py-1.5 bg-slate-800 text-cyan-400 rounded text-[11px] font-semibold">Raid</a>
            <a href="/remote?action=banner_test_bits" class="text-center py-1.5 bg-slate-800 text-amber-400 rounded text-[11px] font-semibold">Bits</a>
            <a href="/remote?action=banner_test_sub" class="text-center py-1.5 bg-slate-800 text-purple-400 rounded text-[11px] font-semibold">Sub</a>
        </div>

        <div class="grid grid-cols-2 gap-2 pt-1">
            <a href="/remote?action=banner_dismiss" class="text-center py-2 bg-slate-800 active:bg-slate-700 text-white rounded-lg text-xs font-bold border border-slate-700">Skip ⏭</a>
            <a href="/remote?action=banner_clear" class="text-center py-2 bg-slate-900 active:bg-rose-950 text-slate-400 rounded-lg text-xs border border-slate-800">Clear All</a>
        </div>
    </div>
    """


# --- OBS Overlays & Fast Polling ---

def handle_banner_overlay(params):
    theme_key = get_param(params, "theme")
    is_api = get_param(params, "api") == "1"

    # Fast JSON Endpoint for OBS Polling & Timer Expiration Processing
    if is_api:
        active = get_active_alert()
        queue = load_banners()
        if active:
            return json_response({
                "has_item": True,
                "queue_length": len(queue),
                "id": active["id"],
                "title": active["title"],
                "text": active["text"],
                "sound": active.get("sound", True)
            })
        return json_response({"has_item": False, "queue_length": len(queue)})

    # Stage 3: Transparent OBS Popup Card
    if theme_key in OVERLAY_THEMES and get_param(params, "card") == "1":
        theme = OVERLAY_THEMES[theme_key]
        box_shadow = "none" if theme["glow"] == "none" else f"0 6px 30px {theme['glow']}"
        text_shadow = "none" if theme["glow"] == "none" else f"0 0 14px {theme['glow']}"

        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>OBS Alert Banner</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        html, body {{
            width: 100vw; height: 100vh;
            overflow: hidden; background: transparent;
            display: flex; align-items: flex-start; justify-content: center;
            padding-top: 30px;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }}
        .banner-container {{
            width: 92vw;
            max-width: 900px;
            background: {theme['bg']};
            border: 2px solid {theme['border']};
            border-radius: 16px;
            padding: 16px 28px;
            box-shadow: {box_shadow};
            backdrop-filter: blur(16px);
            display: flex;
            align-items: center;
            gap: 20px;
            opacity: 0;
            transform: translateY(-40px) scale(0.96);
            transition: opacity 0.35s cubic-bezier(0.16, 1, 0.3, 1), transform 0.35s cubic-bezier(0.16, 1, 0.3, 1);
        }}
        .banner-visible {{
            opacity: 1;
            transform: translateY(0) scale(1);
        }}
        .banner-icon {{
            width: 12px; height: 44px;
            background: {theme['border']};
            border-radius: 6px;
            flex-shrink: 0;
            box-shadow: 0 0 14px {theme['border']};
        }}
        .banner-body {{
            flex: 1; min-width: 0;
        }}
        .banner-title {{
            font-size: 1.45rem;
            font-weight: 800;
            color: {theme['text_count']};
            text-shadow: {text_shadow};
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            line-height: 1.2;
            letter-spacing: 0.02em;
        }}
        .banner-text {{
            font-size: 1.05rem;
            font-weight: 600;
            color: {theme['text_label']};
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            margin-top: 3px;
        }}
    </style>
    <script>
        let currentAlertId = null;

        // Browser WebAudio notification chime (no external audio assets needed)
        function playChime() {{
            try {{
                const ctx = new (window.AudioContext || window.webkitAudioContext)();
                const now = ctx.currentTime;

                const osc1 = ctx.createOscillator();
                const osc2 = ctx.createOscillator();
                const gain = ctx.createGain();

                osc1.type = 'sine';
                osc2.type = 'triangle';
                osc1.frequency.setValueAtTime(587.33, now); // D5
                osc1.frequency.exponentialRampToValueAtTime(880, now + 0.12); // A5

                osc2.frequency.setValueAtTime(880, now);
                osc2.frequency.exponentialRampToValueAtTime(1174.66, now + 0.18); // D6

                gain.gain.setValueAtTime(0.15, now);
                gain.gain.exponentialRampToValueAtTime(0.001, now + 0.6);

                osc1.connect(gain);
                osc2.connect(gain);
                gain.connect(ctx.destination);

                osc1.start(now);
                osc2.start(now);
                osc1.stop(now + 0.6);
                osc2.stop(now + 0.6);
            }} catch (e) {{}}
        }}

        async function pollAlerts() {{
            try {{
                const res = await fetch('/obs/banner_display?api=1');
                if (!res.ok) return;
                const d = await res.json();

                const card = document.getElementById('banner-card');
                const tEl = document.getElementById('b-title');
                const sEl = document.getElementById('b-text');

                if (!d.has_item) {{
                    card.classList.remove('banner-visible');
                    currentAlertId = null;
                    return;
                }}

                if (d.id !== currentAlertId) {{
                    currentAlertId = d.id;
                    tEl.innerText = d.title;
                    if (d.text) {{
                        sEl.innerText = d.text;
                        sEl.style.display = 'block';
                    }} else {{
                        sEl.style.display = 'none';
                    }}

                    card.classList.add('banner-visible');
                    if (d.sound) playChime();
                }}
            }} catch(e) {{}}
        }}

        setInterval(pollAlerts, 300);
    </script>
</head>
<body>
    <div id="banner-card" class="banner-container">
        <div class="banner-icon"></div>
        <div class="banner-body">
            <div id="b-title" class="banner-title"></div>
            <div id="b-text" class="banner-text"></div>
        </div>
    </div>
</body>
</html>"""
        return html_response(html, with_rapid_log=False)

    # Stage 2: Standard/Compact OBS HUD Overlay
    if theme_key in OVERLAY_THEMES:
        html = render_obs_overlay(
            title="Alerts Banner",
            theme_key=theme_key,
            custom_css="""
            .obs-root { justify-content: flex-start; padding: 0 20px; transition: opacity 0.3s; }
            .hidden-alert { opacity: 0; }
        """,
            inner_html="""
            <div class="obs-val text-lg truncate" id="b-title"></div>
            <div class="obs-label text-sm truncate ml-3" id="b-text"></div>
        """,
            poll_endpoint="/obs/banner_display?api=1",
            poll_js="""
            const root = document.getElementById('obs-container');
            if (!data.has_item) { root.classList.add('hidden-alert'); return; }
            root.classList.remove('hidden-alert');
            document.getElementById('b-title').innerText = data.title;
            document.getElementById('b-text').innerText = data.text || '';
        """,
        )
        return html_response(html, with_rapid_log=False)

    # Stage 1: Pick Theme
    return html_response(render_theme_picker(
        base_route="/obs/banner_display",
        title="Select Banner Overlay Theme",
        accent_color="cyan"
    ), with_rapid_log=False)


def handle_chat_event(event_type: str, data: dict):
    if event_type == "raid":
        receive_banner_alert(
            f"Raid: {data['user']}!",
            f"Brought an army of {data['viewers']} viewers!",
            duration=10
        )
    elif event_type == "bits":
        receive_banner_alert(
            f"{data['user']} cheered {data['amount']} bits!",
            data.get("message", "Thanks for the support!"),
            duration=7
        )
    elif event_type == "sub":
        receive_banner_alert(
            f"{data['user']} subscribed!",
            f"Joined the hype train ({data['months']} months)!",
            duration=7
        )


ROUTES = {
    "/obs/banner_display": handle_banner_overlay
}