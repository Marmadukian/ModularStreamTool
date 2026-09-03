import math
from datetime import datetime, date

from modules.counters import SHARED_JS
from utils import (
    OVERLAY_THEMES, escape, quote, get_param,
    html_response, json_response, read_json, write_json,
    render_theme_picker, render_item_picker, get_data_path,
    render_obs_overlay
)


MODULE_ID = "percent_sober"
MODULE_NAME = "Sober Days Percentage"

DATA_FILE = get_data_path("agency_store.json")

DEFAULT_STATE = {
    "start_date": "20260901",  # YYYYMMDD
    "target_pct": 85.0,  # Default baseline goal
    "intake_dates": []  # List of YYYYMMDD strings
}

SHARED_JS = [
    """
    function promptSetAnchor() {
        const current = "YYYYMMDD";
        const d = prompt("Set Season Start Anchor (YYYYMMDD):", current);
        if (d && /^\d{8}$/.test(d.trim())) {
            window.location.search = `?action=agency_set_anchor&date=${encodeURIComponent(d.trim())}`;
        }
    }

    function promptSetGoal() {
        const g = prompt("Set Target Agency % (e.g. 85, 90):", "90");
        if (g && !isNaN(parseFloat(g))) {
            window.location.search = `?action=agency_set_goal&goal=${encodeURIComponent(g.trim())}`;
        }
    }
    """
]


def load_agency_data() -> dict:
    return read_json(DATA_FILE, DEFAULT_STATE)


def save_agency_data(data: dict) -> None:
    write_json(DATA_FILE, data)


def parse_ymd(ymd_str: str) -> date:
    return datetime.strptime(ymd_str, "%Y%m%d").date()


def get_agency_stats(data: dict) -> dict:
    today = date.today()
    try:
        start_d = parse_ymd(data.get("start_date", today.strftime("%Y%m%d")))
    except ValueError:
        start_d = today

    # Cap calculation from start date forward
    total_days = max(1, (today - start_d).days + 1)

    # Filter intake dates to only those occurring on or after start_date
    valid_intake = set()
    for d_str in data.get("intake_dates", []):
        try:
            d = parse_ymd(d_str)
            if d >= start_d and d <= today:
                valid_intake.add(d_str)
        except ValueError:
            continue

    intake_count = len(valid_intake)
    sober_days = max(0, total_days - intake_count)
    pct = (sober_days / total_days) * 100.0
    goal = float(data.get("target_pct", 85.0))

    # Determine loot tier & style classes
    if pct >= 100.0:
        tier_name = "MYTHIC FLAWLESS"
        badge_style = "bg-yellow-400/20 text-yellow-300 border-yellow-400/60 shadow-[0_0_12px_rgba(250,204,21,0.4)]"
        bar_color = "bg-yellow-400"
    elif pct >= 90.0:
        tier_name = "EXALTED EPIC"
        badge_style = "bg-fuchsia-500/20 text-fuchsia-300 border-fuchsia-400/60 shadow-[0_0_12px_rgba(217,70,239,0.4)]"
        bar_color = "bg-fuchsia-500"
    elif pct >= goal:
        tier_name = "TARGET SECURED"
        badge_style = "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
        bar_color = "bg-emerald-500"
    elif pct >= (goal - 5.0):
        tier_name = "ARMOR DAMAGED"
        badge_style = "bg-amber-500/20 text-amber-300 border-amber-500/40"
        bar_color = "bg-amber-500"
    else:
        tier_name = "CRITICAL RECOVERY"
        badge_style = "bg-slate-800 text-slate-400 border-slate-700"
        bar_color = "bg-slate-700"

    # Headroom vs Recovery Math
    target_ratio = goal / 100.0
    if pct >= goal:
        # How many consecutive off-days allowed before slipping under goal
        cushion = math.floor((sober_days / target_ratio) - total_days)
        mission_text = f"+{cushion}d Shield Buffer" if cushion > 0 else "On the wire"
    else:
        # Days needed to pull back up to goal
        days_needed = math.ceil((target_ratio * total_days - sober_days) / (1.0 - target_ratio))
        mission_text = f"Quest: {days_needed}d to hit {int(goal)}%"

    return {
        "pct": round(pct, 1),
        "sober_days": sober_days,
        "total_days": total_days,
        "goal": goal,
        "tier_name": tier_name,
        "badge_style": badge_style,
        "bar_color": bar_color,
        "mission_text": mission_text,
        "start_date": data.get("start_date")
    }

def handle_common_commands(params):
    action = get_param(params, "action")
    if not action or not action.startswith("agency_"):
        return

    data = load_agency_data()
    today_str = date.today().strftime("%Y%m%d")

    # Set Season Anchor Date
    if action == "agency_set_anchor":
        raw_date = get_param(params, "date", "").strip()
        try:
            # Validate format
            parse_ymd(raw_date)
            data["start_date"] = raw_date
            save_agency_data(data)
        except ValueError:
            pass

    # Adjust Target Percentage Goal
    elif action == "agency_set_goal":
        goal = float(get_param(params, "goal", "85"))
        data["target_pct"] = max(50.0, min(100.0, goal))
        save_agency_data(data)

    # Log Intake for Today (Toggles intake date)
    elif action == "agency_toggle_today":
        intakes = set(data.get("intake_dates", []))
        if today_str in intakes:
            intakes.remove(today_str)
        else:
            intakes.add(today_str)
        data["intake_dates"] = sorted(list(intakes))
        save_agency_data(data)


# --- Widget Renderers ---

def render_dashboard_widget(params):
    data = load_agency_data()
    stats = get_agency_stats(data)
    today_str = date.today().strftime("%Y%m%d")
    intake_set = set(data.get("intake_dates", []))
    logged_today = today_str in intake_set

    # Today's quick toggle state
    today_btn = (
        '<a href="/?action=agency_toggle_today" class="px-3 py-1.5 bg-rose-950/80 hover:bg-rose-900 text-rose-300 border border-rose-800 text-xs font-bold rounded-lg transition">Logged Intake Today (Click to Undo)</a>'
        if logged_today
        else '<a href="/?action=agency_toggle_today" class="px-3 py-1.5 bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-700 text-xs font-bold rounded-lg transition">+ Log Intake Today</a>'
    )

    return f"""
    <div class="bg-slate-950/60 border border-slate-800 rounded-2xl p-5 space-y-4">
        <div class="flex items-center justify-between border-b border-slate-800 pb-3">
            <div class="flex items-center gap-2">
                <h2 class="text-sm font-bold uppercase tracking-wider text-slate-200 flex items-center gap-2 font-mono">
                    Agency & Uptime SLA
                </h2>
                <a href="/obs/agency_display" target="_blank" class="text-[10px] text-slate-400 hover:text-slate-200 lowercase font-mono">(+ obs link)</a>
            </div>
            <div class="flex items-center gap-2">
                <span class="text-[10px] px-2 py-0.5 rounded border font-mono font-bold {stats['badge_style']}">
                    {stats['tier_name']}
                </span>
            </div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
            <!-- Main Percent / Status Gauge -->
            <div class="md:col-span-2 bg-slate-900/90 border border-slate-800 rounded-xl p-4 flex flex-col justify-between space-y-4">
                <div class="flex items-center justify-between">
                    <div class="text-xs font-mono text-slate-400">
                        Anchor: <button type="button" onclick="promptSetAnchor()" class="text-slate-200 hover:underline font-bold">{escape(stats['start_date'])}</button>
                        <span class="mx-1 text-slate-600">|</span>
                        Goal: <button type="button" onclick="promptSetGoal()" class="text-slate-200 hover:underline font-bold">{int(stats['goal'])}%</button>
                    </div>
                    {today_btn}
                </div>

                <div class="flex items-baseline justify-between bg-slate-950 border border-slate-800 rounded-lg p-3 px-4">
                    <div>
                        <div class="text-[10px] text-slate-500 uppercase tracking-widest font-mono">Uptime Compliance</div>
                        <span class="font-mono text-4xl font-black text-white">
                            {stats['pct']}%
                        </span>
                    </div>
                    <div class="text-right">
                        <div class="text-[10px] text-slate-500 uppercase tracking-widest font-mono">Active Target</div>
                        <span class="font-mono text-sm font-bold text-slate-300">
                            {stats['mission_text']}
                        </span>
                    </div>
                </div>

                <!-- Compliance Progress Bar -->
                <div class="space-y-1">
                    <div class="flex justify-between text-[11px] font-mono text-slate-400">
                        <span>{stats['sober_days']} of {stats['total_days']} Days Clear</span>
                        <span>Threshold: {int(stats['goal'])}%</span>
                    </div>
                    <div class="w-full bg-slate-950 rounded-full h-2.5 border border-slate-800 overflow-hidden">
                        <div class="{stats['bar_color']} h-full transition-all duration-500" style="width: {stats['pct']}%"></div>
                    </div>
                </div>
            </div>

            <!-- Season / Buffer Stats -->
            <div class="bg-slate-900/90 border border-slate-800 rounded-xl p-4 flex flex-col justify-between space-y-2">
                <span class="text-xs font-bold text-slate-400 uppercase tracking-wider font-mono">Telemetry Buffer</span>
                <div class="space-y-2 font-mono text-xs">
                    <div class="flex justify-between border-b border-slate-800/80 pb-1.5">
                        <span class="text-slate-500">Season Span:</span>
                        <span class="font-bold text-slate-200">{stats['total_days']} Days</span>
                    </div>
                    <div class="flex justify-between border-b border-slate-800/80 pb-1.5">
                        <span class="text-slate-500">Intake Logged:</span>
                        <span class="font-bold text-slate-400">{stats['total_days'] - stats['sober_days']} Days</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-slate-500">Shield Status:</span>
                        <span class="font-bold text-slate-200">{stats['mission_text']}</span>
                    </div>
                </div>
                <div class="pt-2 flex justify-between items-center text-[11px] font-mono">
                    <button type="button" onclick="promptSetAnchor()" class="text-slate-500 hover:text-slate-300">Reset Anchor</button>
                    <a href="/obs/agency_display?theme=solar_yellow" target="_blank" class="text-slate-400 hover:text-amber-300">OBS ↗</a>
                </div>
            </div>
        </div>
    </div>
    """


def render_remote_widget(params):
    data = load_agency_data()
    stats = get_agency_stats(data)
    today_str = date.today().strftime("%Y%m%d")
    intake_set = set(data.get("intake_dates", []))
    logged_today = today_str in intake_set

    log_action_btn = (
        '<a href="/remote?action=agency_toggle_today" class="h-10 px-3 flex items-center justify-center bg-rose-900/80 active:bg-rose-800 text-rose-200 font-bold text-xs rounded border border-rose-700">Undo Log</a>'
        if logged_today
        else '<a href="/remote?action=agency_toggle_today" class="h-10 px-3 flex items-center justify-center bg-slate-800 active:bg-slate-700 text-slate-200 font-bold text-xs rounded border border-slate-700">+ Log Day</a>'
    )

    return f"""
    <div class="space-y-2">
        <div class="flex items-center justify-between">
            <h2 class="text-xs font-bold uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
                Agency SLA
                <span class="text-[10px] px-1.5 py-0.2 rounded border font-mono font-bold {stats['badge_style']}">
                    {stats['pct']}%
                </span>
            </h2>
            <span class="text-[11px] text-slate-400 font-mono">{stats['mission_text']}</span>
        </div>
        <div class="flex items-center justify-between bg-slate-900 border border-slate-800 rounded-xl p-3 shadow-sm">
            <div class="truncate mr-2 flex-1">
                <div class="flex items-center gap-2">
                    <span class="text-sm font-bold font-mono text-white">{stats['sober_days']}/{stats['total_days']}d</span>
                    <span class="text-xs text-slate-500 font-mono">({stats['tier_name']})</span>
                </div>
                <span class="text-[11px] text-slate-400 font-mono block truncate">
                    Goal: {int(stats['goal'])}% | Start: {escape(stats['start_date'])}
                </span>
            </div>
            <div class="shrink-0 flex items-center gap-1">
                {log_action_btn}
            </div>
        </div>
    </div>
    """


# --- OBS Overlays & Fast Polling ---

def handle_obs_overlay(params):
    theme_key = get_param(params, "theme")
    mode = get_param(params, "mode", "uptime")
    is_api = get_param(params, "api") == "1"

    data = load_agency_data()
    stats = get_agency_stats(data)

    # Fast JSON Polling
    if is_api:
        return json_response({
            "pct": stats["pct"],
            "tier_name": stats["tier_name"],
            "mission_text": stats["mission_text"],
            "bar_color": stats["bar_color"],
            "sober_days": stats["sober_days"],
            "total_days": stats["total_days"]
        })

    # Stage 3: Transparent OBS Browser Source
    if theme_key in OVERLAY_THEMES:
        val_text = f"{stats['pct']}%"
        sub_text = stats["tier_name"]

        html = render_obs_overlay(
            title="Agency SLA Overlay",
            theme_key=theme_key,
            inner_html=f"""
            <div class="flex items-center w-full justify-between px-4">
                <div class="flex flex-col min-w-0">
                    <span class="obs-label text-xs uppercase tracking-widest font-mono text-slate-400" id="obs-tier">{sub_text}</span>
                    <span class="text-[11px] font-mono text-slate-500 truncate" id="obs-sub">{stats['mission_text']}</span>
                </div>
                <div class="flex items-baseline gap-1 ml-auto">
                    <span class="obs-val text-3xl font-black font-mono" id="display-val">{val_text}</span>
                </div>
            </div>
            """,
            poll_endpoint="/obs/agency_display?api=1",
            poll_js="""
            const val = document.getElementById('display-val');
            const tier = document.getElementById('obs-tier');
            const sub = document.getElementById('obs-sub');
            if (val && tier && sub) {
                val.innerText = data.pct + '%';
                tier.innerText = data.tier_name;
                sub.innerText = data.mission_text;
            }
            """
        )
        return html_response(html)

    # Stage 2: Pick Mode / Metric Display
    if theme_key:
        items = {
            "uptime": f"Compliance SLA ({stats['pct']}% - {stats['tier_name']})",
            "telemetry": f"Tally ({stats['sober_days']}/{stats['total_days']} Days)"
        }
        return html_response(render_item_picker(
            base_route="/obs/agency_display",
            theme_key=theme_key,
            items=items,
            item_type_label="Display Mode"
        ))

    # Stage 1: Pick Theme
    return html_response(render_theme_picker(
        base_route="/obs/agency_display",
        title="Select Agency Overlay Theme",
        accent_color="indigo"
    ))


ROUTES = {
    "/obs/agency_display": handle_obs_overlay
}