import asyncio
import json
import time
import threading
import websockets

from utils import (
    get_data_path, read_json, write_json,
    escape, quote, get_param, json_response, html_response,
    OVERLAY_THEMES, render_theme_picker, render_item_picker
)

MODULE_ID = "beatsaber"
MODULE_NAME = "Beat Saber HUD & Queue"

REQUESTS_FILE = get_data_path("song_requests.json")
MODERATION_FILE = get_data_path("bs_moderation.json")

# --- Module State ---

game_state = {
    "song_name": "In Menu",
    "artist": "",
    "mapper": "",
    "accuracy": 0.0,
    "combo": 0,
    "misses": 0,
    "cover_image_b64": ""
}

OVERLAY_LAYOUTS = {
    "full_hud": "Full HUD (Cover, Song Info & Live Stats)",
    "song_card": "Song Card Only (Cover, Title, Artist, Mapper)",
    "stats_only": "Live Stats Only (Accuracy, Combo, Misses)",
}

SHARED_JS = [
    """
    function promptManualRequest() {
        const user = prompt("Requester Name:", "Streamer");
        if (!user) return;
        const song = prompt("Song name / BeatSaver Key ($!bsr):");
        if (song && song.trim()) {
            window.location.search = `?action=bs_add_req&user=${encodeURIComponent(user)}&query=${encodeURIComponent(song.trim())}`;
        }
    }
    """
]

# --- Moderation Storage ---

def load_moderation() -> dict:
    return read_json(MODERATION_FILE, {
        "banned_users": [],
        "banned_keys": [],
        "queue_open": True,
        "max_queue_size": 25
    })

def save_moderation(data: dict) -> None:
    write_json(MODERATION_FILE, data)


# --- Persistence & Request Helpers ---

def load_requests() -> list:
    return read_json(REQUESTS_FILE, [])

def save_requests(data: list) -> None:
    write_json(REQUESTS_FILE, data)

def add_song_request(user: str, raw_query: str):
    query = raw_query.strip()
    if not query:
        return

    requests = load_requests()
    # Anti-spam: Overwrite previous unplayed request if from same user
    for req in requests:
        if req["user"].lower() == user.lower() and not req.get("played", False):
            req["query"] = query
            req["timestamp"] = time.time()
            save_requests(requests)
            return

    requests.append({
        "id": len(requests) + 1,
        "user": user,
        "query": query,
        "timestamp": time.time(),
        "played": False,
    })
    save_requests(requests)

# --- Background BSDataPuller WebSocket Listeners ---

async def track_map_data():
    uri = "ws://127.0.0.1:2946/BSDataPuller/MapData"
    while True:
        try:
            async with websockets.connect(uri) as ws:
                async for raw_msg in ws:
                    data = json.loads(raw_msg)
                    title = data.get("SongName") or data.get("songName") or ""
                    sub_title = data.get("SongSubName") or ""
                    if sub_title:
                        title = f"{title} {sub_title}".strip()

                    artist = data.get("SongAuthorName") or data.get("SongAuthor") or data.get("songAuthorName") or ""
                    mapper = data.get("LevelAuthorName") or data.get("Mapper") or data.get("levelAuthorName") or ""
                    cover = data.get("coverImage") or data.get("SongCover") or data.get("coverImage_b64") or ""

                    if title:
                        game_state["song_name"] = title
                        game_state["artist"] = artist
                        game_state["mapper"] = mapper
                    if cover:
                        game_state["cover_image_b64"] = cover
        except (websockets.ConnectionClosed, ConnectionRefusedError):
            await asyncio.sleep(2)
        except Exception:
            await asyncio.sleep(2)

async def track_live_data():
    uri = "ws://127.0.0.1:2946/BSDataPuller/LiveData"
    while True:
        try:
            async with websockets.connect(uri) as ws:
                async for raw_msg in ws:
                    data = json.loads(raw_msg)
                    game_state["accuracy"] = data.get("Accuracy", 0.0)
                    game_state["combo"] = data.get("Combo", 0)
                    game_state["misses"] = data.get("Misses", 0)
        except (websockets.ConnectionClosed, ConnectionRefusedError):
            await asyncio.sleep(2)
        except Exception:
            await asyncio.sleep(2)

def start_background_listeners():
    def run_loop():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(asyncio.gather(track_map_data(), track_live_data()))

    threading.Thread(target=run_loop, daemon=True).start()

# Automatically spin up BSDataPuller listeners when module imports
start_background_listeners()

# --- Common Action Dispatcher ---

def handle_common_commands(params):
    action = get_param(params, "action")
    if not action or not action.startswith("bs_"):
        return

    requests = load_requests()

    if action == "bs_add_req":
        user = get_param(params, "user", "Streamer")
        query = get_param(params, "query", "")
        if query:
            add_song_request(user, query)

    elif action == "bs_toggle_played":
        req_id = int(get_param(params, "id", "0"))
        for req in requests:
            if req.get("id") == req_id:
                req["played"] = not req.get("played", False)
                break
        save_requests(requests)

    elif action == "bs_delete_req":
        req_id = int(get_param(params, "id", "0"))
        requests = [r for r in requests if r.get("id") != req_id]
        save_requests(requests)

    elif action == "bs_clear_played":
        requests = [r for r in requests if not r.get("played", False)]
        save_requests(requests)

# --- Dashboard & Mobile Widgets ---

def render_dashboard_widget(params):
    requests = load_requests()
    pending = [r for r in requests if not r.get("played", False)]

    # Real-time Song Monitor Card
    current_artist = game_state["artist"]
    if game_state["mapper"]:
        current_artist += f" [{game_state['mapper']}]"

    queue_rows = []
    for r in requests:
        status_style = "opacity-40 line-through" if r.get("played") else "text-white"
        toggle_label = "↺ Unmark" if r.get("played") else "✓ Played"
        toggle_color = "bg-slate-800 hover:bg-slate-700" if r.get("played") else "bg-emerald-600 hover:bg-emerald-500 text-white"

        queue_rows.append(f"""
        <div class="flex items-center justify-between p-2.5 bg-slate-900 border border-slate-800/80 rounded-xl {status_style}">
            <div class="truncate mr-3">
                <span class="font-bold text-xs text-rose-400">#{r['id']} {escape(r['user'])}:</span>
                <span class="text-xs text-slate-200 font-mono ml-1">{escape(r['query'])}</span>
            </div>
            <div class="flex items-center gap-1.5 shrink-0">
                <a href="/?action=bs_toggle_played&id={r['id']}" class="px-2.5 py-1 text-[10px] font-bold rounded {toggle_color} transition">{toggle_label}</a>
                <a href="/?action=bs_delete_req&id={r['id']}" class="px-2 py-1 text-[10px] bg-slate-800 hover:bg-rose-900/50 text-slate-400 hover:text-rose-300 font-mono rounded">✕</a>
            </div>
        </div>
        """)

    return f"""
    <div class="bg-slate-950/60 border border-slate-800 rounded-2xl p-5 space-y-5">
        <!-- Header -->
        <div class="flex items-center justify-between border-b border-slate-800 pb-3">
            <div>
                <h2 class="text-sm font-bold uppercase tracking-wider text-rose-400 flex items-center gap-2">
                    Beat Saber Live Monitor
                    <a href="/obs/beatsaber" target="_blank" class="text-[10px] text-slate-400 hover:text-rose-300 lowercase font-mono">(+ obs links)</a>
                </h2>
                <span class="text-xs font-mono text-slate-400">{len(pending)} unplayed song requests</span>
            </div>
            <div class="flex gap-2">
                <button type="button" onclick="promptManualRequest()" class="bg-rose-600 hover:bg-rose-500 text-white font-bold text-xs px-3 py-1.5 rounded-lg transition">+ Add Request</button>
                <a href="/?action=bs_clear_played" class="bg-slate-900 hover:bg-slate-800 text-slate-400 hover:text-white text-xs px-3 py-1.5 rounded-lg border border-slate-800">Clear Played</a>
            </div>
        </div>

        <!-- Live Status Bar -->
        <div class="grid grid-cols-1 md:grid-cols-4 gap-3 bg-slate-900/90 border border-slate-800 p-3.5 rounded-xl">
            <div class="md:col-span-2 flex items-center gap-3">
                <img id="cover-img" class="w-12 h-12 rounded-lg bg-slate-950 border border-slate-800 object-cover" src="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='48' height='48' fill='%231e293b'></svg>" alt="Cover" />
                <div class="min-w-0">
                    <div id="song-title" class="text-sm font-black text-white truncate">{escape(game_state['song_name'])}</div>
                    <div id="song-artist" class="text-xs text-slate-400 truncate">{escape(current_artist or '—')}</div>
                </div>
            </div>
            <div class="flex items-center justify-around md:col-span-2 border-t md:border-t-0 md:border-l border-slate-800 pt-2 md:pt-0 font-mono">
                <div class="text-center">
                    <span class="text-[10px] text-slate-500 block uppercase">Accuracy</span>
                    <span id="stat-acc" class="text-base font-bold text-emerald-400">{game_state['accuracy']:.2f}%</span>
                </div>
                <div class="text-center">
                    <span class="text-[10px] text-slate-500 block uppercase">Combo</span>
                    <span id="stat-combo" class="text-base font-bold text-cyan-400">{game_state['combo']}</span>
                </div>
                <div class="text-center">
                    <span class="text-[10px] text-slate-500 block uppercase">Misses</span>
                    <span id="stat-misses" class="text-base font-bold text-rose-400">{game_state['misses']}</span>
                </div>
            </div>
        </div>

        <!-- Song Queue Section -->
        <div class="space-y-2 max-h-60 overflow-y-auto pr-1">
            {''.join(queue_rows) if queue_rows else '<div class="text-center text-slate-500 text-xs py-4">No active song requests.</div>'}
        </div>
    </div>
    """

def render_remote_widget(params):
    requests = load_requests()
    pending = [r for r in requests if not r.get("played", False)]

    items = []
    for r in pending[:5]:  # Top 5 unplayed for fast mobile checks
        items.append(f"""
        <div class="flex items-center justify-between p-2.5 bg-slate-900 border border-slate-800 rounded-xl">
            <div class="truncate mr-2">
                <span class="text-xs font-bold text-rose-400">#{r['id']} {escape(r['user'])}</span>
                <div class="text-[11px] text-slate-300 font-mono truncate">{escape(r['query'])}</div>
            </div>
            <a href="/remote?action=bs_toggle_played&id={r['id']}" class="w-8 h-8 flex items-center justify-center bg-emerald-600 active:bg-emerald-500 text-white rounded font-bold text-xs">✓</a>
        </div>
        """)

    return f"""
    <div class="space-y-2">
        <div class="flex items-center justify-between">
            <h2 class="text-xs font-bold uppercase tracking-wider text-rose-400">Queue ({len(pending)})</h2>
            <button type="button" onclick="promptManualRequest()" class="text-xs text-rose-400 active:underline">+ Add Song</button>
        </div>
        {''.join(items) if items else '<div class="text-slate-500 text-xs text-center py-4">Queue is empty.</div>'}
    </div>
    """

# --- OBS Overlays & Fast Polling ---

def handle_beatsaber_overlay(params):
    theme_key = get_param(params, "theme")
    layout_key = get_param(params, "layout", "full_hud")
    is_api = get_param(params, "api") == "1"

    # Fast JSON Endpoint for browser source polling
    if is_api:
        return json_response(game_state)

    # Stage 3: Live Overlay Browser Source
    if theme_key in OVERLAY_THEMES and layout_key in OVERLAY_LAYOUTS:
        theme = OVERLAY_THEMES[theme_key]
        box_shadow = "none" if theme["glow"] == "none" else f"0 8px 40px {theme['glow']}"
        text_shadow = "none" if theme["glow"] == "none" else f"0 4px 16px {theme['glow']}"

        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>OBS Beat Saber - {escape(layout_key)}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        html, body {{
            width: 100vw; height: 100vh;
            overflow: hidden; background: transparent;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }}
        .overlay-container {{ width: 100%; height: 100%; display: flex; align-items: flex-start; justify-content: flex-start; }}
        .bs-badge {{
            display: flex; align-items: center; gap: 20px;
            height: 96px; background: {theme['bg']};
            border: 3px solid {theme['border']}; border-radius: 20px;
            padding: 0 28px; backdrop-filter: blur(16px);
            box-shadow: {box_shadow}; color: {theme['text_count']};
            text-shadow: {text_shadow};
        }}
        .cover-art {{ width: 64px; height: 64px; border-radius: 12px; object-fit: cover; background: #0f172a; border: 2px solid rgba(255,255,255,0.15); flex-shrink: 0; }}
        .info-col {{ display: flex; flex-direction: column; justify-content: center; min-width: 0; max-width: 420px; }}
        .song-title {{ font-size: 1.6rem; font-weight: 800; color: {theme['text_count']}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; line-height: 1.1; }}
        .song-sub {{ font-size: 1.1rem; font-weight: 600; color: {theme['text_label']}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: 3px; }}
        .stats-col {{ display: flex; align-items: center; gap: 20px; padding-left: 20px; border-left: 2px solid rgba(255,255,255,0.15); flex-shrink: 0; }}
        .stat-item {{ display: flex; flex-direction: column; align-items: center; }}
        .stat-label {{ font-size: 0.9rem; font-weight: 700; color: {theme['text_label']}; text-transform: uppercase; }}
        .stat-value {{ font-size: 1.6rem; font-weight: 800; font-family: monospace; color: {theme['text_count']}; }}
    </style>
    <script>
        let lastCover = "";
        async function updateHUD() {{
            try {{
                const res = await fetch('/obs/beatsaber?api=1');
                if (!res.ok) return;
                const d = await res.json();

                const elTitle  = document.getElementById('song-title');
                const elArtist = document.getElementById('song-artist');
                const elAcc    = document.getElementById('stat-acc');
                const elCombo  = document.getElementById('stat-combo');
                const elMisses = document.getElementById('stat-misses');
                const elCover  = document.getElementById('cover-img');

                if (elTitle) elTitle.innerText = d.song_name || "In Menu";
                if (elArtist) {{
                    let s = d.artist || "—";
                    if (d.mapper) s += " [" + d.mapper + "]";
                    elArtist.innerText = s;
                }}
                if (elAcc) elAcc.innerText = (d.accuracy || 0).toFixed(2) + "%";
                if (elCombo) elCombo.innerText = d.combo || 0;
                if (elMisses) elMisses.innerText = d.misses || 0;

                const c = d.cover_image_b64;
                if (elCover && c && c !== lastCover) {{
                    lastCover = c;
                    elCover.src = c.startsWith("data:") ? c : "data:image/png;base64," + c;
                }}
            }} catch(e) {{}}
        }}
        setInterval(updateHUD, 300);
    </script>
</head>
<body>
    <div class="overlay-container">
        <div class="bs-badge">
            {"<img id='cover-img' class='cover-art' src='data:image/svg+xml;utf8,<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"64\" height=\"64\" fill=\"%231e293b\"/>' alt='Cover' />" if layout_key != 'stats_only' else ""}
            {"<div class='info-col'><div class='song-title' id='song-title'>In Menu</div><div class='song-sub' id='song-artist'>—</div></div>" if layout_key != 'stats_only' else ""}
            {"<div class='stats-col'><div class='stat-item'><span class='stat-label'>Acc</span><span class='stat-value' id='stat-acc'>0.00%</span></div><div class='stat-item'><span class='stat-label'>Combo</span><span class='stat-value' id='stat-combo'>0</span></div><div class='stat-item'><span class='stat-label'>Miss</span><span class='stat-value' style='color:#ef4444;' id='stat-misses'>0</span></div></div>" if layout_key != 'song_card' else ""}
        </div>
    </div>
</body>
</html>"""
        return html_response(html)

    # Stage 2: Pick Layout (Using central item picker helper)
    if theme_key in OVERLAY_THEMES:
        return html_response(render_item_picker(
            base_route="/obs/beatsaber",
            theme_key=theme_key,
            items=OVERLAY_LAYOUTS,
            item_type_label="HUD Layout"
        ))

    # Stage 1: Pick Theme (Using central theme picker helper)
    return html_response(render_theme_picker(
        base_route="/obs/beatsaber",
        title="Select Beat Saber HUD Theme",
        accent_color="rose"
    ))

# --- IRC Commands Handler ---

def handle_chat_command(user: str, command: str, args: str, tags: dict):
    badges = tags.get("badges", "")
    is_mod = "broadcaster/1" in badges or "moderator/1" in badges

    # Public request commands
    if command in ("!bsr", "$"):
        success, msg = add_song_request(user, args)
        print(f"[BeatSaber Queue] {user}: {msg}")

    # Moderator commands
    elif is_mod:
        mod_cfg = load_moderation()
        requests = load_requests()

        if command == "!bsopen":
            mod_cfg["queue_open"] = True
            save_moderation(mod_cfg)
        elif command == "!bsclose":
            mod_cfg["queue_open"] = False
            save_moderation(mod_cfg)
        elif command == "!banuser" and args:
            mod_cfg["banned_users"].append(args.strip().lower())
            save_moderation(mod_cfg)
        elif command == "!clearpast":
            save_requests([r for r in requests if not r.get("played", False)])

# --- In-Game & UI JSON API Endpoints ---

def api_get_queue(params):
    """Called by the in-game Beat Saber mod to display pending tracks."""
    requests = load_requests()
    mod_cfg = load_moderation()
    pending = [r for r in requests if not r.get("played", False)]
    return json_response({
        "queue_open": mod_cfg.get("queue_open", True),
        "total_pending": len(pending),
        "items": pending
    })

def api_action_queue(params):
    """
    Called by in-game VR buttons or mobile clicks:
    /api/bs/action?action=clear&id=123
    Actions: 'play_clear', 'skip', 'ban_song', 'ban_user'
    """
    req_action = get_param(params, "action")
    req_id = int(get_param(params, "id", "0"))
    requests = load_requests()
    mod_cfg = load_moderation()

    target_req = next((r for r in requests if r.get("id") == req_id), None)

    if req_action == "play_clear" and target_req:
        target_req["played"] = True
        save_requests(requests)
        return json_response({"status": "ok", "message": f"Cleared {target_req['song_name']}"})

    elif req_action == "skip" and target_req:
        requests = [r for r in requests if r.get("id") != req_id]
        save_requests(requests)
        return json_response({"status": "ok", "message": "Song skipped"})

    elif req_action == "ban_user" and target_req:
        u = target_req["user"].lower()
        if u not in mod_cfg["banned_users"]:
            mod_cfg["banned_users"].append(u)
            save_moderation(mod_cfg)
        # Drop all requests from this user
        requests = [r for r in requests if r.get("user", "").lower() != u]
        save_requests(requests)
        return json_response({"status": "ok", "message": f"Banned user {u}"})

    elif req_action == "toggle_queue":
        mod_cfg["queue_open"] = not mod_cfg.get("queue_open", True)
        save_moderation(mod_cfg)
        return json_response({"status": "ok", "queue_open": mod_cfg["queue_open"]})

    return json_response({"status": "error", "message": "Invalid action"}, 400)

def handle_beatsaber_vr_queue(params):
    """
    Dedicated lightweight VR view designed for OVR Toolkit / XSOverlay / SteamVR Desktop.
    Point an OVR browser tab to: http://localhost:5000/vr/bsr
    """
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>VR Beat Saber Queue</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body {
            background: #090d16;
            color: #f1f5f9;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            user-select: none;
            -webkit-user-select: none;
        }
        /* Custom thick scrollbars easy to drag with VR pointers */
        ::-webkit-scrollbar { width: 10px; }
        ::-webkit-scrollbar-track { background: #0f172a; }
        ::-webkit-scrollbar-thumb { background: #334155; border-radius: 5px; }
        ::-webkit-scrollbar-thumb:hover { background: #475569; }
    </style>
    <script>
        let isFetching = false;

        async function triggerAction(action, id) {
            try {
                await fetch(`/api/bs/action?action=${action}&id=${id}`);
                loadQueue();
            } catch (err) {
                console.error("Action error:", err);
            }
        }

        async function toggleQueueStatus() {
            try {
                await fetch('/api/bs/action?action=toggle_queue');
                loadQueue();
            } catch (err) {}
        }

        function copyKey(key, btn) {
            navigator.clipboard.writeText(`!bsr ${key}`).then(() => {
                const oldText = btn.innerText;
                btn.innerText = "COPIED!";
                btn.classList.add("bg-emerald-600");
                setTimeout(() => {
                    btn.innerText = oldText;
                    btn.classList.remove("bg-emerald-600");
                }, 1200);
            });
        }

        async function loadQueue() {
            if (isFetching) return;
            isFetching = true;
            try {
                const res = await fetch('/api/bs/queue');
                if (!res.ok) throw new Error("Network error");
                const data = await res.json();

                // Status Bar
                const statusBadge = document.getElementById('queue-status');
                if (data.queue_open) {
                    statusBadge.innerText = "OPEN";
                    statusBadge.className = "px-3 py-1 text-xs font-black uppercase rounded-lg bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 cursor-pointer";
                } else {
                    statusBadge.innerText = "CLOSED";
                    statusBadge.className = "px-3 py-1 text-xs font-black uppercase rounded-lg bg-rose-500/20 text-rose-400 border border-rose-500/40 cursor-pointer";
                }
                document.getElementById('queue-count').innerText = `${data.total_pending} waiting`;

                // Song List
                const container = document.getElementById('queue-container');
                if (!data.items || data.items.length === 0) {
                    container.innerHTML = `
                        <div class="flex flex-col items-center justify-center py-16 text-slate-500 text-sm">
                            <span class="text-2xl mb-1">🎧</span>
                            Queue is empty. Waiting for !bsr requests...
                        </div>`;
                    return;
                }

                container.innerHTML = data.items.map((item, idx) => `
                    <div class="flex items-center justify-between p-3.5 bg-slate-900 border border-slate-800 hover:border-slate-700 rounded-2xl gap-3 transition">
                        <!-- Song Info -->
                        <div class="min-w-0 flex-1">
                            <div class="flex items-center gap-2 mb-1">
                                <span class="font-mono text-xs font-bold text-slate-400">#${idx + 1}</span>
                                <span class="text-xs font-bold text-rose-400 truncate">${escapeHtml(item.user)}</span>
                                <span class="text-[10px] font-mono text-slate-400 bg-slate-950 px-2 py-0.5 rounded border border-slate-800">
                                    ${escapeHtml(item.bsr_key || item.query)}
                                </span>
                            </div>
                            <div class="font-bold text-base text-white truncate leading-tight">
                                ${escapeHtml(item.song_name || item.query)}
                            </div>
                            <div class="text-xs text-slate-400 truncate mt-0.5">
                                ${escapeHtml(item.artist || '—')} <span class="text-slate-500">[${escapeHtml(item.mapper || '—')}]</span>
                            </div>
                        </div>

                        <!-- VR Pointer Actions -->
                        <div class="flex items-center gap-2 shrink-0">
                            <button onclick="copyKey('${item.bsr_key}', this)" class="h-11 px-3 bg-slate-800 active:scale-95 text-slate-200 text-xs font-mono font-bold rounded-xl border border-slate-700 transition">
                                Key
                            </button>
                            <button onclick="triggerAction('play_clear', ${item.id})" class="h-11 px-4 bg-emerald-600 hover:bg-emerald-500 active:scale-95 text-white font-bold text-sm rounded-xl transition">
                                Done ✓
                            </button>
                            <button onclick="triggerAction('skip', ${item.id})" class="h-11 px-3 bg-slate-800 hover:bg-slate-700 active:scale-95 text-slate-300 font-bold text-xs rounded-xl border border-slate-700 transition">
                                Skip ⏭
                            </button>
                            <button onclick="if(confirm('Ban user ${escapeHtml(item.user)}?')) triggerAction('ban_user', ${item.id})" class="h-11 px-3 bg-slate-950 hover:bg-rose-950 text-slate-500 hover:text-rose-400 font-bold text-xs rounded-xl border border-slate-800 transition">
                                Ban 🚫
                            </button>
                        </div>
                    </div>
                `).join('');
            } catch (err) {
                console.error("Poll failure:", err);
            } finally {
                isFetching = false;
            }
        }

        function escapeHtml(str) {
            if (!str) return '';
            return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
        }

        // Live refresh every 1.5s
        setInterval(loadQueue, 1500);
        window.addEventListener('DOMContentLoaded', loadQueue);
    </script>
</head>
<body class="p-4 min-h-screen flex flex-col space-y-4">
    <!-- Header Controls -->
    <header class="flex items-center justify-between bg-slate-900/90 border border-slate-800 p-3.5 rounded-2xl shadow-lg shrink-0">
        <div>
            <h1 class="text-sm font-black tracking-wider text-rose-400 uppercase flex items-center gap-2">
                <span class="w-2.5 h-2.5 rounded-full bg-rose-500 inline-block"></span>
                VR Song Queue
            </h1>
            <p id="queue-count" class="text-xs font-mono text-slate-400 mt-0.5">Loading...</p>
        </div>
        <div class="flex items-center gap-3">
            <button id="queue-status" onclick="toggleQueueStatus()" class="px-3 py-1 text-xs font-bold rounded-lg bg-slate-800 text-slate-400">
                ...
            </button>
            <button onclick="loadQueue()" class="h-9 px-3 bg-slate-800 hover:bg-slate-700 active:scale-95 text-slate-200 text-xs font-bold rounded-xl border border-slate-700">
                Sync ⟳
            </button>
        </div>
    </header>

    <!-- Scrollable Queue List -->
    <main id="queue-container" class="flex-1 space-y-2.5 overflow-y-auto pr-1">
        <!-- Injected via loadQueue() -->
    </main>
</body>
</html>"""
    return html_response(html)

ROUTES = {
    "/vr/bsr": handle_beatsaber_vr_queue,
    "/api/bs/queue": api_get_queue,
    "/api/bs/action": api_action_queue,
    "/obs/beatsaber": handle_beatsaber_overlay
}