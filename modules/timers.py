import re
import time
from utils import (
    OVERLAY_THEMES, escape, quote, get_param,
    html_response, json_response, read_json, write_json,
    render_theme_picker, render_item_picker, get_data_path
)

MODULE_ID = "timers"
MODULE_NAME = "Stream Timers & Stopwatches"

TIMERS_FILE = get_data_path("timers_store.json")

SHARED_JS = [
    """
    function promptCreateTimer() {
        const name = prompt("Timer name (e.g., Speedrun, Subathon, Break):");
        if (!name || !name.trim()) return;
        const mode = confirm("Click OK for COUNTDOWN, or Cancel for COUNT UP (Stopwatch)") ? "down" : "up";
        let duration = 0;
        if (mode === "down") {
            const mins = prompt("Countdown minutes:", "10");
            duration = (parseInt(mins, 10) || 10) * 60;
        }
        window.location.search = `?action=timer_create&name=${encodeURIComponent(name.trim())}&mode=${mode}&duration=${duration}`;
    }

    function promptAdjustTimer(name) {
        const delta = prompt(`Add/subtract seconds for "${name}" (e.g. 60 or -30):`, "60");
        if (delta && !isNaN(parseInt(delta, 10))) {
            window.location.search = `?action=timer_adjust&name=${encodeURIComponent(name)}&delta=${parseInt(delta, 10)}`;
        }
    }
    """
]


# --- Persistence & Time Math ---

def load_timers() -> dict:
    return read_json(TIMERS_FILE, {})


def save_timers(data: dict) -> None:
    write_json(TIMERS_FILE, data)


def get_timer_display_state(t: dict) -> dict:
    """
    Calculates remaining/elapsed time on the fly based on UTC timestamps.
    Modes:
      'down': counts down from 'duration' to 0.
      'up': counts up from 0 (or elapsed offset).
    """
    now = time.time()
    mode = t.get("mode", "up")
    running = t.get("running", False)
    duration = t.get("duration", 0)  # total target seconds for countdowns
    accumulated = t.get("accumulated", 0)  # accumulated elapsed seconds while running
    started_at = t.get("started_at", 0)

    if running:
        current_run = now - started_at
        total_elapsed = accumulated + current_run
    else:
        total_elapsed = accumulated

    if mode == "down":
        remaining = max(0, duration - total_elapsed)
        seconds_val = int(remaining)
        is_complete = (remaining <= 0)
    else:
        seconds_val = int(total_elapsed)
        is_complete = False

    # Format HH:MM:SS or MM:SS
    hrs = seconds_val // 3600
    mins = (seconds_val % 3600) // 60
    secs = seconds_val % 60

    if hrs > 0:
        formatted = f"{hrs:02d}:{mins:02d}:{secs:02d}"
    else:
        formatted = f"{mins:02d}:{secs:02d}"

    return {
        "formatted": formatted,
        "seconds": seconds_val,
        "running": running,
        "mode": mode,
        "is_complete": is_complete
    }


# --- Action Dispatcher ---

def handle_common_commands(params):
    action = get_param(params, "action")
    if not action or not action.startswith("timer_"):
        return

    name = get_param(params, "name").strip()
    timers = load_timers()
    now = time.time()

    if action == "timer_create" and name:
        mode = get_param(params, "mode", "up")
        duration = int(get_param(params, "duration", "0"))
        timers[name] = {
            "mode": mode,
            "duration": duration,
            "accumulated": 0,
            "started_at": 0,
            "running": False
        }
        save_timers(timers)

    elif action == "timer_start" and name in timers:
        t = timers[name]
        if not t.get("running", False):
            t["running"] = True
            t["started_at"] = now
            save_timers(timers)

    elif action == "timer_pause" and name in timers:
        t = timers[name]
        if t.get("running", False):
            t["accumulated"] += (now - t["started_at"])
            t["running"] = False
            t["started_at"] = 0
            save_timers(timers)

    elif action == "timer_reset" and name in timers:
        t = timers[name]
        t["running"] = False
        t["accumulated"] = 0
        t["started_at"] = 0
        save_timers(timers)

    elif action == "timer_adjust" and name in timers:
        delta = int(get_param(params, "delta", "0"))
        t = timers[name]
        # Adding time to countdown increases duration; on stopwatch, subtracts accumulated
        if t.get("mode") == "down":
            t["duration"] = max(0, t.get("duration", 0) + delta)
        else:
            t["accumulated"] = max(0, t.get("accumulated", 0) + delta)
        save_timers(timers)

    elif action == "timer_delete" and name in timers:
        del timers[name]
        save_timers(timers)


# --- Widget Renderers ---

def render_dashboard_widget(params):
    timers = load_timers()
    cards = []

    for name, t in sorted(timers.items()):
        qname = quote(name)
        state = get_timer_display_state(t)

        mode_badge = (
            '<span class="text-[10px] bg-amber-500/20 text-amber-300 px-1.5 py-0.5 rounded border border-amber-500/30">DOWN</span>'
            if t.get("mode") == "down"
            else '<span class="text-[10px] bg-cyan-500/20 text-cyan-300 px-1.5 py-0.5 rounded border border-cyan-500/30">UP</span>'
        )

        status_class = "text-emerald-400" if state["running"] else "text-slate-400"
        if state["is_complete"]:
            status_class = "text-rose-400 animate-pulse"

        play_pause_btn = (
            f'<a href="/?action=timer_pause&name={qname}" class="px-3 py-1 bg-amber-600 hover:bg-amber-500 text-xs font-bold text-white rounded">Pause</a>'
            if state["running"]
            else f'<a href="/?action=timer_start&name={qname}" class="px-3 py-1 bg-emerald-600 hover:bg-emerald-500 text-xs font-bold text-white rounded">Start</a>'
        )

        cards.append(f"""
        <div class="bg-slate-900/90 border border-slate-800 hover:border-slate-700 rounded-xl p-4 shadow-sm space-y-3">
            <div class="flex items-center justify-between">
                <div class="flex items-center gap-2 min-w-0 mr-2">
                    <span class="font-bold text-slate-200 text-sm truncate">{escape(name)}</span>
                    {mode_badge}
                </div>
                <div class="flex items-center gap-2">
                    <a href="/obs/timer_display?theme=solar_yellow&name={qname}" target="_blank" class="text-[11px] text-slate-400 hover:text-amber-300 font-mono">OBS ↗</a>
                    <a href="/?action=timer_delete&name={qname}" onclick="return confirm('Delete timer: {escape(name)}?');" class="text-slate-600 hover:text-rose-400 text-xs font-mono">✕</a>
                </div>
            </div>

            <div class="flex items-center justify-between bg-slate-950 border border-slate-800 rounded-lg p-2 px-3">
                <span class="font-mono text-2xl font-black {status_class}" id="timer-val-{qname}">{state['formatted']}</span>
                <div class="flex items-center gap-1.5">
                    {play_pause_btn}
                    <a href="/?action=timer_reset&name={qname}" class="px-2 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-bold rounded border border-slate-700">↺</a>
                    <button type="button" onclick="promptAdjustTimer('{escape(name)}')" class="px-2 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-bold rounded border border-slate-700" title="Adjust seconds">±</button>
                </div>
            </div>
        </div>
        """)

    grid = "".join(
        cards) if cards else '<div class="col-span-full text-center text-slate-500 text-xs py-8">No active timers. Click below to add one.</div>'

    return f"""
    <div class="bg-slate-950/60 border border-slate-800 rounded-2xl p-5 space-y-4">
        <div class="flex items-center justify-between border-b border-slate-800 pb-3">
            <div>
                <h2 class="text-sm font-bold uppercase tracking-wider text-amber-400 flex items-center gap-2">
                    Active Timers & Clocks
                    <a href="/obs/timer_display" target="_blank" class="text-[10px] text-slate-400 hover:text-amber-300 lowercase font-mono">(+ obs links)</a>
                </h2>
            </div>
            <button type="button" onclick="promptCreateTimer()" class="bg-amber-600 hover:bg-amber-500 text-white font-bold text-xs px-3 py-1.5 rounded-lg transition">
                + New Timer
            </button>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
            {grid}
        </div>
    </div>
    """


def render_remote_widget(params):
    timers = load_timers()
    rows = []

    for name, t in sorted(timers.items()):
        qname = quote(name)
        state = get_timer_display_state(t)

        play_pause_btn = (
            f'<a href="/remote?action=timer_pause&name={qname}" class="w-12 h-10 flex items-center justify-center bg-amber-600 active:bg-amber-500 text-white font-bold text-xs rounded">||</a>'
            if state["running"]
            else f'<a href="/remote?action=timer_start&name={qname}" class="w-12 h-10 flex items-center justify-center bg-emerald-600 active:bg-emerald-500 text-white font-bold text-xs rounded">▶</a>'
        )

        rows.append(f"""
        <div class="flex items-center justify-between bg-slate-900 border border-slate-800 rounded-xl p-3 shadow-sm">
            <div class="truncate mr-2 flex-1">
                <span class="text-sm font-bold text-white truncate block">{escape(name)}</span>
                <span class="text-xs font-mono {'text-emerald-400 font-bold' if state['running'] else 'text-slate-400'}">{state['formatted']}</span>
            </div>
            <div class="flex items-center gap-1 shrink-0">
                {play_pause_btn}
                <a href="/remote?action=timer_reset&name={qname}" class="w-10 h-10 flex items-center justify-center bg-slate-800 active:bg-slate-700 text-slate-300 font-bold text-sm rounded border border-slate-700">↺</a>
                <a href="/remote?action=timer_adjust&name={qname}&delta=60" class="w-10 h-10 flex items-center justify-center bg-slate-800 active:bg-slate-700 text-slate-300 font-mono text-xs rounded border border-slate-700">+1m</a>
            </div>
        </div>
        """)

    return f"""
    <div class="space-y-2">
        <div class="flex items-center justify-between">
            <h2 class="text-xs font-bold uppercase tracking-wider text-amber-400">Timers</h2>
            <button type="button" onclick="promptCreateTimer()" class="text-xs text-amber-400 active:underline">+ Add</button>
        </div>
        {''.join(rows) if rows else '<div class="text-slate-500 text-xs text-center py-4">No active timers.</div>'}
    </div>
    """


# --- OBS Overlays & Fast Polling ---

def handle_obs_overlay(params):
    theme_key = get_param(params, "theme")
    target_name = get_param(params, "name")
    is_api = get_param(params, "api") == "1"
    timers = load_timers()

    # Fast JSON Polling
    if is_api and target_name:
        t = timers.get(target_name, {})
        state = get_timer_display_state(t)
        return json_response({"name": target_name, "formatted": state["formatted"], "complete": state["is_complete"]})

    # Stage 3: Transparent OBS Browser Source
    if theme_key in OVERLAY_THEMES and target_name:
        theme = OVERLAY_THEMES[theme_key]
        state = get_timer_display_state(timers.get(target_name, {}))
        qname = quote(target_name)
        box_shadow = "none" if theme["glow"] == "none" else f"0 4px 20px {theme['glow']}"
        text_shadow = "none" if theme["glow"] == "none" else f"0 0 12px {theme['glow']}"

        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>OBS Timer - {escape(target_name)}</title>
    <style>
        body {{ background: transparent; overflow: hidden; display: flex; height: 100vh; align-items: center; justify-content: center; margin: 0; }}
        .badge {{ display: flex; align-items: center; gap: 16px; height: 56px; background: {theme['bg']}; border: 2px solid {theme['border']}; border-radius: 12px; padding: 0 20px; box-shadow: {box_shadow}; }}
        .label {{ font-family: sans-serif; font-size: 1.15rem; font-weight: 800; color: {theme['text_label']}; text-transform: uppercase; }}
        .val {{ font-family: monospace; font-size: 2rem; font-weight: 900; color: {theme['text_count']}; text-shadow: {text_shadow}; min-width: 90px; text-align: right; }}
        .pulse {{ animation: p 1s infinite alternate; }}
        @keyframes p {{ from {{ opacity: 1; }} to {{ opacity: 0.4; }} }}
    </style>
    <script>
        setInterval(async () => {{
            try {{
                const res = await fetch('/obs/timer_display?api=1&name={qname}');
                if (res.ok) {{
                    const d = await res.json();
                    const el = document.getElementById('display-val');
                    el.innerText = d.formatted;
                    el.classList.toggle('pulse', !!d.complete);
                }}
            }} catch(e) {{}}
        }}, 300);
    </script>
</head>
<body>
    <div class="badge"><span class="label">{escape(target_name)}</span><span class="val" id="display-val">{state['formatted']}</span></div>
</body>
</html>"""
        return html_response(html)

    # Stage 2: Pick Timer
    if theme_key in OVERLAY_THEMES:
        items_preview = {name: get_timer_display_state(t)["formatted"] for name, t in timers.items()}
        return html_response(render_item_picker(
            base_route="/obs/timer_display",
            theme_key=theme_key,
            items=items_preview,
            item_type_label="Timer"
        ))

    # Stage 1: Pick Theme
    return html_response(render_theme_picker(
        base_route="/obs/timer_display",
        title="Select Timer Overlay Theme",
        accent_color="amber"
    ))

def _parse_duration_to_seconds(time_str: str) -> int:
    """Parses plain integers or strings like '10m', '1h30m', '45s' into total seconds."""
    time_str = time_str.strip().lower()
    if time_str.isdigit():
        return int(time_str)

    total_seconds = 0
    pattern = r'(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+)\s*s)?'
    match = re.fullmatch(pattern, time_str)
    if match and any(match.groups()):
        h, m, s = match.groups()
        if h: total_seconds += int(h) * 3600
        if m: total_seconds += int(m) * 60
        if s: total_seconds += int(s)
        return total_seconds
    return 0


def handle_chat_command(user: str, command: str, args: str, tags: dict):
    # Restrict to broadcaster and moderators
    badges = tags.get("badges", "")
    is_admin = "broadcaster/1" in badges or "moderator/1" in badges
    if not is_admin:
        return

    # Valid commands: !timer, !t
    if command not in ("!timer", "!t"):
        return

    raw = args.strip()
    if not raw:
        return

    tokens = raw.split()
    if len(tokens) < 2:
        return

    subcommand = tokens[0].lower()
    rest = tokens[1:]

    timers = load_timers()
    now = time.time()

    def find_timer_name(candidate_name: str):
        """Case-insensitive matching for already named timers."""
        c_clean = candidate_name.strip().lower()
        for existing in timers:
            if existing.lower() == c_clean:
                return existing
        return None

    # 1. START: !timer start <Name>
    if subcommand in ("start", "resume", "play"):
        target_name = " ".join(rest)
        name = find_timer_name(target_name)
        if name and not timers[name].get("running", False):
            timers[name]["running"] = True
            timers[name]["started_at"] = now
            save_timers(timers)
            print(f"[Timer] '{name}' started by {user}")

    # 2. STOP / PAUSE: !timer stop <Name>
    elif subcommand in ("stop", "pause"):
        target_name = " ".join(rest)
        name = find_timer_name(target_name)
        if name and timers[name].get("running", False):
            timers[name]["accumulated"] += (now - timers[name]["started_at"])
            timers[name]["running"] = False
            timers[name]["started_at"] = 0
            save_timers(timers)
            print(f"[Timer] '{name}' paused by {user}")

    # 3. RESET: !timer reset <Name>
    elif subcommand == "reset":
        target_name = " ".join(rest)
        name = find_timer_name(target_name)
        if name:
            timers[name]["running"] = False
            timers[name]["accumulated"] = 0
            timers[name]["started_at"] = 0
            save_timers(timers)
            print(f"[Timer] '{name}' reset by {user}")

    # 4. SWITCH MODE: !timer mode <up|down> <Name> [optional: initial_time]
    elif subcommand in ("mode", "setmode"):
        if len(rest) < 2:
            return
        new_mode = rest[0].lower()
        if new_mode not in ("up", "down"):
            return

        # Check if the final parameter is an optional initial duration
        possible_time = _parse_duration_to_seconds(rest[-1])
        has_time_override = (possible_time > 0 or rest[-1] in ("0", "0s", "0m")) and len(rest) > 2

        if has_time_override:
            target_name = " ".join(rest[1:-1])
            initial_time = possible_time
        else:
            target_name = " ".join(rest[1:])
            initial_time = None

        name = find_timer_name(target_name)
        if name:
            t = timers[name]
            t["mode"] = new_mode

            # If an initial time was supplied, reset accumulated/duration to it
            if initial_time is not None:
                if new_mode == "down":
                    t["duration"] = initial_time
                    t["accumulated"] = 0
                else:
                    t["accumulated"] = initial_time
                if t.get("running"):
                    t["started_at"] = now

            save_timers(timers)
            print(f"[Timer] '{name}' mode set to {new_mode.upper()} by {user}")

    # 5. SET INITIAL TIME: !timer set <Name> <time>
    elif subcommand == "set":
        if len(rest) < 2:
            return
        parsed_secs = _parse_duration_to_seconds(rest[-1])
        target_name = " ".join(rest[:-1])
        name = find_timer_name(target_name)

        if name:
            t = timers[name]
            if t.get("mode") == "down":
                t["duration"] = parsed_secs
                t["accumulated"] = 0
            else:
                t["accumulated"] = parsed_secs

            if t.get("running"):
                t["started_at"] = now

            save_timers(timers)
            print(f"[Timer] '{name}' time set to {parsed_secs}s by {user}")



ROUTES = {
    "/obs/timer_display": handle_obs_overlay
}