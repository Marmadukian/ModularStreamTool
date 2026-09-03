import math
import time
from utils import (
    OVERLAY_THEMES, escape, quote, get_param,
    html_response, json_response, read_json, write_json,
    render_theme_picker, render_item_picker, get_data_path,
    render_obs_overlay
)

MODULE_ID = "urge_surf"
MODULE_NAME = "Urge Surfer"

SURF_FILE = get_data_path("urge_surf_store.json")

SHARED_JS = [
    """
    function promptStartWave() {
        const trigger = prompt("What's triggering the urge? (e.g. Boredom, Snack, Stress, Restless):", "Craving");
        if (trigger === null) return;
        const note = trigger.trim() || "General Urge";
        window.location.search = `?action=surf_start&trigger=${encodeURIComponent(note)}`;
    }
    """
]

DEFAULT_STATE = {
    "is_surfing": False,
    "started_at": 0,
    "current_trigger": "",
    "xp": 0,
    "total_minutes": 0,
    "waves_beaten": 0,
    "history": []
}


# --- Persistence & XP Math ---

def load_data() -> dict:
    data = read_json(SURF_FILE, DEFAULT_STATE)
    # Ensure missing keys get populated if schema grows
    for k, v in DEFAULT_STATE.items():
        if k not in data:
            data[k] = v
    return data


def save_data(data: dict) -> None:
    write_json(SURF_FILE, data)


def calculate_level(xp: int) -> int:
    """Square-root leveling curve: Level = floor(sqrt(xp / 15)) + 1."""
    if xp <= 0:
        return 1
    return int(math.isqrt(xp // 15)) + 1


def get_xp_for_level(lvl: int) -> int:
    """Calculates total cumulative XP needed to hit a given level."""
    if lvl <= 1:
        return 0
    return ((lvl - 1) ** 2) * 15


def get_display_state(data: dict) -> dict:
    now = time.time()
    is_surfing = data.get("is_surfing", False)
    started_at = data.get("started_at", 0)

    elapsed_secs = max(0, int(now - started_at)) if is_surfing else 0
    mins = elapsed_secs // 60
    secs = elapsed_secs % 60
    formatted = f"{mins:02d}:{secs:02d}"

    # Peak wave boundary: typically urges plateau and drop after 10-15 mins
    is_peak_surfed = mins >= 10

    current_lvl = calculate_level(data.get("xp", 0))
    current_lvl_base_xp = get_xp_for_level(current_lvl)
    next_lvl_xp = get_xp_for_level(current_lvl + 1)
    xp_in_level = max(0, data.get("xp", 0) - current_lvl_base_xp)
    xp_needed = max(1, next_lvl_xp - current_lvl_base_xp)
    progress_pct = min(100, int((xp_in_level / xp_needed) * 100))

    return {
        "formatted": formatted,
        "seconds": elapsed_secs,
        "minutes": mins,
        "is_surfing": is_surfing,
        "is_peak_surfed": is_peak_surfed,
        "level": current_lvl,
        "xp": data.get("xp", 0),
        "xp_in_level": xp_in_level,
        "xp_needed": xp_needed,
        "progress_pct": progress_pct,
        "waves_beaten": data.get("waves_beaten", 0),
        "total_minutes": data.get("total_minutes", 0),
        "trigger": data.get("current_trigger", "")
    }


# --- Action Dispatcher ---

def handle_common_commands(params):
    action = get_param(params, "action")
    if not action or not action.startswith("surf_"):
        return

    data = load_data()
    now = time.time()

    if action == "surf_start" and not data.get("is_surfing"):
        trigger = get_param(params, "trigger", "Craving").strip()
        data["is_surfing"] = True
        data["started_at"] = now
        data["current_trigger"] = trigger or "Craving"
        save_data(data)

    elif action == "surf_finish" and data.get("is_surfing"):
        elapsed_secs = max(0, int(now - data.get("started_at", now)))
        mins = elapsed_secs // 60

        # Award base 10 XP per whole minute surfed
        earned_xp = mins * 10

        # Bonus 30 XP for conquering the wave's peak (>= 10 mins)
        if mins >= 10:
            earned_xp += 30
            data["waves_beaten"] = data.get("waves_beaten", 0) + 1

        data["xp"] = data.get("xp", 0) + earned_xp
        data["total_minutes"] = data.get("total_minutes", 0) + mins

        # Append to roll history (capped at 20)
        history_entry = {
            "timestamp": int(now),
            "duration_m": mins,
            "trigger": data.get("current_trigger", ""),
            "xp_earned": earned_xp,
            "beat_peak": mins >= 10
        }
        data.setdefault("history", []).insert(0, history_entry)
        data["history"] = data["history"][:20]

        # Reset active wave
        data["is_surfing"] = False
        data["started_at"] = 0
        data["current_trigger"] = ""
        save_data(data)

    elif action == "surf_cancel" and data.get("is_surfing"):
        data["is_surfing"] = False
        data["started_at"] = 0
        data["current_trigger"] = ""
        save_data(data)

    elif action == "surf_reset_stats":
        data["xp"] = 0
        data["total_minutes"] = 0
        data["waves_beaten"] = 0
        data["history"] = []
        save_data(data)


# --- Widget Renderers ---

def render_dashboard_widget(params):
    data = load_data()
    state = get_display_state(data)

    if state["is_surfing"]:
        status_badge = '<span class="text-[10px] bg-emerald-500/20 text-emerald-300 px-2 py-0.5 rounded border border-emerald-500/30 animate-pulse font-bold">RIDING THE WAVE</span>'
        action_btn = '<a href="/?action=surf_finish" class="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-xs font-bold text-white rounded transition shadow">Wave Broke (Bank XP)</a>'
        cancel_btn = '<a href="/?action=surf_cancel" class="px-2 py-1.5 bg-slate-800 hover:bg-rose-900/60 text-slate-400 hover:text-rose-300 text-xs font-mono rounded border border-slate-700 transition" title="Bail out">✕</a>'
    else:
        status_badge = '<span class="text-[10px] bg-slate-800 text-slate-400 px-2 py-0.5 rounded border border-slate-700 font-bold">CALM WATERS</span>'
        action_btn = '<button type="button" onclick="promptStartWave()" class="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-xs font-bold text-white rounded transition shadow">+ Ride Wave</button>'
        cancel_btn = ""

    trigger_sub = f'<span class="text-xs text-slate-400 font-mono truncate max-w-[150px] inline-block">Trigger: {escape(state["trigger"])}</span>' if state["is_surfing"] else '<span class="text-xs text-slate-500">Ready for next wave</span>'

    return f"""
    <div class="bg-slate-950/60 border border-slate-800 rounded-2xl p-5 space-y-4">
        <div class="flex items-center justify-between border-b border-slate-800 pb-3">
            <div class="flex items-center gap-2">
                <h2 class="text-sm font-bold uppercase tracking-wider text-indigo-400 flex items-center gap-2">
                    Urge Surfer
                    <span class="text-xs bg-indigo-500/20 text-indigo-300 px-2 py-0.5 rounded border border-indigo-500/30 font-mono">LVL {state['level']}</span>
                </h2>
                <a href="/obs/surf_display" target="_blank" class="text-[10px] text-slate-400 hover:text-indigo-300 lowercase font-mono">(+ obs link)</a>
            </div>
            {status_badge}
        </div>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
            <!-- Main Wave Stopwatch / Active Card -->
            <div class="md:col-span-2 bg-slate-900/90 border border-slate-800 rounded-xl p-4 flex flex-col justify-between space-y-3">
                <div class="flex items-center justify-between">
                    <div>{trigger_sub}</div>
                    <div class="flex items-center gap-2">
                        {action_btn}
                        {cancel_btn}
                    </div>
                </div>

                <div class="flex items-center justify-between bg-slate-950 border border-slate-800 rounded-lg p-3 px-4">
                    <div>
                        <div class="text-[10px] text-slate-500 uppercase tracking-widest font-mono">Current Duration</div>
                        <span class="font-mono text-3xl font-black {'text-emerald-400' if state['is_surfing'] else 'text-slate-500'}">
                            {state['formatted']}
                        </span>
                    </div>
                    <div class="text-right">
                        <div class="text-[10px] text-slate-500 uppercase tracking-widest font-mono">Peak Threshold</div>
                        <span class="font-mono text-sm {'text-emerald-300 font-bold' if state['is_peak_surfed'] else 'text-slate-500'}">
                            {'PEAK SURFED (+30 XP)' if state['is_peak_surfed'] else '10m 00s'}
                        </span>
                    </div>
                </div>

                <!-- Level Progress Bar -->
                <div class="space-y-1">
                    <div class="flex justify-between text-[11px] font-mono text-slate-400">
                        <span>XP Progress</span>
                        <span>{state['xp_in_level']} / {state['xp_needed']} XP</span>
                    </div>
                    <div class="w-full bg-slate-950 rounded-full h-2 border border-slate-800 overflow-hidden">
                        <div class="bg-indigo-500 h-full transition-all duration-500" style="width: {state['progress_pct']}%"></div>
                    </div>
                </div>
            </div>

            <!-- Total Stats Panel -->
            <div class="bg-slate-900/90 border border-slate-800 rounded-xl p-4 flex flex-col justify-between space-y-2">
                <span class="text-xs font-bold text-slate-400 uppercase tracking-wider font-mono">Discipline Tally</span>
                <div class="space-y-2 font-mono">
                    <div class="flex justify-between border-b border-slate-800/80 pb-1">
                        <span class="text-xs text-slate-500">Total XP:</span>
                        <span class="text-xs font-bold text-indigo-300">{state['xp']}</span>
                    </div>
                    <div class="flex justify-between border-b border-slate-800/80 pb-1">
                        <span class="text-xs text-slate-500">Total Time:</span>
                        <span class="text-xs font-bold text-slate-200">{state['total_minutes']}m</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-xs text-slate-500">Peaks Conquered:</span>
                        <span class="text-xs font-bold text-emerald-400">{state['waves_beaten']}</span>
                    </div>
                </div>
                <div class="pt-2 text-right">
                    <a href="/obs/surf_display?theme=solar_yellow&mode=status" target="_blank" class="text-[11px] text-slate-500 hover:text-indigo-300 font-mono">Open OBS Layer ↗</a>
                </div>
            </div>
        </div>
    </div>
    """


def render_remote_widget(params):
    data = load_data()
    state = get_display_state(data)

    if state["is_surfing"]:
        controls = f"""
        <div class="flex items-center gap-1 shrink-0">
            <a href="/remote?action=surf_finish" class="px-3 h-10 flex items-center justify-center bg-emerald-600 active:bg-emerald-500 text-white font-bold text-xs rounded shadow">Done (+XP)</a>
            <a href="/remote?action=surf_cancel" class="w-10 h-10 flex items-center justify-center bg-slate-800 active:bg-rose-950 text-slate-400 active:text-rose-300 font-bold text-xs rounded border border-slate-700">✕</a>
        </div>
        """
    else:
        controls = """
        <div class="flex items-center gap-1 shrink-0">
            <a href="/remote?action=surf_start&trigger=Urge" class="px-4 h-10 flex items-center justify-center bg-indigo-600 active:bg-indigo-500 text-white font-bold text-xs rounded shadow">Ride Wave</a>
        </div>
        """

    return f"""
    <div class="space-y-2">
        <div class="flex items-center justify-between">
            <h2 class="text-xs font-bold uppercase tracking-wider text-indigo-400 flex items-center gap-2">
                Urge Surfer
                <span class="text-[10px] bg-indigo-500/20 text-indigo-300 px-1.5 py-0.2 rounded border border-indigo-500/30 font-mono">LVL {state['level']}</span>
            </h2>
            <span class="text-[11px] text-slate-400 font-mono">{state['xp']} XP</span>
        </div>
        <div class="flex items-center justify-between bg-slate-900 border border-slate-800 rounded-xl p-3 shadow-sm">
            <div class="truncate mr-2 flex-1">
                <span class="text-sm font-bold text-white truncate block">
                    {'Riding Wave' if state['is_surfing'] else 'Standing By'}
                </span>
                <span class="text-xs font-mono {'text-emerald-400 font-bold animate-pulse' if state['is_surfing'] else 'text-slate-500'}">
                    {state['formatted'] if state['is_surfing'] else f"{state['waves_beaten']} peaks surfed"}
                </span>
            </div>
            {controls}
        </div>
    </div>
    """


# --- OBS Overlays & Fast Polling ---

def handle_obs_overlay(params):
    theme_key = get_param(params, "theme")
    mode = get_param(params, "mode", "status")
    is_api = get_param(params, "api") == "1"
    data = load_data()
    state = get_display_state(data)

    # Fast JSON Polling
    if is_api:
        return json_response({
            "level": state["level"],
            "xp": state["xp"],
            "formatted": state["formatted"],
            "is_surfing": state["is_surfing"],
            "is_peak_surfed": state["is_peak_surfed"],
            "waves_beaten": state["waves_beaten"]
        })

    # Stage 3: Transparent OBS Browser Source
    if theme_key in OVERLAY_THEMES:
        val_text = state["formatted"] if state["is_surfing"] else f"LVL {state['level']}"
        sub_text = "SURFING" if state["is_surfing"] else f"{state['waves_beaten']} CONQUERED"

        html = render_obs_overlay(
            title="Urge Surfer Overlay",
            theme_key=theme_key,
            inner_html=f"""
            <span class="obs-label text-base truncate ml-5" id="obs-status">{sub_text}</span>
            <span class="obs-val text-3xl mr-5 ml-auto font-mono" id="display-val">{val_text}</span>
            """,
            poll_endpoint="/obs/surf_display?api=1",
            poll_js="""
            const val = document.getElementById('display-val');
            const status = document.getElementById('obs-status');
            if (data.is_surfing) {
                val.innerText = data.formatted;
                status.innerText = data.is_peak_surfed ? 'PEAK CONQUERED' : 'SURFING WAVE';
                val.classList.add('text-emerald-400');
            } else {
                val.innerText = 'LVL ' + data.level;
                status.innerText = data.waves_beaten + ' PEAKS CONQUERED';
                val.classList.remove('text-emerald-400');
            }
            """
        )
        return html_response(html)

    # Stage 2: Pick Mode
    if theme_key:
        items = {
            "status": f"Level {state['level']} (XP: {state['xp']} | Surfed: {state['waves_beaten']})"
        }
        return html_response(render_item_picker(
            base_route="/obs/surf_display",
            theme_key=theme_key,
            items=items,
            item_type_label="Display"
        ))

    # Stage 1: Pick Theme
    return html_response(render_theme_picker(
        base_route="/obs/surf_display",
        title="Select Urge Surfer Theme",
        accent_color="indigo"
    ))


ROUTES = {
    "/obs/surf_display": handle_obs_overlay
}