from utils import (
    OVERLAY_THEMES, escape, quote, get_param,
    html_response, json_response, read_json, write_json,
    render_theme_picker, render_item_picker, get_data_path,
    render_obs_overlay
)

MODULE_ID = "counters"
MODULE_NAME = "Counters & Announcements"

COUNTERS_FILE = get_data_path("counters_store.json")
MESSAGES_FILE = get_data_path("messages_store.json")

# --- Module JavaScript ---
SHARED_JS = [
    """
    function promptRenameCounter(oldName) {
        const newName = prompt(`Rename counter "${oldName}" to:`, oldName);
        if (newName && newName.trim() && newName.trim() !== oldName) {
            window.location.search = `?action=rename&name=${encodeURIComponent(oldName)}&new_name=${encodeURIComponent(newName.trim())}`;
        }
    }
    function promptRenameMessage(oldLabel) {
        const newLabel = prompt(`Rename message label "${oldLabel}" to:`, oldLabel);
        if (newLabel && newLabel.trim() && newLabel.trim() !== oldLabel) {
            window.location.search = `?action=rename_message&msg_label=${encodeURIComponent(oldLabel)}&new_msg_label=${encodeURIComponent(newLabel.trim())}`;
        }
    }
    """
]


# --- State Helpers ---
def load_counters(): return read_json(COUNTERS_FILE, {})


def save_counters(data): write_json(COUNTERS_FILE, data)


def load_messages(): return read_json(MESSAGES_FILE, {})


def save_messages(data): write_json(MESSAGES_FILE, data)


def handle_common_commands(params):
    action = get_param(params, "action")
    if not action:
        return

    name = get_param(params, "name")
    counters = load_counters()

    if action == "inc" and name:
        amt = int(get_param(params, "amt", "1"))
        counters[name] = max(0, counters.get(name, 0) + amt)
        save_counters(counters)
    elif action == "dec" and name:
        amt = int(get_param(params, "amt", "1"))
        counters[name] = max(0, counters.get(name, 0) - amt)
        save_counters(counters)
    elif action == "set" and name:
        val = int(get_param(params, "val", "0"))
        counters[name] = max(0, val)
        save_counters(counters)
    elif action == "delete" and name in counters:
        del counters[name]
        save_counters(counters)
    elif action == "rename" and name in counters:
        new_name = get_param(params, "new_name").strip()
        if new_name:
            counters[new_name] = counters.pop(name)
            save_counters(counters)
    elif action == "bulk_set":
        bulk = get_param(params, "bulk_data")
        for item in bulk.replace("\n", ",").split(","):
            if not item.strip(): continue
            parts = item.strip().rsplit(" ", 1)
            if len(parts) == 2 and parts[1].isdigit():
                counters[parts[0].strip()] = int(parts[1])
            else:
                counters[item.strip()] = counters.get(item.strip(), 0)
        save_counters(counters)

    # Message actions
    msg_label = get_param(params, "msg_label")
    messages = load_messages()
    if action == "save_message" and msg_label:
        messages[msg_label] = get_param(params, "msg_content")
        save_messages(messages)
    elif action == "delete_message" and msg_label in messages:
        del messages[msg_label]
        save_messages(messages)


# --- Widget Renderers ---
def render_dashboard_widget(params):
    counters = load_counters()
    counter_cards = []
    for name, count in sorted(counters.items()):
        qname = quote(name)
        counter_cards.append(f"""
        <div class="bg-slate-900/90 border border-slate-800 rounded-xl p-3.5 shadow-sm">
            <div class="flex justify-between items-center mb-3">
                <span class="font-bold text-slate-200 text-sm truncate">{escape(name)}</span>
                <div class="flex gap-2">
                    <button type="button" onclick="promptRenameCounter('{escape(name)}')" class="text-slate-500 hover:text-amber-400 text-xs">✏️</button>
                    <a href="/?action=delete&name={qname}" onclick="return confirm('Delete {escape(name)}?');" class="text-slate-600 hover:text-rose-400 text-xs">✕</a>
                </div>
            </div>
            <div class="flex items-center justify-between bg-slate-950 border border-slate-800/80 rounded-lg p-1.5 mb-2">
                <a href="/?action=dec&name={qname}&amt=1" class="px-2 py-1 bg-slate-800 hover:bg-slate-700 text-xs font-bold text-white rounded">-1</a>
                <span class="font-mono font-black text-emerald-400 text-base">{count}</span>
                <a href="/?action=inc&name={qname}&amt=1" class="px-2 py-1 bg-emerald-600 hover:bg-emerald-500 text-xs font-bold text-white rounded">+1</a>
            </div>
        </div>
        """)

    grid = "".join(
        counter_cards) if counter_cards else '<div class="col-span-full text-slate-500 text-xs py-4 text-center">No counters active.</div>'
    return f"""
    <div class="bg-slate-950/60 border border-slate-800 rounded-2xl p-5 space-y-4">
        <div class="flex items-center justify-between border-b border-slate-800 pb-3">
            <h2 class="text-sm font-bold uppercase tracking-wider text-emerald-400 flex items-center gap-2">
                Counters
                <a href="/obs/counter_display" target="_blank" class="text-[10px] text-slate-400 hover:text-emerald-300 font-mono">(+ obs link)</a>
            </h2>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
            {grid}
        </div>
    </div>
    """


def render_remote_widget(params):
    counters = load_counters()
    rows = []
    for name, count in sorted(counters.items()):
        qname = quote(name)
        rows.append(f"""
        <div class="flex items-center justify-between bg-slate-900 border border-slate-800 rounded-xl p-3">
            <span class="text-sm font-bold text-white truncate mr-2">{escape(name)}</span>
            <div class="flex items-center gap-1.5 shrink-0">
                <a href="/remote?action=dec&name={qname}&amt=1" class="w-9 h-9 flex items-center justify-center bg-slate-800 active:bg-slate-700 text-white font-bold rounded">-1</a>
                <span class="w-10 text-center font-mono font-black text-emerald-400">{count}</span>
                <a href="/remote?action=inc&name={qname}&amt=1" class="w-9 h-9 flex items-center justify-center bg-emerald-600 active:bg-emerald-500 text-white font-bold rounded">+1</a>
            </div>
        </div>
        """)
    return f"""
    <div class="space-y-2">
        <h2 class="text-xs font-bold uppercase tracking-wider text-emerald-400">Counters</h2>
        {''.join(rows) if rows else '<div class="text-slate-500 text-xs text-center py-4">No counters.</div>'}
    </div>
    """


# --- Dedicated Endpoints (OBS & Polling) ---
def handle_obs_overlay(params):
    theme_key = get_param(params, "theme")
    target_name = get_param(params, "name")
    is_api = get_param(params, "api") == "1"
    counters = load_counters()

    if is_api and target_name:
        return json_response(
            {"name": target_name, "count": counters.get(target_name, 0)}
        )

    html = ""

    if theme_key in OVERLAY_THEMES and target_name:
        qname = quote(target_name)
        current_val = counters.get(target_name, 0)

        html = render_obs_overlay(
            title=f"Counter - {target_name}",
            theme_key=theme_key,
            inner_html=f"""
            <span class="obs-label text-xl truncate ml-5">{escape(target_name)}</span>
            <span class="obs-val text-3xl mr-5 ml-auto" id="display-val">{current_val}</span>
        """,
            poll_endpoint=f"/obs/counter_display?api=1&name={qname}",
            poll_js="document.getElementById('display-val').innerText = data.count;",
        )
    return html_response(html)

def handle_chat_command(user: str, command: str, args: str, tags: dict):
    # Only allow the broadcaster and moderators to modify counters
    badges = tags.get("badges", "")
    is_admin = "broadcaster/1" in badges or "moderator/1" in badges

    if not is_admin:
        return

    # Syntax: !counter <name> [optional: +/-/amount]
    if command in ("!counter", "!c"):
        raw_text = args.strip()
        if not raw_text:
            return

        delta = 1
        set_exact = None
        target_name = raw_text

        # Check if the streamer provided a specific number or adjustment at the end
        parts = raw_text.rsplit(" ", 1)
        if len(parts) == 2:
            candidate_num = parts[1].strip()
            # Explicit delta: +5 or -2
            if candidate_num.startswith(("+", "-")) and candidate_num[1:].isdigit():
                delta = int(candidate_num)
                target_name = parts[0].strip()
            # Exact set: 0, 10, etc.
            elif candidate_num.isdigit():
                set_exact = int(candidate_num)
                target_name = parts[0].strip()

        counters = load_counters()

        # Case-insensitive lookup so "!counter deaths" matches "Deaths"
        lookup_name = target_name
        for existing in counters:
            if existing.lower() == target_name.lower():
                lookup_name = existing
                break

        if set_exact is not None:
            counters[lookup_name] = max(0, set_exact)
        else:
            counters[lookup_name] = max(0, counters.get(lookup_name, 0) + delta)

        save_counters(counters)
        print(f"[Counter] '{lookup_name}' updated to {counters[lookup_name]} by {user}")



# Route mappings for the dispatcher
ROUTES = {
    "/obs/counter_display": handle_obs_overlay
}