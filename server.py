import importlib
import pkgutil
from http.server import BaseHTTPRequestHandler, HTTPServer
import socket
import sys
import urllib.parse
from pathlib import Path
from twitch_listener import TwitchListener


import modules
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

PORT = 5000
CONFIG_FILE = get_data_path("config.json")

# --- Module Registry & Dynamic Loading ---
MODULE_REGISTRY = {}
ACTIVE_MODULE_IDS = set()


def load_all_modules():
    global MODULE_REGISTRY, ACTIVE_MODULE_IDS
    MODULE_REGISTRY.clear()

    # Discover all python files in the modules/ directory
    for _, module_name, _ in pkgutil.iter_modules(modules.__path__):
        mod = importlib.import_module(f"modules.{module_name}")
        mod_id = getattr(mod, "MODULE_ID", module_name)
        MODULE_REGISTRY[mod_id] = mod

    # Load active status from config
    cfg = read_json(CONFIG_FILE, {"active_modules": list(MODULE_REGISTRY.keys())})
    ACTIVE_MODULE_IDS = set(cfg.get("active_modules", []))


def save_active_modules():
    cfg = read_json(CONFIG_FILE, {})
    cfg["active_modules"] = list(ACTIVE_MODULE_IDS)
    write_json(CONFIG_FILE, cfg)


def get_active_routes():
    """Builds the combined route table for active modules."""
    routes = {}
    for mod_id in ACTIVE_MODULE_IDS:
        mod = MODULE_REGISTRY.get(mod_id)
        if mod and hasattr(mod, "ROUTES"):
            routes.update(mod.ROUTES)
    return routes

def get_currently_active_modules():
    return [MODULE_REGISTRY[m_id] for m_id in ACTIVE_MODULE_IDS if m_id in MODULE_REGISTRY]

# --- Main Dashboard & Remote Aggregators ---
def render_toggle_menu() -> str:
    toggle_pills = []
    for mod_id, mod in sorted(MODULE_REGISTRY.items()):
        name = getattr(mod, "MODULE_NAME", mod_id)
        is_active = mod_id in ACTIVE_MODULE_IDS
        action = "module_disable" if is_active else "module_enable"
        status_dot = "bg-emerald-400" if is_active else "bg-slate-600"
        border = "border-emerald-500/40" if is_active else "border-slate-800"

        toggle_pills.append(f"""
        <a href="/?action={action}&target_mod={mod_id}" class="flex items-center gap-2 px-3 py-1.5 rounded-lg border {border} bg-slate-900 hover:bg-slate-800 transition text-xs font-semibold">
            <span class="w-2 h-2 rounded-full {status_dot}"></span>
            <span class="{'text-white' if is_active else 'text-slate-500'}">{name}</span>
        </a>
        """)
    return f"""
    <div class="flex flex-wrap items-center gap-2 bg-slate-950/70 border border-slate-800/80 p-3 rounded-xl">
        <span class="text-[11px] uppercase tracking-wider text-slate-400 font-bold mr-1">Modules:</span>
        {''.join(toggle_pills)}
    </div>
    """


def handle_dashboard(params):
    action = get_param(params, "action")
    target_mod = get_param(params, "target_mod")

    # Handle Module Toggles
    if action == "module_enable" and target_mod in MODULE_REGISTRY:
        ACTIVE_MODULE_IDS.add(target_mod)
        save_active_modules()
    elif action == "module_disable" and target_mod in ACTIVE_MODULE_IDS:
        ACTIVE_MODULE_IDS.remove(target_mod)
        save_active_modules()

    # Pass command modifications down to active modules
    scripts = []
    widgets_dict = {}

    for mod_id in list(ACTIVE_MODULE_IDS):
        mod = MODULE_REGISTRY.get(mod_id)
        if not mod:
            continue

        if hasattr(mod, "handle_common_commands"):
            mod.handle_common_commands(params)
        if hasattr(mod, "SHARED_JS"):
            scripts.extend(mod.SHARED_JS)
        if hasattr(mod, "render_dashboard_widget"):
            rendered = mod.render_dashboard_widget(params)

            # Neutralize nested background/border so the outer shell owns the corners
            cleaned_rendered = rendered.replace(
                "bg-slate-950/60 border border-slate-800 rounded-2xl p-5",
                "p-5"
            )

            # Unified continuous corner shell with flush top knurled handle
            wrapped_widget = f"""
            <div class="dashboard-widget group relative transition-all duration-150 ease-out rounded-2xl overflow-hidden border border-slate-800 bg-slate-950/60 shadow-lg hover:border-slate-700" 
                 draggable="true" 
                 data-mod-id="{mod_id}">
                <div class="drag-handle w-full h-3.5 bg-slate-900/90 hover:bg-slate-800/90 border-b border-slate-800/80 cursor-grab active:cursor-grabbing flex items-center justify-center transition select-none">
                    <div class="w-24 h-1 opacity-25 group-hover:opacity-75 transition" 
                         style="background-image: radial-gradient(circle, #94a3b8 1px, transparent 1px); background-size: 5px 5px;"></div>
                </div>
                {cleaned_rendered}
            </div>
            """
            widgets_dict[mod_id] = wrapped_widget

    # Distribute initially alternating across two columns
    col0_html = []
    col1_html = []
    for idx, (m_id, w_html) in enumerate(widgets_dict.items()):
        if idx % 2 == 0:
            col0_html.append(w_html)
        else:
            col1_html.append(w_html)

    if widgets_dict:
        widget_content = f"""
        <div id="dashboard-columns" class="grid grid-cols-1 md:grid-cols-2 gap-6 items-start">
            <div id="dash-col-0" class="dash-col flex flex-col gap-6 min-h-[120px]" data-col="0">
                {''.join(col0_html)}
            </div>
            <div id="dash-col-1" class="dash-col flex flex-col gap-6 min-h-[120px]" data-col="1">
                {''.join(col1_html)}
            </div>
        </div>
        """
    else:
        widget_content = '<div class="text-slate-500 py-12 text-center">No active modules enabled.</div>'

    dnd_script = """
    document.addEventListener('DOMContentLoaded', () => {
        const col0 = document.getElementById('dash-col-0');
        const col1 = document.getElementById('dash-col-1');
        if (!col0 || !col1) return;

        const STORAGE_KEY = 'dashboard_col_layout_v2';

        function restoreLayout() {
            try {
                const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
                if (saved && (Array.isArray(saved.col0) || Array.isArray(saved.col1))) {
                    const allCards = Array.from(document.querySelectorAll('.dashboard-widget'));
                    const cardMap = new Map(allCards.map(el => [el.getAttribute('data-mod-id'), el]));

                    col0.innerHTML = '';
                    col1.innerHTML = '';

                    (saved.col0 || []).forEach(id => {
                        if (cardMap.has(id)) {
                            col0.appendChild(cardMap.get(id));
                            cardMap.delete(id);
                        }
                    });

                    (saved.col1 || []).forEach(id => {
                        if (cardMap.has(id)) {
                            col1.appendChild(cardMap.get(id));
                            cardMap.delete(id);
                        }
                    });

                    cardMap.forEach(el => {
                        if (col0.children.length <= col1.children.length) {
                            col0.appendChild(el);
                        } else {
                            col1.appendChild(el);
                        }
                    });
                }
            } catch (e) {}
        }

        function saveLayout() {
            const getIds = (col) => Array.from(col.querySelectorAll('.dashboard-widget'))
                                        .map(el => el.getAttribute('data-mod-id'))
                                        .filter(Boolean);

            const state = {
                col0: getIds(col0),
                col1: getIds(col1)
            };
            localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
        }

        restoreLayout();

        let draggedItem = null;

        document.querySelectorAll('.dash-col').forEach(col => {
            col.addEventListener('dragstart', (e) => {
                const target = e.target.closest('.dashboard-widget');
                if (!target) return;
                draggedItem = target;
                e.dataTransfer.effectAllowed = 'move';
                e.dataTransfer.setData('text/plain', target.getAttribute('data-mod-id'));

                setTimeout(() => {
                    target.classList.add('opacity-30', 'scale-[0.99]');
                }, 0);
            });

            col.addEventListener('dragend', (e) => {
                const target = e.target.closest('.dashboard-widget');
                if (target) {
                    target.classList.remove('opacity-30', 'scale-[0.99]');
                }
                draggedItem = null;
                document.querySelectorAll('.dash-col').forEach(c => {
                    c.classList.remove('bg-indigo-950/20', 'rounded-2xl');
                });
                saveLayout();
            });

            col.addEventListener('dragover', (e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';

                if (!draggedItem) return;

                const afterElement = getDragAfterElement(col, e.clientY);
                if (afterElement == null) {
                    col.appendChild(draggedItem);
                } else {
                    col.insertBefore(draggedItem, afterElement);
                }
            });

            col.addEventListener('dragenter', (e) => {
                col.classList.add('bg-indigo-950/20', 'rounded-2xl');
            });

            col.addEventListener('dragleave', (e) => {
                if (!col.contains(e.relatedTarget)) {
                    col.classList.remove('bg-indigo-950/20', 'rounded-2xl');
                }
            });
        });

        function getDragAfterElement(container, y) {
            const draggableElements = [...container.querySelectorAll('.dashboard-widget:not(.opacity-30)')];

            return draggableElements.reduce((closest, child) => {
                const box = child.getBoundingClientRect();
                const offset = y - box.top - box.height / 2;
                if (offset < 0 && offset > closest.offset) {
                    return { offset: offset, element: child };
                } else {
                    return closest;
                }
            }, { offset: Number.NEGATIVE_INFINITY }).element;
        }
    });
    """

    scripts.append(dnd_script)

    page_body = f"""
    <div class="space-y-6">
        <header class="flex items-center justify-between border-b border-slate-800 pb-5">
            <h1 class="text-xl font-black text-white uppercase tracking-wider flex items-center gap-2">
                <span class="w-3 h-3 rounded-full bg-emerald-500"></span> Control Dashboard
            </h1>
            <a href="/" class="bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-2 text-xs font-bold rounded-lg border border-slate-700">⟳ Refresh</a>
        </header>
        {render_toggle_menu()}
        {widget_content}
        <div class="h-36 w-full shrink-0"></div>
    </div>
    """
    return html_response(render_page("Dashboard", page_body, scripts))


def handle_remote(params):
    widgets_html = []
    scripts = []

    for mod_id in list(ACTIVE_MODULE_IDS):
        mod = MODULE_REGISTRY.get(mod_id)
        if not mod: continue

        if hasattr(mod, "handle_common_commands"):
            mod.handle_common_commands(params)
        if hasattr(mod, "SHARED_JS"):
            scripts.extend(mod.SHARED_JS)
        if hasattr(mod, "render_remote_widget"):
            widgets_html.append(mod.render_remote_widget(params))

    body = f"""
    <header class="flex items-center justify-between border-b border-slate-800 pb-4">
        <h1 class="text-sm font-bold text-white uppercase tracking-wider">Mobile Remote</h1>
        <a href="/remote" class="bg-slate-800 text-slate-200 text-xs px-3 py-1.5 rounded-lg">Sync ⟳</a>
    </header>
    <main class="space-y-6">
        {''.join(widgets_html) if widgets_html else '<div class="text-slate-500 py-8 text-center text-xs">No active widgets.</div>'}
    </main>
    """
    return html_response(render_page("Remote", body, scripts))


# --- Dispatcher ---
class UnifiedTrackerHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        if len(args) > 1 and str(args[1]).startswith(("4", "5")):
            sys.stderr.write(f"[{self.log_date_time_string()}] {format % args}\n")

    def do_GET(self):
        self._handle_request()

    def do_POST(self):
        self._handle_request()

    def _handle_request(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        # Core Pages
        if path == "/":
            body, (k, v) = handle_dashboard(params)
        elif path == "/remote":
            body, (k, v) = handle_remote(params)
        else:
            # Query module-defined route tables
            active_routes = get_active_routes()
            handler = active_routes.get(path)

            if handler:
                result = handler(params)
                body, (k, v) = result if isinstance(result, tuple) else (str(result), ("Content-Type", "text/plain"))
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"404 Not Found")
                return

        self.send_response(200)
        self.send_header(k, v)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


if __name__ == "__main__":
    load_all_modules()

    # Start the Zero-Helix IRC Listener
    listener = TwitchListener(get_active_modules_fn=get_currently_active_modules)
    listener.start()

    ip = get_local_ip()

    twitch = TwitchListener(get_active_modules_fn=get_currently_active_modules)
    twitch_thread = twitch.start()

    server = HTTPServer(("0.0.0.0", PORT), UnifiedTrackerHandler)
    print("=====================================================")
    print(f"Server Running on http://{ip}:{PORT}")
    print(f"Loaded Modules: {', '.join(MODULE_REGISTRY.keys()) if MODULE_REGISTRY else 'None'}")
    print("-----------------------------------------------------")
    print("Active Endpoints:")

    # Core Endpoints
    print("  [Core Dashboards]")
    print(f"    - Desktop: http://localhost:{PORT}/")
    print(f"    - Remote:  http://localhost:{PORT}/remote")

    # Dynamically Loaded Module Endpoints
    active_routes = get_active_routes()
    if active_routes:
        print("\n  [Module Routes & OBS Overlays]")
        obs_endpoints = []
        for route in sorted(active_routes.keys()):
            prefix = "[API]" if "/api/" in route else "[OBS]" if "/obs/" in route else " [VR]" if "/vr/" in route else "     "
            if "/api/" in route:
                continue
            if "/obs/" in route:
                obs_endpoints.append(f"    {prefix} http://localhost:{PORT}{route}")
                continue
            print(f"    {prefix} http://localhost:{PORT}{route}")
        for end in obs_endpoints:
            print(end)

    print("=====================================================")
    print("[*] Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Server shutdown cleanly.")
        server.server_close()