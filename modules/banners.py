import time
from utils import (
    get_data_path, read_json, write_json,
    escape, quote, get_param, json_response, html_response,
    OVERLAY_THEMES, render_theme_picker, render_item_picker
)

MODULE_ID = "banners"
MODULE_NAME = "Stream Banners & Received Alerts"

BANNERS_FILE = get_data_path("banners_store.json")

SHARED_JS = [
    """
    function promptPushAlert(slot) {
        const title = prompt(`Alert Title for "${slot}" (e.g., New Raid!, 500 Bits):`);
        if (!title || !title.trim()) return;
        const text = prompt("Alert Message / Subtitle:", "Thanks for the hype!");
        const duration = prompt("Display duration in seconds:", "6");
        window.location.search = `?action=banner_push&slot=${encodeURIComponent(slot)}&title=${encodeURIComponent(title.trim())}&text=${encodeURIComponent(text || '')}&duration=${encodeURIComponent(duration || '6')}`;
    }

    function promptCreateBannerSlot() {
        const slot = prompt("New banner/alert slot name (e.g., Alerts, RaidBanner, Ticker):");
        if (slot && slot.trim()) {
            window.location.search = `?action=banner_create_slot&slot=${encodeURIComponent(slot.trim())}`;
        }
    }
    """
]


# --- Persistence & Auto-Expiring Queue Logic ---

def load_banners() -> dict:
    return read_json(BANNERS_FILE, {})


def save_banners(data: dict) -> None:
    write_json(BANNERS_FILE, data)


def receive_banner_alert(slot: str, title: str, text: str = "", duration: int = 6, sound: bool = True):
    """
    Primary ingestion point for events (Twitch IRC, bits, raids, commands, or manual).
    Pushes an alert into the slot's received queue with an active timer.
    """
    banners = load_banners()
    if slot not in banners:
        banners[slot] = []

    new_id = int(time.time() * 1000) % 10000000
    banners[slot].append({
        "id": new_id,
        "title": title.strip(),
        "text": text.strip(),
        "duration": max(2, int(duration)),
        "sound": sound,
        "received_at": time.time(),
        "started_at": 0.0,  # Starts ticking when OBS fetches it
    })
    save_banners(banners)


def get_active_alert(slot: str) -> dict:
    """
    Returns the currently active alert for a slot.
    Automatically pops expired items once their display duration ends.
    """
    banners = load_banners()
    queue = banners.get(slot, [])
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
        banners[slot] = queue
        save_banners(banners)

    return queue[0] if queue else None


# --- Action Dispatcher ---

def handle_common_commands(params):
    action = get_param(params, "action")
    if not action or not action.startswith("banner_"):
        return

    slot = get_param(params, "slot").strip()
    banners = load_banners()

    if action == "banner_create_slot" and slot:
        if slot not in banners:
            banners[slot] = []
            save_banners(banners)

    elif action == "banner_push" and slot:
        title = get_param(params, "title")
        text = get_param(params, "text")
        duration = int(get_param(params, "duration", "6"))
        if title:
            receive_banner_alert(slot, title, text, duration=duration)

    elif action == "banner_dismiss" and slot in banners:
        if banners[slot]:
            banners[slot].pop(0)
            save_banners(banners)

    elif action == "banner_clear" and slot in banners:
        banners[slot] = []
        save_banners(banners)

    elif action == "banner_delete_slot" and slot in banners:
        del banners[slot]
        save_banners(banners)


# --- Dashboard & Mobile Remote Widgets ---

def render_dashboard_widget(params):
    banners = load_banners()
    slot_cards = []

    for slot, items in sorted(banners.items()):
        qslot = quote(slot)
        queue_items = []

        for idx, item in enumerate(items):
            is_active = (idx == 0)
            badge_label = "Playing" if is_active else f"Queue #{idx + 1}"
            bg = "bg-slate-900 border-cyan-500/50" if is_active else "bg-slate-950/70 border-slate-800"

            queue_items.append(f"""
            <div class="flex items-center justify-between p-2 rounded-lg border {bg} text-xs">
                <div class="truncate mr-2">
                    <span class="font-bold text-slate-300 font-mono text-[10px] mr-1.5 px-1 py-0.5 rounded bg-slate-800">{badge_label}</span>
                    <strong class="text-white">{escape(item['title'])}</strong>
                    {f'<span class="text-slate-400 text-[11px] ml-1">({escape(item["text"])})</span>' if item['text'] else ''}
                </div>
                <span class="text-[10px] font-mono text-slate-500 shrink-0">{item.get('duration', 6)}s</span>
            </div>
            """)

        queue_block = "".join(
            queue_items) if queue_items else '<div class="text-slate-500 text-xs italic py-3 text-center">Alert queue empty (ready for events).</div>'

        slot_cards.append(f"""
        <div class="bg-slate-900/90 border border-slate-800 rounded-xl p-4 shadow-sm space-y-3">
            <div class="flex items-center justify-between border-b border-slate-800/80 pb-2">
                <div class="flex items-center gap-2">
                    <span class="font-bold text-sm text-cyan-300 uppercase tracking-wider">{escape(slot)}</span>
                    <span class="text-[10px] font-mono bg-slate-950 border border-slate-800 px-1.5 py-0.5 rounded text-slate-400">{len(items)} waiting</span>
                </div>
                <div class="flex items-center gap-2">
                    <a href="/obs/banner_display?theme=cyan_blue&name={qslot}" target="_blank" class="text-[11px] text-cyan-400 hover:underline">OBS ↗</a>
                    <a href="/?action=banner_delete_slot&slot={qslot}" onclick="return confirm('Delete slot {escape(slot)}?');" class="text-slate-600 hover:text-rose-400 text-xs font-mono">✕</a>
                </div>
            </div>

            <!-- Action Controls -->
            <div class="flex items-center justify-between gap-2">
                <button type="button" onclick="promptPushAlert('{escape(slot)}')" class="bg-cyan-600 hover:bg-cyan-500 text-white font-bold text-xs px-2.5 py-1.5 rounded transition">+ Test Alert</button>
                <div class="flex gap-1.5">
                    <a href="/?action=banner_dismiss&slot={qslot}" class="px-2.5 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold rounded border border-slate-700">Skip Active ⏭</a>
                    <a href="/?action=banner_clear&slot={qslot}" onclick="return confirm('Clear queue for {escape(slot)}?');" class="px-2 py-1.5 bg-slate-800 hover:bg-rose-900/40 text-slate-400 hover:text-rose-300 text-xs rounded border border-slate-700">Clear</a>
                </div>
            </div>

            <!-- Queue preview -->
            <div class="space-y-1.5 max-h-40 overflow-y-auto pr-1">
                {queue_block}
            </div>
        </div>
        """)

    grid = "".join(
        slot_cards) if slot_cards else '<div class="col-span-full text-slate-500 text-xs italic py-6 text-center">No alert channels setup. Add "Alerts" to start.</div>'

    return f"""
    <div class="bg-slate-950/60 border border-slate-800 rounded-2xl p-5 space-y-4">
        <div class="flex items-center justify-between border-b border-slate-800 pb-3">
            <div>
                <h2 class="text-sm font-bold uppercase tracking-wider text-cyan-400 flex items-center gap-2">
                    Received Banners & Dynamic Alerts
                    <a href="/obs/banner_display" target="_blank" class="text-[10px] text-slate-400 hover:text-cyan-300 lowercase font-mono">(+ obs links)</a>
                </h2>
                <p class="text-xs text-slate-400">Auto-popping notification queues for stream events & popups</p>
            </div>
            <button type="button" onclick="promptCreateBannerSlot()" class="bg-cyan-600 hover:bg-cyan-500 text-white font-bold text-xs px-3 py-1.5 rounded-lg transition">
                + New Alert Channel
            </button>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {grid}
        </div>
    </div>
    """


def render_remote_widget(params):
    banners = load_banners()
    cards = []

    for slot, items in sorted(banners.items()):
        qslot = quote(slot)
        active = items[0] if items else None
        title_text = active['title'] if active else "No active alerts"
        sub_text = active['text'] if active and active['text'] else ""

        cards.append(f"""
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-3.5 space-y-2">
            <div class="flex items-center justify-between">
                <span class="text-xs font-bold uppercase tracking-wider text-cyan-400">{escape(slot)} ({len(items)})</span>
                <button type="button" onclick="promptPushAlert('{escape(slot)}')" class="text-xs text-cyan-400 active:underline">+ Send</button>
            </div>
            <div class="bg-slate-950 border border-slate-800/80 rounded-lg p-2.5">
                <div class="text-sm font-bold text-white truncate">{escape(title_text)}</div>
                {f'<div class="text-xs text-slate-400 truncate mt-0.5">{escape(sub_text)}</div>' if sub_text else ''}
            </div>
            <div class="grid grid-cols-2 gap-2 pt-1">
                <a href="/remote?action=banner_dismiss&slot={qslot}" class="text-center py-2 bg-slate-800 active:bg-slate-700 text-white rounded-lg text-xs font-bold border border-slate-700">Skip ⏭</a>
                <a href="/remote?action=banner_clear&slot={qslot}" class="text-center py-2 bg-slate-900 active:bg-rose-950 text-slate-400 rounded-lg text-xs border border-slate-800">Clear All</a>
            </div>
        </div>
        """)

    return f"""
    <div class="space-y-3">
        <h2 class="text-xs font-bold uppercase tracking-wider text-cyan-400">Received Alerts</h2>
        {''.join(cards) if cards else '<div class="text-slate-500 text-xs text-center py-4">No alert channels.</div>'}
    </div>
    """


# --- OBS Overlays & Fast Polling ---

def handle_banner_overlay(params):
    theme_key = get_param(params, "theme")
    slot = get_param(params, "name")
    is_api = get_param(params, "api") == "1"

    # Fast JSON Endpoint for OBS Polling & Timer Expiration Processing
    if is_api and slot:
        active = get_active_alert(slot)
        if active:
            return json_response({
                "slot": slot,
                "has_item": True,
                "id": active["id"],
                "title": active["title"],
                "text": active["text"],
                "sound": active.get("sound", True)
            })
        return json_response({"slot": slot, "has_item": False})

    # Stage 3: Transparent OBS Overlay Screen
    if theme_key in OVERLAY_THEMES and slot:
        theme = OVERLAY_THEMES[theme_key]
        qslot = quote(slot)

        box_shadow = "none" if theme["glow"] == "none" else f"0 6px 30px {theme['glow']}"
        text_shadow = "none" if theme["glow"] == "none" else f"0 0 14px {theme['glow']}"

        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>OBS Alert Banner - {escape(slot)}</title>
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
                const res = await fetch('/obs/banner_display?api=1&name={qslot}');
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
        return html_response(html)

    # Stage 2: Pick Channel / Slot
    if theme_key in OVERLAY_THEMES:
        banners = load_banners()
        items_preview = {slot: f"{len(items)} queued" for slot, items in banners.items()}
        return html_response(render_item_picker(
            base_route="/obs/banner_display",
            theme_key=theme_key,
            items=items_preview,
            item_type_label="Alert Channel"
        ))

    # Stage 1: Pick Theme
    return html_response(render_theme_picker(
        base_route="/obs/banner_display",
        title="Select Received Banner Overlay Theme",
        accent_color="cyan"
    ))


def handle_chat_event(event_type: str, data: dict):
    if event_type == "raid":
        receive_banner_alert(
            "Alerts",
            f"Raid: {data['user']}!",
            f"Brought an army of {data['viewers']} viewers!",
            duration=10
        )
    elif event_type == "bits":
        receive_banner_alert(
            "Alerts",
            f"{data['user']} cheered {data['amount']} bits!",
            data.get("message", "Thanks for the support!"),
            duration=7
        )
    elif event_type == "sub":
        receive_banner_alert(
            "Alerts",
            f"{data['user']} subscribed!",
            f"Joined the hype train ({data['months']} months)!",
            duration=7
        )



ROUTES = {
    "/obs/banner_display": handle_banner_overlay
}