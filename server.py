import importlib
import pkgutil
from http.server import BaseHTTPRequestHandler, HTTPServer
import socket
import sys
import urllib.parse
from pathlib import Path
from twitch_listener import TwitchListener

import modules
from utils import read_json, write_json, render_page, get_data_path, get_param, html_response

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
    widgets_html = []

    for mod_id in list(ACTIVE_MODULE_IDS):
        mod = MODULE_REGISTRY.get(mod_id)
        if not mod: continue

        if hasattr(mod, "handle_common_commands"):
            mod.handle_common_commands(params)
        if hasattr(mod, "SHARED_JS"):
            scripts.extend(mod.SHARED_JS)
        if hasattr(mod, "render_dashboard_widget"):
            widgets_html.append(mod.render_dashboard_widget(params))

    page_body = f"""
    <header class="flex items-center justify-between border-b border-slate-800 pb-5">
        <h1 class="text-xl font-black text-white uppercase tracking-wider flex items-center gap-2">
            <span class="w-3 h-3 rounded-full bg-emerald-500"></span> Control Dashboard
        </h1>
        <a href="/" class="bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-2 text-xs font-bold rounded-lg border border-slate-700">⟳ Refresh</a>
    </header>
    {render_toggle_menu()}
    <main class="space-y-6">
        {''.join(widgets_html) if widgets_html else '<div class="text-slate-500 py-12 text-center">No active modules enabled.</div>'}
    </main>
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

    server = HTTPServer(("0.0.0.0", PORT), UnifiedTrackerHandler)
    print("=====================================================")
    print(f"Server Running: http://{ip}:{PORT}")
    print(f"Localhost:      http://localhost:{PORT}")
    print(f"Loaded Modules: {', '.join(MODULE_REGISTRY.keys())}")
    print("=====================================================")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Server shutdown cleanly.")
        server.server_close()