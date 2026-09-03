import json
import random
import time
from utils import (
    DEFAULT_ENERGY,
    ENERGY_PROFILES,
    escape,
    get_data_path,
    get_energy_profile,
    get_param,
    html_response,
    json_response,
    normalize_energy_key,
    read_json,
    render_energy_badge,
    write_json,
)

MODULE_ID = "task_tinder"
MODULE_NAME = "Task Tinder"

TASKS_FILE = get_data_path("tasks_store.json")


# --- Persistence ---


def load_tasks() -> list:
    return read_json(
        TASKS_FILE,
        [
            {
                "id": 1,
                "text": "Wipe down kitchen island counter",
                "energy": "mP",
                "completed": False,
            },
            {
                "id": 2,
                "text": "File paper receipts on desk",
                "energy": "mp",
                "completed": False,
            },
            {
                "id": 3,
                "text": "Refactor router dispatcher loop",
                "energy": "Mp",
                "completed": False,
            },
        ],
    )


def save_tasks(tasks: list) -> None:
    write_json(TASKS_FILE, tasks)


# --- API / Engine Logic ---


def api_task_deck(params):
    energy_filter = get_param(params, "energy", "any")
    tasks = load_tasks()
    uncompleted = [t for t in tasks if not t.get("completed", False)]

    if energy_filter in ENERGY_PROFILES:
        pool = [t for t in uncompleted if t.get("energy") == energy_filter]
    else:
        pool = uncompleted

    random.shuffle(pool)

    return json_response({
        "total_uncompleted": len(uncompleted),
        "pool_count": len(pool),
        "current_filter": energy_filter,
        "cards": pool,
    })


def api_task_action(params):
    action = get_param(params, "action")
    task_id = int(get_param(params, "id", "0"))
    tasks = load_tasks()

    if action == "complete" and task_id:
        for t in tasks:
            if t.get("id") == task_id:
                t["completed"] = True
                t["completed_at"] = time.time()
                break
        save_tasks(tasks)
        return json_response({"status": "ok", "action": "complete", "id": task_id})

    elif action == "add":
        raw_text = get_param(params, "text").strip()
        raw_energy = get_param(params, "energy", DEFAULT_ENERGY)
        energy = normalize_energy_key(raw_energy)

        if raw_text:
            new_task = {
                "id": int(time.time() * 1000) % 10000000,
                "text": raw_text,
                "energy": energy,
                "completed": False,
                "created_at": time.time(),
            }
            tasks.append(new_task)
            save_tasks(tasks)
            return json_response({"status": "ok", "task": new_task})

    return json_response({"status": "noop"})


# --- Full View Tinder Interface (/tasks) ---


def handle_tasks_page(params):
    # Client-side map generated dynamically from server utils
    energy_css_map = {
        k: v["badge_css"]
        for k, v in ENERGY_PROFILES.items()
    }

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>Task Tinder</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body {{
            background: #090d16;
            color: #e2e8f0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            touch-action: pan-y;
            user-select: none;
            -webkit-user-select: none;
        }}
        .card-stage {{
            perspective: 1000px;
        }}
        .swipe-card {{
            transition: transform 0.25s ease, opacity 0.25s ease;
            will-change: transform, opacity;
        }}
    </style>
</head>
<body class="min-h-screen flex flex-col justify-between p-4 max-w-md mx-auto">
    <header class="space-y-3">
        <div class="flex items-center justify-between border-b border-slate-800 pb-3">
            <div>
                <h1 class="text-base font-black uppercase tracking-wider text-emerald-400">Task Tinder</h1>
                <span id="deck-stats" class="text-xs font-mono text-slate-500">Loading cards...</span>
            </div>
            <a href="/" class="text-xs text-slate-400 hover:text-white bg-slate-900 border border-slate-800 px-2.5 py-1.5 rounded-lg">← Hub</a>
        </div>

        <div class="grid grid-cols-5 gap-1 text-[11px] font-mono font-bold">
            <button onclick="setFilter('any')" id="btn-any" class="filter-btn py-2 rounded-lg border border-slate-700 bg-slate-800 text-white">ALL</button>
            <button onclick="setFilter('mp')" id="btn-mp" class="filter-btn py-2 rounded-lg border border-slate-800 bg-slate-900 text-slate-400">mp</button>
            <button onclick="setFilter('mP')" id="btn-mP" class="filter-btn py-2 rounded-lg border border-slate-800 bg-slate-900 text-slate-400">mP</button>
            <button onclick="setFilter('Mp')" id="btn-Mp" class="filter-btn py-2 rounded-lg border border-slate-800 bg-slate-900 text-slate-400">Mp</button>
            <button onclick="setFilter('MP')" id="btn-MP" class="filter-btn py-2 rounded-lg border border-slate-800 bg-slate-900 text-slate-400">MP</button>
        </div>
    </header>

    <main class="card-stage flex-1 flex items-center justify-center my-6 relative min-h-[300px]">
        <div id="active-card" class="swipe-card w-full bg-slate-900/95 border-2 border-slate-800 rounded-3xl p-6 shadow-2xl flex flex-col justify-between min-h-[280px]">
            <div class="flex items-center justify-between">
                <span id="card-energy-badge" class="px-2.5 py-1 text-xs font-mono font-bold rounded-lg border border-slate-700 bg-slate-800 text-slate-300">--</span>
                <span class="text-[10px] font-mono text-slate-500">Swipe or use keys</span>
            </div>

            <div id="card-text" class="text-xl sm:text-2xl font-black text-white text-center px-2 my-auto leading-snug">
                Pulling task...
            </div>

            <div class="flex justify-between items-center text-xs font-mono text-slate-500 pt-3 border-t border-slate-800/80">
                <span>[A] or [←] Skip</span>
                <span>[D] or [→] Done</span>
            </div>
        </div>
    </main>

    <footer class="space-y-4">
        <div class="grid grid-cols-2 gap-3">
            <button onclick="swipeLeft()" class="flex items-center justify-center gap-2 py-3.5 bg-slate-900 hover:bg-slate-800 active:scale-95 text-slate-300 font-bold rounded-2xl border border-slate-800 text-sm transition">
                <span class="text-rose-400 text-lg">✕</span> Skip (Recycle)
            </button>
            <button onclick="swipeRight()" class="flex items-center justify-center gap-2 py-3.5 bg-emerald-600 hover:bg-emerald-500 active:scale-95 text-white font-bold rounded-2xl shadow-lg shadow-emerald-950 text-sm transition">
                <span class="text-white text-lg">✓</span> Completed
            </button>
        </div>

        <form onsubmit="handleQuickAdd(event)" class="bg-slate-900/80 border border-slate-800 rounded-2xl p-2.5 flex items-center gap-2">
            <select id="new-task-energy" class="bg-slate-950 border border-slate-800 text-xs text-white rounded-xl px-2 py-2 font-mono focus:outline-none">
                <option value="mp">mp</option>
                <option value="mP">mP</option>
                <option value="Mp">Mp</option>
                <option value="MP">MP</option>
            </select>
            <input type="text" id="new-task-text" placeholder="Drop next thought here..." class="flex-1 bg-transparent text-xs text-white placeholder-slate-500 focus:outline-none px-1" required />
            <button type="submit" class="bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-bold px-3 py-2 rounded-xl border border-slate-700">Add</button>
        </form>
    </footer>

    <script>
        let currentFilter = 'any';
        let cardQueue = [];
        let activeCard = null;
        const energyColors = {json.dumps(energy_css_map)};

        async function fetchDeck() {{
            try {{
                const res = await fetch(`/api/tasks/deck?energy=${{currentFilter}}`);
                const data = await res.json();
                cardQueue = data.cards;
                document.getElementById('deck-stats').innerText = `${{data.pool_count}} available (${{data.total_uncompleted}} total)`;
                showNextCard();
            }} catch(e) {{
                document.getElementById('card-text').innerText = "Failed to load deck.";
            }}
        }}

        function showNextCard() {{
            const cardEl = document.getElementById('active-card');
            cardEl.style.transform = 'translate(0px, 0px) rotate(0deg)';
            cardEl.style.opacity = '1';

            if (!cardQueue || cardQueue.length === 0) {{
                activeCard = null;
                document.getElementById('card-text').innerText = "🎉 All tasks cleared for this energy band!";
                document.getElementById('card-energy-badge').innerText = "--";
                return;
            }}

            activeCard = cardQueue[0];
            document.getElementById('card-text').innerText = activeCard.text;

            const badge = document.getElementById('card-energy-badge');
            badge.innerText = activeCard.energy;
            badge.className = `px-2.5 py-1 text-xs font-mono font-bold rounded-lg border ${{energyColors[activeCard.energy] || 'bg-slate-800 text-slate-300 border-slate-700'}}`;
        }}

        function setFilter(filter) {{
            currentFilter = filter;
            document.querySelectorAll('.filter-btn').forEach(btn => {{
                btn.className = "filter-btn py-2 rounded-lg border border-slate-800 bg-slate-900 text-slate-400";
            }});
            const activeBtn = document.getElementById(`btn-${{filter}}`);
            if (activeBtn) activeBtn.className = "filter-btn py-2 rounded-lg border border-emerald-500 bg-emerald-950 text-emerald-300";
            fetchDeck();
        }}

        function swipeLeft() {{
            if (!activeCard) return;
            const cardEl = document.getElementById('active-card');
            cardEl.style.transform = 'translateX(-120%) rotate(-15deg)';
            cardEl.style.opacity = '0';

            setTimeout(() => {{
                const skipped = cardQueue.shift();
                cardQueue.push(skipped);
                showNextCard();
            }}, 200);
        }}

        async function swipeRight() {{
            if (!activeCard) return;
            const cardEl = document.getElementById('active-card');
            cardEl.style.transform = 'translateX(120%) rotate(15deg)';
            cardEl.style.opacity = '0';

            const finished = cardQueue.shift();
            try {{
                await fetch(`/api/tasks/action?action=complete&id=${{finished.id}}`);
            }} catch(e) {{}}

            setTimeout(() => {{
                showNextCard();
                fetchDeck();
            }}, 200);
        }}

        async function handleQuickAdd(e) {{
            e.preventDefault();
            const textInput = document.getElementById('new-task-text');
            const energySelect = document.getElementById('new-task-energy');
            const text = textInput.value.trim();
            const energy = energySelect.value;
            if (!text) return;

            try {{
                await fetch(`/api/tasks/action?action=add&text=${{encodeURIComponent(text)}}&energy=${{energy}}`);
                textInput.value = '';
                fetchDeck();
            }} catch(e) {{}}
        }}

        window.addEventListener('keydown', (e) => {{
            if (['input', 'textarea', 'select'].includes(document.activeElement.tagName.toLowerCase())) return;
            if (e.key === 'ArrowLeft' || e.key.toLowerCase() === 'a') swipeLeft();
            if (e.key === 'ArrowRight' || e.key.toLowerCase() === 'd') swipeRight();
        }});

        let startX = 0;
        let cardStage = document.getElementById('active-card');

        cardStage.addEventListener('touchstart', e => {{ startX = e.touches[0].clientX; }}, {{passive: true}});
        cardStage.addEventListener('touchmove', e => {{
            if (!activeCard) return;
            const deltaX = e.touches[0].clientX - startX;
            cardStage.style.transform = `translateX(${{deltaX}}px) rotate(${{deltaX * 0.05}}deg)`;
        }}, {{passive: true}});
        cardStage.addEventListener('touchend', e => {{
            if (!activeCard) return;
            const deltaX = e.changedTouches[0].clientX - startX;
            if (deltaX > 90) {{
                swipeRight();
            }} else if (deltaX < -90) {{
                swipeLeft();
            }} else {{
                cardStage.style.transform = 'translateX(0px) rotate(0deg)';
            }}
        }});

        window.addEventListener('DOMContentLoaded', () => setFilter('any'));
    </script>
</body>
</html>"""
    return html_response(html)


# --- Dashboard Mini Widget ---


def render_dashboard_widget(params):
    tasks = load_tasks()
    uncompleted = [t for t in tasks if not t.get("completed", False)]

    counts = {k: 0 for k in ENERGY_PROFILES}
    for t in uncompleted:
        e = normalize_energy_key(t.get("energy", DEFAULT_ENERGY))
        if e in counts:
            counts[e] += 1

    blocks = []
    for key, profile in ENERGY_PROFILES.items():
        blocks.append(f"""
        <div class="p-3 bg-slate-900 border border-slate-800 rounded-xl">
            <div class="flex items-center justify-between mb-1">
                <span class="text-xs font-mono font-bold text-slate-300">{key}</span>
                <span class="w-2 h-2 rounded-full" style="background: {profile['accent_hex']};"></span>
            </div>
            <span class="text-[10px] text-slate-500 block truncate">{escape(profile['label'])}</span>
            <span class="text-xl font-bold font-mono text-white mt-1 block">{counts[key]}</span>
        </div>
        """)

    return f"""
    <div class="bg-slate-950/60 border border-slate-800 rounded-2xl p-5 space-y-4">
        <div class="flex items-center justify-between border-b border-slate-800 pb-3">
            <div>
                <h2 class="text-sm font-bold uppercase tracking-wider text-emerald-400">Task Tinder Engine</h2>
                <span class="text-xs font-mono text-slate-400">{len(uncompleted)} tasks in backlog</span>
            </div>
            <a href="/tasks" target="_blank" class="bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs px-3 py-1.5 rounded-lg transition">
                Open Swipe Deck ↗
            </a>
        </div>
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 font-mono">
            {''.join(blocks)}
        </div>
    </div>
    """


def render_remote_widget(params):
    tasks = load_tasks()
    uncompleted = [t for t in tasks if not t.get("completed", False)]
    return f"""
    <div class="bg-slate-900 border border-slate-800 rounded-xl p-3.5 flex items-center justify-between">
        <div>
            <span class="text-xs font-bold uppercase tracking-wider text-emerald-400 block">Task Tinder</span>
            <span class="text-[11px] font-mono text-slate-400">{len(uncompleted)} tasks waiting</span>
        </div>
        <a href="/tasks" class="bg-emerald-600 active:bg-emerald-500 text-white font-bold text-xs px-3 py-1.5 rounded-lg">
            Launch Deck →
        </a>
    </div>
    """


ROUTES = {
    "/tasks": handle_tasks_page,
    "/api/tasks/deck": api_task_deck,
    "/api/tasks/action": api_task_action,
}