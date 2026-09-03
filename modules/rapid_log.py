import os
import re
import time
import uuid
from datetime import datetime
from utils import (
    BASE_DIR, read_json, write_json, escape, quote, get_param,
    json_response, html_response, normalize_energy_key,
    ENERGY_PROFILES, DEFAULT_ENERGY, set_page_header_hook
)
from modules.vault_manager import save_vault_task, get_vault_tree, TASK_TYPES, BLOCK_TYPES, STATUS_TYPES

MODULE_ID = "rapid_log"
MODULE_NAME = "End of Day Review"

BUJO_DIR = os.path.join(BASE_DIR, "Vault", "BuJo")
LOGS_DIR = os.path.join(BUJO_DIR, "Logs")
UNREVIEWED_FILE = os.path.join(BUJO_DIR, "unreviewed_days.json")

os.makedirs(LOGS_DIR, exist_ok=True)


# --- Path & Registry Helpers ---

def _get_day_log_path(date_str: str) -> str:
    """Returns Vault/BuJo/Logs/<YYYY>/<YYYY-MM-DD>.json"""
    year = date_str.split("-")[0]
    year_dir = os.path.join(LOGS_DIR, year)
    os.makedirs(year_dir, exist_ok=True)
    return os.path.join(year_dir, f"{date_str}.json")


def _load_unreviewed() -> list:
    return read_json(UNREVIEWED_FILE, [])


def _save_unreviewed(data: list) -> None:
    write_json(UNREVIEWED_FILE, data)


def mark_day_unreviewed(date_str: str):
    unreviewed = _load_unreviewed()
    if date_str not in unreviewed:
        unreviewed.append(date_str)
        _save_unreviewed(sorted(unreviewed))


def mark_day_reviewed(date_str: str):
    unreviewed = _load_unreviewed()
    if date_str in unreviewed:
        unreviewed.remove(date_str)
        _save_unreviewed(sorted(unreviewed))


def load_day_log(date_str: str) -> dict:
    path = _get_day_log_path(date_str)
    return read_json(path, {
        "date": date_str,
        "created_at": time.time(),
        "reviewed": False,
        "entries": [],
        "processed_tasks": []
    })


def save_day_log(date_str: str, data: dict):
    path = _get_day_log_path(date_str)
    write_json(path, data)


# --- Parser ---

def parse_rapid_input(raw: str) -> dict:
    clean = raw.strip()
    urgent = "!" in clean
    # Strip standalone exclamation marks
    text_work = re.sub(r'(^|\s)!+(\s|$)', ' ', clean).strip()

    # Detect Energy
    energy = None
    tokens = text_work.split()
    remaining_tokens = []
    for t in tokens:
        if t in ("mp", "mP", "Mp", "MP"):
            energy = t
        else:
            remaining_tokens.append(t)
    text_work = " ".join(remaining_tokens)

    # Detect @area and #project
    area = ""
    project = ""
    area_match = re.search(r'@(\w+)', text_work)
    if area_match:
        area = area_match.group(1).lower()
        text_work = text_work.replace(area_match.group(0), "").strip()

    proj_match = re.search(r'#(\w+)', text_work)
    if proj_match:
        project = proj_match.group(1).lower()
        text_work = text_work.replace(proj_match.group(0), "").strip()

    # Clean double spaces
    final_text = re.sub(r'\s+', ' ', text_work).strip()

    return {
        "id": str(uuid.uuid4())[:8],
        "raw": raw,
        "text": final_text or raw,
        "energy": energy or DEFAULT_ENERGY,
        "urgent": urgent,
        "area": area,
        "project": project,
        "timestamp": time.time(),
        "status": "logged"
    }


# --- Shared Top Bar & Floating Snap Injection ---

def render_rapid_log_bar() -> str:
    """Injected at the top of every dashboard page with '/' hotkey and snap target."""
    return """
    <div id="rapid-log-anchor" class="w-full bg-slate-950/90 backdrop-blur border-b border-slate-800 p-2.5 sticky top-0 z-50 shadow-md">
        <form id="rapid-log-form" onsubmit="submitRapidLog(event)" class="max-w-7xl mx-auto flex items-center gap-2">
            <span class="text-xs font-mono font-bold text-indigo-400 bg-indigo-950/80 border border-indigo-800 px-2 py-1 rounded hidden sm:inline-block">/</span>
            <input type="text" id="rapid-log-input" placeholder="Rapid log... (e.g. Fix navbar Mp ! @dev #stream_tools) [/ to focus]" 
                class="flex-1 bg-slate-900 border border-slate-800 focus:border-indigo-500 rounded-xl px-3 py-2 text-xs text-white placeholder-slate-500 focus:outline-none transition font-sans" autocomplete="off" />
            <button type="submit" class="bg-indigo-600 hover:bg-indigo-500 active:scale-95 text-white font-bold text-xs px-3.5 py-2 rounded-xl transition shrink-0">Log</button>
        </form>
    </div>

    <!-- Mobile Snap Floating Button (Bottom Right) -->
    <button onclick="snapToRapidLog()" title="Snap to Rapid Log" class="sm:hidden fixed bottom-5 right-5 z-50 w-12 h-12 rounded-full bg-indigo-600 hover:bg-indigo-500 active:scale-95 text-white shadow-xl flex items-center justify-center text-lg font-black border border-indigo-400/30">
        ⚡
    </button>

    <script>
        async function submitRapidLog(e) {
            e.preventDefault();
            const input = document.getElementById('rapid-log-input');
            const val = input.value.trim();
            if (!val) return;

            try {
                await fetch(`/api/bujo/log?text=${encodeURIComponent(val)}`);
                input.value = '';
                input.placeholder = 'Logged! Next thought...';
                setTimeout(() => { input.placeholder = 'Rapid log... (e.g. Fix navbar Mp ! @dev #stream_tools) [/ to focus]'; }, 1500);
            } catch(err) {}
        }

        function snapToRapidLog() {
            const el = document.getElementById('rapid-log-anchor');
            if (el) {
                el.scrollIntoView({ behavior: 'smooth' });
                setTimeout(() => { document.getElementById('rapid-log-input').focus(); }, 300);
            }
        }

        window.addEventListener('keydown', (e) => {
            if (e.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) {
                e.preventDefault();
                snapToRapidLog();
            }
        });
    </script>
    """


# --- End of Day HTML Review Page (/bujo/review) ---

def handle_eod_review_page(params):
    today_str = datetime.now().strftime("%Y-%m-%d")
    target_date = get_param(params, "date", today_str)

    type_opts = "".join(f'<option value="{t}">{t.upper()}</option>' for t in TASK_TYPES)
    energy_opts = "".join(f'<option value="{k}">{k} - {v["label"]}</option>' for k, v in ENERGY_PROFILES.items())
    block_opts = "".join(f'<option value="{b}">{b.upper()}</option>' for b in BLOCK_TYPES)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>End of Day Review - BuJo</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body {{ background: #070a12; color: #cbd5e1; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
        ::-webkit-scrollbar {{ width: 6px; }}
        ::-webkit-scrollbar-thumb {{ background: #1e293b; border-radius: 4px; }}
    </style>
</head>
<body class="p-4 md:p-8 max-w-5xl mx-auto space-y-6">
    <header class="flex flex-col md:flex-row md:items-center justify-between border-b border-slate-800 pb-4 gap-4">
        <div>
            <h1 class="text-xl font-black text-white uppercase tracking-wider flex items-center gap-2">
                <span class="w-3 h-3 rounded-full bg-amber-500"></span>
                End of Day Review: <span id="display-date" class="text-amber-400 font-mono">{target_date}</span>
            </h1>
            <p class="text-xs text-slate-400 font-mono">Process daily raw rapid logs into the Vault hierarchy</p>
        </div>
        <div class="flex items-center gap-2">
            <a href="/vault" class="px-3 py-1.5 bg-slate-900 border border-slate-800 text-slate-400 hover:text-white rounded-lg text-xs font-mono">Vault ↗</a>
            <a href="/" class="px-3 py-1.5 bg-slate-900 border border-slate-800 text-slate-400 hover:text-white rounded-lg text-xs font-mono">Hub</a>
        </div>
    </header>

    <!-- Priority Day Prompt -->
    <div id="unreviewed-banner" class="hidden bg-amber-950/40 border border-amber-800/80 rounded-2xl p-4 flex flex-col sm:flex-row justify-between sm:items-center gap-3">
        <div>
            <span class="text-xs font-bold text-amber-300 uppercase tracking-wider block">⚠️ Unreviewed Previous Days Pending</span>
            <span id="unreviewed-dates" class="text-xs font-mono text-slate-400"></span>
        </div>
        <div id="unreviewed-actions" class="flex items-center gap-2"></div>
    </div>

    <!-- Review Deck Container -->
    <main id="review-container" class="space-y-4">
        <div class="text-slate-500 text-xs py-12 text-center">Loading day review...</div>
    </main>

    <!-- Energy Check Completion Modal -->
    <dialog id="energy-prompt-modal" class="bg-slate-900 border border-slate-800 rounded-2xl p-6 text-slate-200 max-w-md w-full backdrop:bg-black/60 shadow-2xl space-y-4">
        <h3 class="text-base font-black text-emerald-400 uppercase">Day Review Complete! 🎉</h3>
        <p id="energy-prompt-text" class="text-xs text-slate-300 leading-relaxed"></p>
        <div class="flex justify-end gap-2 pt-2 border-t border-slate-800">
            <button onclick="finishSession(false)" class="px-3.5 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl text-xs font-bold">I'm Drained (Stop)</button>
            <button id="btn-next-day" onclick="finishSession(true)" class="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-xs font-bold">Process Next Day →</button>
        </div>
    </dialog>

    <script>
        const currentDate = "{target_date}";
        let dayLog = null;
        let vaultTree = null;
        let unreviewedList = [];

        async function init() {{
            const [bujoRes, vaultRes] = await Promise.all([
                fetch(`/api/bujo/day?date=${{currentDate}}`),
                fetch('/api/vault/data')
            ]);
            dayLog = await bujoRes.json();
            const vData = await vaultRes.json();
            vaultTree = (vData && vData.tree) ? vData.tree.areas : {{}};
            unreviewedList = dayLog.unreviewed || [];

            checkUnreviewedBanner();
            renderEntries();
        }}

        function checkUnreviewedBanner() {{
            const banner = document.getElementById('unreviewed-banner');
            const datesSpan = document.getElementById('unreviewed-dates');
            const actions = document.getElementById('unreviewed-actions');

            // Filter out current page date
            const others = unreviewedList.filter(d => d !== currentDate);
            if (others.length === 0) {{
                banner.classList.add('hidden');
                return;
            }}
            banner.classList.remove('hidden');
            datesSpan.innerText = `Pending review: ${{others.join(', ')}}`;
            actions.innerHTML = others.map(d => `
                <a href="/bujo/review?date=${{d}}" class="px-2.5 py-1 bg-amber-900/60 hover:bg-amber-800 text-amber-200 border border-amber-700 rounded-lg text-xs font-mono">
                    Review ${{d}} →
                </a>
            `).join('');
        }}

        function renderEntries() {{
            const container = document.getElementById('review-container');
            const entries = dayLog.entries || [];

            if (entries.length === 0) {{
                container.innerHTML = `
                    <div class="bg-slate-950/60 border border-slate-800 rounded-2xl p-8 text-center space-y-3">
                        <span class="text-3xl">📭</span>
                        <div class="text-sm font-bold text-slate-300">No raw entries for ${{currentDate}}</div>
                        <p class="text-xs text-slate-500">Use the rapid log bar at the top of any page to drop tasks, notes, or thoughts.</p>
                    </div>`;
                return;
            }}

            const areaKeys = Object.keys(vaultTree);
            const areaOptions = `<option value="">(Select Area)</option>` + areaKeys.map(a => `<option value="${{a}}">${{vaultTree[a].display_name || a}}</option>`).join('');

            container.innerHTML = `
                <div class="flex items-center justify-between">
                    <span class="text-xs font-mono text-slate-400">${{entries.length}} raw items recorded</span>
                    <button onclick="finalizeDay()" class="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 active:scale-95 text-white font-bold text-xs rounded-xl transition">
                        Complete ${{currentDate}} Review ✓
                    </button>
                </div>
                <div class="space-y-3">
                    ${{entries.map((entry, idx) => `
                        <div id="entry-card-${{entry.id}}" class="bg-slate-950/80 border border-slate-800 rounded-2xl p-4 space-y-3">
                            <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-800/80 pb-2">
                                <div class="flex items-center gap-2 flex-1 min-w-0">
                                    <span class="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-slate-900 border border-slate-800 text-slate-400">#${{idx + 1}}</span>
                                    <input type="text" id="title-${{entry.id}}" value="${{entry.text.replace(/"/g, '&quot;')}}" class="bg-transparent border-b border-transparent focus:border-indigo-500 text-sm font-bold text-white flex-1 focus:outline-none" />
                                </div>
                                <div class="flex items-center gap-1.5 shrink-0">
                                    ${{entry.urgent ? '<span class="text-rose-400 font-mono font-bold text-xs bg-rose-950/80 border border-rose-800 px-2 py-0.5 rounded">URGENT !</span>' : ''}}
                                    <button onclick="deleteRawEntry('${{entry.id}}')" class="text-slate-600 hover:text-rose-400 font-mono text-xs px-2 py-1">✕</button>
                                </div>
                            </div>

                            <!-- Conversion Form -->
                            <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-2 text-xs">
                                <div>
                                    <label class="block text-[10px] uppercase font-bold text-slate-500 mb-1">Type</label>
                                    <select id="type-${{entry.id}}" class="w-full bg-slate-900 border border-slate-800 rounded-lg p-2 text-white font-mono">
                                        {type_opts}
                                    </select>
                                </div>
                                <div>
                                    <label class="block text-[10px] uppercase font-bold text-slate-500 mb-1">Energy</label>
                                    <select id="energy-${{entry.id}}" class="w-full bg-slate-900 border border-slate-800 rounded-lg p-2 text-white font-mono">
                                        {energy_opts}
                                    </select>
                                </div>
                                <div>
                                    <label class="block text-[10px] uppercase font-bold text-slate-500 mb-1">Area</label>
                                    <select id="area-${{entry.id}}" onchange="updateProjectDropdown('${{entry.id}}')" class="w-full bg-slate-900 border border-slate-800 rounded-lg p-2 text-white">
                                        ${{areaOptions}}
                                    </select>
                                </div>
                                <div>
                                    <label class="block text-[10px] uppercase font-bold text-slate-500 mb-1">Project</label>
                                    <select id="project-${{entry.id}}" class="w-full bg-slate-900 border border-slate-800 rounded-lg p-2 text-white font-mono">
                                        <option value="">(None / Direct Area)</option>
                                    </select>
                                </div>
                            </div>

                            <!-- List of strings (steps/notes) -->
                            <div>
                                <label class="block text-[10px] uppercase font-bold text-slate-500 mb-1">Sub-Steps / Strings (One per line)</label>
                                <textarea id="items-${{entry.id}}" rows="2" placeholder="Step 1&#10;Step 2..." class="w-full bg-slate-900 border border-slate-800 rounded-lg p-2 text-xs text-slate-200 font-mono focus:outline-none"></textarea>
                            </div>

                            <!-- Action -->
                            <div class="flex justify-end gap-2 pt-2 border-t border-slate-800/60">
                                <button onclick="fileEntryToVault('${{entry.id}}')" class="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 active:scale-95 text-white font-bold text-xs rounded-lg transition">
                                    File to Vault ↳
                                </button>
                            </div>
                        </div>
                    `).join('')}}
                </div>`;

            // Pre-fill parsed fields
            entries.forEach(e => {{
                if (e.energy) document.getElementById(`energy-${{e.id}}`).value = e.energy;
                if (e.area && vaultTree[e.area]) {{
                    document.getElementById(`area-${{e.id}}`).value = e.area;
                    updateProjectDropdown(e.id, e.project);
                }}
            }});
        }}

        function updateProjectDropdown(entryId, selectedProject = "") {{
            const areaKey = document.getElementById(`area-${{entryId}}`).value;
            const projSelect = document.getElementById(`project-${{entryId}}`);
            if (!areaKey || !vaultTree[areaKey]) {{
                projSelect.innerHTML = '<option value="">(None / Direct Area)</option>';
                return;
            }}

            const projs = vaultTree[areaKey].projects || {{}};
            const projKeys = Object.keys(projs);
            let opts = '<option value="">(None / Direct Area)</option>';
            projKeys.forEach(pk => {{
                const name = projs[pk].info ? projs[pk].info.name : pk;
                const isSel = (pk === selectedProject) ? 'selected' : '';
                opts += `<option value="${{pk}}" ${{isSel}}>${{name}}</option>`;
            }});
            projSelect.innerHTML = opts;
        }}

        async function fileEntryToVault(entryId) {{
            const title = document.getElementById(`title-${{entryId}}`).value.trim();
            const type = document.getElementById(`type-${{entryId}}`).value;
            const energy = document.getElementById(`energy-${{entryId}}`).value;
            const area = document.getElementById(`area-${{entryId}}`).value;
            const project = document.getElementById(`project-${{entryId}}`).value;
            const items = document.getElementById(`items-${{entryId}}`).value;

            if (!area) {{
                alert("Please select an Area before filing to Vault.");
                return;
            }}

            const q = new URLSearchParams({{
                action: 'file_entry',
                date: currentDate,
                id: entryId,
                title, type, energy, area, project, items
            }});

            const res = await fetch(`/api/bujo/action?${{q.toString()}}`);
            if (res.ok) {{
                const card = document.getElementById(`entry-card-${{entryId}}`);
                card.style.opacity = '0.4';
                card.style.pointerEvents = 'none';
                card.innerHTML = `<div class="p-3 text-emerald-400 font-mono text-xs font-bold">✓ Filed to ${{area}}${{project ? ' / ' + project : ''}}: ${{title}}</div>`;
            }}
        }}

        async function deleteRawEntry(entryId) {{
            if (confirm("Discard this raw log entry?")) {{
                await fetch(`/api/bujo/action?action=delete_entry&date=${{currentDate}}&id=${{entryId}}`);
                init();
            }}
        }}

        async function finalizeDay() {{
            await fetch(`/api/bujo/action?action=mark_reviewed&date=${{currentDate}}`);
            const pendingOthers = unreviewedList.filter(d => d !== currentDate);

            const modal = document.getElementById('energy-prompt-modal');
            const textEl = document.getElementById('energy-prompt-text');
            const nextBtn = document.getElementById('btn-next-day');

            if (pendingOthers.length > 0) {{
                textEl.innerText = `You finished reviewing ${{currentDate}}. There are still unreviewed days waiting (${{pendingOthers.join(', ')}}). Do you have the mental bandwidth (Mp/MP) to process another one, or are you done for the day?`;
                nextBtn.onclick = () => {{ window.location.href = `/bujo/review?date=${{pendingOthers[0]}}`; }};
                nextBtn.classList.remove('hidden');
            }} else {{
                textEl.innerText = `All caught up! Every single day in your BuJo is processed and up to date. Rest up!`;
                nextBtn.classList.add('hidden');
            }}
            modal.showModal();
        }}

        function finishSession(proceed) {{
            if (!proceed) {{
                window.location.href = "/";
            }}
        }}

        window.addEventListener('DOMContentLoaded', init);
    </script>
</body>
</html>"""
    return html_response(html)


# --- API Endpoints ---

def api_bujo_log(params):
    """GET /api/bujo/log?text=... (Used by the universal rapid log bar)"""
    raw_text = get_param(params, "text")
    if not raw_text:
        return json_response({"status": "empty"}, 400)

    parsed = parse_rapid_input(raw_text)
    today_str = datetime.now().strftime("%Y-%m-%d")

    day_data = load_day_log(today_str)
    day_data["entries"].append(parsed)
    save_day_log(today_str, day_data)

    # Flag today as needing EOD review
    mark_day_unreviewed(today_str)

    return json_response({"status": "ok", "entry": parsed, "date": today_str})


def api_bujo_day(params):
    today_str = datetime.now().strftime("%Y-%m-%d")
    date_str = get_param(params, "date", today_str)
    day_data = load_day_log(date_str)
    day_data["unreviewed"] = _load_unreviewed()
    return json_response(day_data)


def api_bujo_action(params):
    action = get_param(params, "action")
    date_str = get_param(params, "date")
    if not date_str:
        return json_response({"status": "error", "message": "Missing date"}, 400)

    day_data = load_day_log(date_str)

    if action == "file_entry":
        entry_id = get_param(params, "id")
        area = get_param(params, "area")
        project = get_param(params, "project", "")
        title = get_param(params, "title")
        t_type = get_param(params, "type", "task")
        energy = get_param(params, "energy", "mp")
        raw_items = get_param(params, "items", "")
        items = [line.strip() for line in raw_items.replace("\r\n", "\n").split("\n") if line.strip()]

        # 1. Create true task in Vault Area/Project
        task_data = {
            "id": entry_id,
            "title": title,
            "type": t_type,
            "energy": normalize_energy_key(energy),
            "block_type": "none",
            "status": "pending",
            "notes": f"Logged from BuJo {date_str}",
            "items": items
        }
        guid = save_vault_task(area, project, task_data)

        # 2. Archive entry in day log as processed
        day_data["entries"] = [e for e in day_data["entries"] if e.get("id") != entry_id]
        if "processed_tasks" not in day_data:
            day_data["processed_tasks"] = []
        day_data["processed_tasks"].append(task_data)
        save_day_log(date_str, day_data)

        return json_response({"status": "ok", "guid": guid})

    elif action == "delete_entry":
        entry_id = get_param(params, "id")
        day_data["entries"] = [e for e in day_data["entries"] if e.get("id") != entry_id]
        save_day_log(date_str, day_data)
        return json_response({"status": "ok"})

    elif action == "mark_reviewed":
        day_data["reviewed"] = True
        save_day_log(date_str, day_data)
        mark_day_reviewed(date_str)
        return json_response({"status": "ok", "date": date_str})

    return json_response({"status": "error"}, 400)


# --- Dashboard Widget ---

def render_dashboard_widget(params):
    today_str = datetime.now().strftime("%Y-%m-%d")
    day_data = load_day_log(today_str)
    unreviewed = _load_unreviewed()
    pending_count = len(day_data.get("entries", []))

    review_badge = ""
    if unreviewed:
        review_badge = f"""
        <a href="/bujo/review?date={unreviewed[0]}" class="px-2.5 py-1 text-xs font-mono font-bold rounded-lg bg-amber-950/80 text-amber-300 border border-amber-800 animate-pulse">
            EOD Review: {len(unreviewed)} Days Waiting ⚠️
        </a>
        """
    else:
        review_badge = f"""
        <a href="/bujo/review?date={today_str}" class="px-2.5 py-1 text-xs font-mono font-bold rounded-lg bg-slate-900 text-slate-400 border border-slate-800">
            Today's Log
        </a>
        """

    return f"""
    <div class="bg-slate-950/60 border border-slate-800 rounded-2xl p-5 space-y-4">
        <div class="flex items-center justify-between border-b border-slate-800 pb-3">
            <div>
                <h2 class="text-sm font-bold uppercase tracking-wider text-amber-400 flex items-center gap-2">
                    <span class="w-2.5 h-2.5 rounded-full bg-amber-500"></span>
                    Digital BuJo & Rapid Log
                </h2>
                <span class="text-xs font-mono text-slate-400">{pending_count} unfiled items captured today</span>
            </div>
            {review_badge}
        </div>
        <div class="p-3 bg-slate-900 border border-slate-800 rounded-xl flex items-center justify-between text-xs">
            <span class="text-slate-300">Hotkeys: <span class="font-mono text-amber-400">/</span> to focus bar, <span class="font-mono text-amber-400">!</span> for urgent</span>
            <a href="/bujo/review?date={today_str}" class="bg-amber-600 hover:bg-amber-500 text-white font-bold text-xs px-3 py-1.5 rounded-lg transition">
                Start End of Day →
            </a>
        </div>
    </div>
    """


def render_remote_widget(params):
    today_str = datetime.now().strftime("%Y-%m-%d")
    unreviewed = _load_unreviewed()
    return f"""
    <div class="bg-slate-900 border border-slate-800 rounded-xl p-3.5 flex items-center justify-between">
        <div>
            <span class="text-xs font-bold uppercase tracking-wider text-amber-400 block">BuJo Review</span>
            <span class="text-[11px] font-mono text-slate-400">{len(unreviewed)} unreviewed days</span>
        </div>
        <a href="/bujo/review?date={today_str}" class="bg-amber-600 active:bg-amber-500 text-white font-bold text-xs px-3 py-1.5 rounded-lg">
            Review →
        </a>
    </div>
    """


ROUTES = {
    "/bujo/review": handle_eod_review_page,
    "/api/bujo/log": api_bujo_log,
    "/api/bujo/day": api_bujo_day,
    "/api/bujo/action": api_bujo_action
}



# Auto-register the rapid log bar into the page layout engine
set_page_header_hook(render_rapid_log_bar)