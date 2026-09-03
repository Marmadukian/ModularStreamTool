import os
import time
import uuid
import shutil
from pathlib import Path
from utils import (
    BASE_DIR, read_json, write_json, escape, quote, get_param,
    json_response, html_response, normalize_energy_key,
    render_energy_badge, ENERGY_PROFILES
)

MODULE_ID = "vault_manager"
MODULE_NAME = "Project Manager"

VAULT_DIR = os.path.join(BASE_DIR, "Vault")
AREAS_DIR = os.path.join(VAULT_DIR, "Areas")
BLOCKED_FILE = os.path.join(VAULT_DIR, "currently_blocked.json")

os.makedirs(AREAS_DIR, exist_ok=True)

TASK_TYPES = ["task", "event", "note", "quote", "url", "discard"]
BLOCK_TYPES = ["none", "impossible task", "demand avoidance", "waiting on someone", "unknown"]
STATUS_TYPES = ["pending", "in the middle of", "finished", "tested", "complete"]

SEVEN_DAYS_SECONDS = 7 * 24 * 60 * 60


# --- Helper Utilities & Slugs ---

def _slugify(name: str) -> str:
    if not name:
        return ""
    clean = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in str(name).strip().lower())
    return clean.strip("_") or "unnamed"


def resolve_target_dir(area: str, project: str = "") -> str:
    area_slug = _slugify(area)
    if not project or not project.strip():
        target = os.path.join(AREAS_DIR, area_slug)
    else:
        target = os.path.join(AREAS_DIR, area_slug, "Projects", _slugify(project))
    os.makedirs(target, exist_ok=True)
    return target


# --- Blocked Registry Sync ---

def _load_blocked_registry() -> list:
    return read_json(BLOCKED_FILE, [])


def _save_blocked_registry(data: list) -> None:
    write_json(BLOCKED_FILE, data)


def sync_blocked_registry(task_guid: str, task_path: str, area: str, project: str, block_type: str, task_title: str):
    try:
        registry = _load_blocked_registry()
        registry = [r for r in registry if str(r.get("task_guid")) != str(task_guid)]

        if block_type and block_type != "none":
            rel = os.path.relpath(task_path, VAULT_DIR) if os.path.exists(task_path) else task_path
            registry.append({
                "task_guid": str(task_guid),
                "path": rel,
                "area": area,
                "project": project or "",
                "block_type": block_type,
                "title": task_title or "Untitled Task",
                "blocked_at": time.time()
            })
        _save_blocked_registry(registry)
    except Exception as e:
        print(f"[!] Blocked registry sync failed: {e}")


# --- 7-Day Sweep & Restore Engine ---

def sweep_directory_stale_tasks(target_dir: str, area: str, project: str = ""):
    if not os.path.exists(target_dir):
        return

    now = time.time()
    info_path = os.path.join(target_dir, "info.json")
    info = read_json(info_path, {})

    last_sweep = info.get("last_sweep_at", 0)
    if now - last_sweep < SEVEN_DAYS_SECONDS:
        return

    stale_file = os.path.join(target_dir, "stale.json")
    stale_list = read_json(stale_file, [])
    swept_any = False

    for file_name in os.listdir(target_dir):
        if file_name.startswith("task_") and file_name.endswith(".json"):
            full_path = os.path.join(target_dir, file_name)
            task_data = read_json(full_path, None)
            if not isinstance(task_data, dict):
                continue

            updated_at = task_data.get("updated_at", task_data.get("created_at", now))
            if now - updated_at >= SEVEN_DAYS_SECONDS:
                task_guid = task_data.get("id") or file_name.replace("task_", "").replace(".json", "")
                task_data["id"] = task_guid
                task_data["area"] = area
                task_data["project"] = project or ""
                task_data["_original_file"] = file_name
                task_data["_swept_at"] = now

                stale_list.append(task_data)
                sync_blocked_registry(task_guid, full_path, "", "", "none", "")

                try:
                    os.remove(full_path)
                    swept_any = True
                except OSError:
                    pass

    if swept_any:
        write_json(stale_file, stale_list)

    info["last_sweep_at"] = now
    write_json(info_path, info)


def restore_stale_task(area: str, project: str, task_id: str) -> dict:
    target_dir = resolve_target_dir(area, project)
    stale_file = os.path.join(target_dir, "stale.json")
    stale_list = read_json(stale_file, [])

    matched_task = None
    remaining_stale = []

    for item in stale_list:
        if str(item.get("id")) == str(task_id) and not matched_task:
            matched_task = item
        else:
            remaining_stale.append(item)

    if matched_task:
        matched_task.pop("_swept_at", None)
        matched_task.pop("_original_file", None)
        matched_task["updated_at"] = time.time()

        active_task_file = os.path.join(target_dir, f"task_{task_id}.json")
        write_json(active_task_file, matched_task)
        write_json(stale_file, remaining_stale)

        if matched_task.get("block_type") and matched_task["block_type"] != "none":
            sync_blocked_registry(
                task_guid=task_id,
                task_path=active_task_file,
                area=area,
                project=project,
                block_type=matched_task["block_type"],
                task_title=matched_task.get("title", "Restored Task")
            )
        return matched_task
    return None


# --- Vault Tree Scanner ---

def get_vault_tree() -> dict:
    tree = {"areas": {}}
    if not os.path.exists(AREAS_DIR):
        return tree

    for area_folder in os.listdir(AREAS_DIR):
        area_path = os.path.join(AREAS_DIR, area_folder)
        if not os.path.isdir(area_path):
            continue

        sweep_directory_stale_tasks(area_path, area=area_folder, project="")
        info_file = os.path.join(area_path, "info.json")
        area_info = read_json(info_file, {"name": area_folder})
        display_name = area_info.get("name") or area_folder

        area_tasks = []
        for f in os.listdir(area_path):
            if f.startswith("task_") and f.endswith(".json"):
                t = read_json(os.path.join(area_path, f), None)
                if isinstance(t, dict):
                    t["id"] = t.get("id") or f.replace("task_", "").replace(".json", "")
                    t["area"] = area_folder
                    t["project"] = ""
                    area_tasks.append(t)

        projects = {}
        proj_base = os.path.join(area_path, "Projects")
        if os.path.exists(proj_base) and os.path.isdir(proj_base):
            for proj_folder in os.listdir(proj_base):
                proj_path = os.path.join(proj_base, proj_folder)
                if not os.path.isdir(proj_path):
                    continue

                sweep_directory_stale_tasks(proj_path, area=area_folder, project=proj_folder)
                p_info_file = os.path.join(proj_path, "info.json")
                proj_info = read_json(p_info_file, {"name": proj_folder})

                proj_tasks = []
                for pf in os.listdir(proj_path):
                    if pf.startswith("task_") and pf.endswith(".json"):
                        pt = read_json(os.path.join(proj_path, pf), None)
                        if isinstance(pt, dict):
                            pt["id"] = pt.get("id") or pf.replace("task_", "").replace(".json", "")
                            pt["area"] = area_folder
                            pt["project"] = proj_folder
                            proj_tasks.append(pt)

                projects[proj_folder] = {
                    "slug": proj_folder,
                    "info": proj_info,
                    "tasks": sorted(proj_tasks, key=lambda x: x.get("created_at", 0), reverse=True)
                }

        tree["areas"][area_folder] = {
            "slug": area_folder,
            "info": area_info,
            "display_name": display_name,
            "tasks": sorted(area_tasks, key=lambda x: x.get("created_at", 0), reverse=True),
            "projects": projects
        }

    return tree


def save_vault_task(area: str, project: str, task_data: dict) -> str:
    area_slug = _slugify(area)
    proj_slug = _slugify(project) if project else ""
    target_dir = resolve_target_dir(area_slug, proj_slug)

    task_guid = str(task_data.get("id") or str(uuid.uuid4())[:8])
    now = time.time()

    task_data["id"] = task_guid
    task_data["area"] = area_slug
    task_data["project"] = proj_slug
    task_data["updated_at"] = now
    if "created_at" not in task_data:
        task_data["created_at"] = now

    task_file = os.path.join(target_dir, f"task_{task_guid}.json")
    write_json(task_file, task_data)

    sync_blocked_registry(
        task_guid=task_guid,
        task_path=task_file,
        area=area_slug,
        project=proj_slug,
        block_type=task_data.get("block_type", "none"),
        task_title=task_data.get("title", "Untitled Task")
    )
    return task_guid


# --- API Endpoints ---

def api_vault_data(params):
    return json_response({
        "tree": get_vault_tree(),
        "blocked": _load_blocked_registry(),
        "meta": {
            "types": TASK_TYPES,
            "blocks": BLOCK_TYPES,
            "statuses": STATUS_TYPES,
            "energies": list(ENERGY_PROFILES.keys())
        }
    })


def api_vault_action(params):
    action = get_param(params, "action")
    raw_area = get_param(params, "area", "")
    raw_project = get_param(params, "project", "")

    area = _slugify(raw_area)
    project = _slugify(raw_project) if raw_project else ""
    now = time.time()

    if not area and action in ("create_area", "create_project", "save_task", "delete_area"):
        return json_response({"status": "error", "message": "Missing area parameter"}, 400)

    if action == "create_area":
        area_dir = resolve_target_dir(area)
        write_json(os.path.join(area_dir, "info.json"), {
            "name": raw_area.strip(),
            "created_at": now,
            "last_sweep_at": now
        })
        return json_response({"status": "ok", "area": area})

    elif action == "delete_area":
        target = os.path.join(AREAS_DIR, area)
        if os.path.exists(target):
            shutil.rmtree(target, ignore_errors=True)
        return json_response({"status": "ok"})

    elif action == "create_project" and project:
        proj_dir = resolve_target_dir(area, project)
        write_json(os.path.join(proj_dir, "info.json"), {
            "name": raw_project.strip(),
            "created_at": now,
            "last_sweep_at": now
        })
        return json_response({"status": "ok", "project": project})

    elif action == "delete_project" and project:
        target = resolve_target_dir(area, project)
        if os.path.exists(target):
            shutil.rmtree(target, ignore_errors=True)
        return json_response({"status": "ok"})

    elif action == "save_task":
        task_id = get_param(params, "id", "")
        task_title = get_param(params, "title", "Untitled Task")
        block_type = get_param(params, "block_type", "none")
        if block_type not in BLOCK_TYPES:
            block_type = "none"

        raw_items = get_param(params, "items", "")
        parsed_items = [line.strip() for line in raw_items.replace("\r\n", "\n").split("\n") if line.strip()]

        t_data = {
            "id": task_id if task_id else str(uuid.uuid4())[:8],
            "title": task_title,
            "type": get_param(params, "type", "task"),
            "energy": normalize_energy_key(get_param(params, "energy", "mp")),
            "block_type": block_type,
            "status": get_param(params, "status", "pending"),
            "notes": get_param(params, "notes", ""),
            "items": parsed_items
        }
        guid = save_vault_task(area, project, t_data)
        return json_response({"status": "ok", "guid": guid})

    elif action == "delete_task":
        task_id = get_param(params, "id")
        target_dir = resolve_target_dir(area, project)
        task_file = os.path.join(target_dir, f"task_{task_id}.json")
        if os.path.exists(task_file):
            os.remove(task_file)
            sync_blocked_registry(task_id, task_file, "", "", "none", "")
        return json_response({"status": "ok"})

    elif action == "update_status":
        task_id = get_param(params, "id")
        status = get_param(params, "status", "pending")
        target_dir = resolve_target_dir(area, project)
        task_file = os.path.join(target_dir, f"task_{task_id}.json")

        t_data = read_json(task_file, None)
        if isinstance(t_data, dict):
            t_data["status"] = status
            t_data["updated_at"] = now
            write_json(task_file, t_data)
            return json_response({"status": "ok"})
        return json_response({"status": "error", "message": "Task file not found"}, 404)

    elif action == "unblock_task":
        task_id = get_param(params, "id")
        target_dir = resolve_target_dir(area, project)
        task_file = os.path.join(target_dir, f"task_{task_id}.json")

        t_data = read_json(task_file, None)
        if isinstance(t_data, dict):
            t_data["block_type"] = "none"
            t_data["updated_at"] = now
            write_json(task_file, t_data)
            sync_blocked_registry(task_id, task_file, "", "", "none", "")
            return json_response({"status": "ok"})
        return json_response({"status": "error", "message": "Task file not found"}, 404)

    elif action == "restore_stale":
        task_id = get_param(params, "id")
        restored = restore_stale_task(area, project, task_id)
        if restored:
            return json_response({"status": "ok", "task": restored})
        return json_response({"status": "error", "message": "Task not found in stale archive"}, 404)

    elif action == "wipe_slate_clean":
        # Force sweeps EVERY active task in every area and project into stale.json
        now = time.time()
        tree = get_vault_tree()
        areas = tree.get("areas", {})
        swept_total = 0

        for a_slug, a_data in areas.items():
            area_dir = resolve_target_dir(a_slug)

            # 1. Sweep loose area tasks
            area_stale_file = os.path.join(area_dir, "stale.json")
            area_stale = read_json(area_stale_file, [])
            for f in os.listdir(area_dir):
                if f.startswith("task_") and f.endswith(".json"):
                    full_p = os.path.join(area_dir, f)
                    t_data = read_json(full_p, None)
                    if t_data:
                        t_data["_swept_at"] = now
                        t_data["_wipe_reason"] = "slate_reset"
                        area_stale.append(t_data)
                        swept_total += 1
                        try:
                            os.remove(full_p)
                        except OSError:
                            pass
            write_json(area_stale_file, area_stale)

            # 2. Sweep project tasks
            proj_base = os.path.join(area_dir, "Projects")
            if os.path.exists(proj_base) and os.path.isdir(proj_base):
                for p_slug in os.listdir(proj_base):
                    p_dir = os.path.join(proj_base, p_slug)
                    if not os.path.isdir(p_dir):
                        continue
                    p_stale_file = os.path.join(p_dir, "stale.json")
                    p_stale = read_json(p_stale_file, [])
                    for pf in os.listdir(p_dir):
                        if pf.startswith("task_") and pf.endswith(".json"):
                            p_full_p = os.path.join(p_dir, pf)
                            pt_data = read_json(p_full_p, None)
                            if pt_data:
                                pt_data["_swept_at"] = now
                                pt_data["_wipe_reason"] = "slate_reset"
                                p_stale.append(pt_data)
                                swept_total += 1
                                try:
                                    os.remove(p_full_p)
                                except OSError:
                                    pass
                    write_json(p_stale_file, p_stale)

        # Clear the blocked soft-registry
        _save_blocked_registry([])

        return json_response({"status": "ok", "swept_total": swept_total})

    return json_response({"status": "error", "message": "Invalid request"}, 400)


# --- Vault HTML Interface (/vault) ---

def handle_vault_page(params):
    type_options = "".join(f'<option value="{t}">{t.upper()}</option>' for t in TASK_TYPES)
    energy_options = "".join(f'<option value="{k}">{k} - {v["label"]}</option>' for k, v in ENERGY_PROFILES.items())
    block_options = "".join(f'<option value="{b}">{b.upper()}</option>' for b in BLOCK_TYPES)
    status_options = "".join(f'<option value="{s}">{s.upper()}</option>' for s in STATUS_TYPES)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Vault Workspaces</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body {{ background: #070a12; color: #cbd5e1; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
        ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
        ::-webkit-scrollbar-thumb {{ background: #1e293b; border-radius: 4px; }}
    </style>
</head>
<body class="p-4 md:p-8 max-w-7xl mx-auto space-y-6 pb-36">
    <header class="flex flex-col md:flex-row md:items-center justify-between border-b border-slate-800 pb-4 gap-4">
        <div>
            <h1 class="text-xl font-black text-white uppercase tracking-wider flex items-center gap-2">
                <span class="w-3 h-3 rounded-full bg-indigo-500"></span>
                Vault Hierarchy & Task Core
            </h1>
            <p class="text-xs text-slate-400 font-mono">Active workspaces</p>
        </div>
        <div class="flex items-center gap-2">
            <button onclick="promptCreateArea()" class="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-bold transition">+ Area</button>
            <button onclick="refreshVault()" class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-bold">↻ Sync</button>
            <a href="/" class="px-3 py-1.5 bg-slate-900 border border-slate-800 text-slate-400 hover:text-white rounded-lg text-xs">Hub</a>
        </div>
    </header>

    <!-- Main Hierarchy Grid -->
    <main id="vault-tree" class="space-y-6">
        <div class="text-slate-500 text-xs py-12 text-center">Loading vault components...</div>
    </main>

    <!-- Task Edit Modal -->
    <dialog id="task-modal" class="bg-slate-900 border border-slate-800 rounded-2xl p-6 text-slate-200 max-w-lg w-full backdrop:bg-black/60 shadow-2xl">
        <form method="dialog" onsubmit="submitTaskForm(event)" class="space-y-4">
            <div class="flex justify-between items-center border-b border-slate-800 pb-2">
                <h3 id="modal-title" class="text-sm font-bold text-white uppercase">Edit Task</h3>
                <button type="button" onclick="document.getElementById('task-modal').close()" class="text-slate-500 hover:text-white text-sm">✕</button>
            </div>

            <input type="hidden" id="task-id" />
            <input type="hidden" id="task-area" />
            <input type="hidden" id="task-project" />

            <div>
                <label class="block text-[11px] font-bold text-slate-400 uppercase mb-1">Title</label>
                <input type="text" id="task-name" class="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs text-white focus:outline-none focus:border-indigo-500" required />
            </div>

            <div class="grid grid-cols-2 gap-3">
                <div>
                    <label class="block text-[11px] font-bold text-slate-400 uppercase mb-1">Type</label>
                    <select id="task-type" class="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-xs text-white">
                        {type_options}
                    </select>
                </div>
                <div>
                    <label class="block text-[11px] font-bold text-slate-400 uppercase mb-1">Energy</label>
                    <select id="task-energy" class="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-xs text-white font-mono">
                        {energy_options}
                    </select>
                </div>
            </div>

            <div class="grid grid-cols-2 gap-3">
                <div>
                    <label class="block text-[11px] font-bold text-slate-400 uppercase mb-1">Blocker Status</label>
                    <select id="task-blocker" class="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-xs text-white">
                        {block_options}
                    </select>
                </div>
                <div>
                    <label class="block text-[11px] font-bold text-slate-400 uppercase mb-1">Execution Status</label>
                    <select id="task-status" class="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-xs text-white">
                        {status_options}
                    </select>
                </div>
            </div>

            <div>
                <label class="block text-[11px] font-bold text-slate-400 uppercase mb-1">
                    Array Items / Steps / Tags <span class="text-slate-500 font-normal">(One string per line)</span>
                </label>
                <textarea id="task-items" rows="3" placeholder="Step 1&#10;Step 2&#10;Context note..." class="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-xs text-white focus:outline-none font-mono"></textarea>
            </div>

            <div>
                <label class="block text-[11px] font-bold text-slate-400 uppercase mb-1">Notes / Context</label>
                <textarea id="task-notes" rows="2" class="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-xs text-white focus:outline-none"></textarea>
            </div>

            <div class="flex justify-end gap-2 pt-2 border-t border-slate-800">
                <button type="button" onclick="document.getElementById('task-modal').close()" class="px-3 py-1.5 bg-slate-800 text-slate-400 rounded-lg text-xs">Cancel</button>
                <button type="submit" class="px-4 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white font-bold rounded-lg text-xs">Save Task</button>
            </div>
        </form>
    </dialog>

    <script>
        let vaultData = null;
        const taskCache = new Map();

        async function refreshVault() {{
            try {{
                const res = await fetch('/api/vault/data');
                vaultData = await res.json();

                taskCache.clear();
                const areas = (vaultData.tree && vaultData.tree.areas) ? vaultData.tree.areas : {{}};
                for (const aKey in areas) {{
                    (areas[aKey].tasks || []).forEach(t => taskCache.set(t.id, t));
                    const projects = areas[aKey].projects || {{}};
                    for (const pKey in projects) {{
                        (projects[pKey].tasks || []).forEach(t => taskCache.set(t.id, t));
                    }}
                }}

                renderTree();
            }} catch(e) {{
                document.getElementById('vault-tree').innerHTML = '<div class="text-rose-500 text-xs py-8 text-center">Failed to connect to /api/vault/data</div>';
            }}
        }}

        function renderTree() {{
            const root = document.getElementById('vault-tree');
            const areas = (vaultData && vaultData.tree && vaultData.tree.areas) ? vaultData.tree.areas : {{}};
            const areaKeys = Object.keys(areas);

            if (areaKeys.length === 0) {{
                root.innerHTML = '<div class="text-slate-500 text-xs py-12 text-center">Vault empty. Click "+ Area" above to create your first directory.</div>';
                return;
            }}

            root.innerHTML = areaKeys.map(aKey => {{
                const area = areas[aKey];
                const projects = area.projects || {{}};
                const projKeys = Object.keys(projects);
                const areaTitle = (area.info && area.info.name) ? area.info.name : aKey;

                // STRICT FILTER: Blocked tasks are invisible here
                const unblockedAreaTasks = (area.tasks || []).filter(t => !t.block_type || t.block_type === 'none');

                return `
                <div class="bg-slate-950/80 border border-slate-800 rounded-2xl p-5 space-y-4">
                    <div class="flex items-center justify-between border-b border-slate-800/80 pb-3">
                        <div class="flex items-center gap-2">
                            <span class="text-sm font-black uppercase text-indigo-400 tracking-wider">📁 Area: ${{areaTitle}}</span>
                            <span class="text-[10px] font-mono bg-slate-900 border border-slate-800 px-2 py-0.5 rounded text-slate-400">${{unblockedAreaTasks.length}} active</span>
                        </div>
                        <div class="flex items-center gap-2">
                            <button onclick="openNewTaskModal('${{aKey}}', '')" class="text-xs bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-800 px-2 py-1 rounded">+ Area Task</button>
                            <button onclick="promptCreateProject('${{aKey}}')" class="text-xs bg-indigo-950 hover:bg-indigo-900 text-indigo-300 border border-indigo-800 px-2 py-1 rounded">+ Project</button>
                            <button onclick="deleteArea('${{aKey}}')" class="text-xs text-slate-600 hover:text-rose-400 p-1 font-mono">✕</button>
                        </div>
                    </div>

                    ${{renderTaskGrid(unblockedAreaTasks, aKey, '')}}

                    ${{projKeys.length > 0 ? `
                        <div class="pt-3 space-y-3">
                            <span class="text-[10px] uppercase font-bold text-slate-400 tracking-wider">Active Projects</span>
                            <div class="grid grid-cols-1 gap-3">
                                ${{projKeys.map(pKey => {{
                                    const proj = projects[pKey];
                                    const projTitle = (proj.info && proj.info.name) ? proj.info.name : pKey;
                                    // STRICT FILTER: Blocked tasks are invisible here too
                                    const unblockedProjTasks = (proj.tasks || []).filter(t => !t.block_type || t.block_type === 'none');

                                    return `
                                    <div class="bg-slate-900/60 border border-slate-800/80 rounded-xl p-3.5 space-y-3">
                                        <div class="flex items-center justify-between">
                                            <span class="text-xs font-bold text-slate-200 uppercase tracking-wider">↳ 🎯 ${{projTitle}}</span>
                                            <div class="flex items-center gap-2">
                                                <button onclick="openNewTaskModal('${{aKey}}', '${{pKey}}')" class="text-[11px] bg-slate-800 hover:bg-slate-700 text-slate-300 px-2 py-0.5 rounded">+ Task</button>
                                                <button onclick="deleteProject('${{aKey}}', '${{pKey}}')" class="text-xs text-slate-600 hover:text-rose-400 font-mono">✕</button>
                                            </div>
                                        </div>
                                        ${{renderTaskGrid(unblockedProjTasks, aKey, pKey)}}
                                    </div>`;
                                }}).join('')}}
                            </div>
                        </div>
                    ` : ''}}
                </div>`;
            }}).join('');
        }}

        function renderTaskGrid(tasks, area, project) {{
            if (!tasks || tasks.length === 0) {{
                return '<div class="text-[11px] text-slate-600 italic py-1">No actionable tasks.</div>';
            }}
            return `
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
                ${{tasks.map(t => {{
                    const items = t.items || [];
                    return `
                    <div class="p-3 border border-slate-800 bg-slate-900/40 rounded-xl flex flex-col justify-between gap-2">
                        <div class="flex items-center justify-between">
                            <div class="flex items-center gap-1.5">
                                <span class="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 uppercase">${{t.type || 'task'}}</span>
                                <span class="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded bg-slate-800 text-emerald-400">${{t.energy || 'mp'}}</span>
                                ${{items.length > 0 ? `<span class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-950 border border-slate-800 text-slate-400">${{items.length}} items</span>` : ''}}
                            </div>
                            <div class="flex items-center gap-1.5">
                                <button onclick="editTaskModal('${{t.id}}')" class="text-slate-500 hover:text-white text-xs">✏️</button>
                                <button onclick="deleteTask('${{area}}', '${{project}}', '${{t.id}}')" class="text-slate-600 hover:text-rose-400 text-xs font-mono">✕</button>
                            </div>
                        </div>

                        <div>
                            <div class="font-bold text-xs text-white truncate" title="${{t.title}}">${{t.title}}</div>
                            ${{items.length > 0 ? `
                                <div class="mt-1.5 space-y-1 max-h-24 overflow-y-auto">
                                    ${{items.map(it => `<div class="text-[11px] text-slate-300 bg-slate-950/60 border border-slate-800/80 rounded px-1.5 py-0.5 truncate">• ${{it}}</div>`).join('')}}
                                </div>
                            ` : ''}}
                        </div>

                        <div class="flex items-center justify-between pt-2 border-t border-slate-800/60 text-[10px]">
                            <select onchange="updateTaskStatus('${{area}}', '${{project}}', '${{t.id}}', this.value)" class="bg-slate-950 border border-slate-800 text-slate-300 rounded px-1 py-0.5 font-mono">
                                ${{['pending', 'in the middle of', 'finished', 'tested', 'complete'].map(st => `
                                    <option value="${{st}}" ${{t.status === st ? 'selected' : ''}}>${{st}}</option>
                                `).join('')}}
                            </select>
                        </div>
                    </div>`;
                }}).join('')}}
            </div>`;
        }}

        async function promptCreateArea() {{
            const name = prompt("New Area Name (e.g., Household, Dev, Fitness):");
            if (name && name.trim()) {{
                await fetch(`/api/vault/action?action=create_area&area=${{encodeURIComponent(name.trim())}}`);
                refreshVault();
            }}
        }}

        async function promptCreateProject(area) {{
            const name = prompt(`New Project under "${{area}}":`);
            if (name && name.trim()) {{
                await fetch(`/api/vault/action?action=create_project&area=${{encodeURIComponent(area)}}&project=${{encodeURIComponent(name.trim())}}`);
                refreshVault();
            }}
        }}

        async function deleteArea(area) {{
            if (confirm(`Permanently delete Area "${{area}}" and all internal projects/tasks?`)) {{
                await fetch(`/api/vault/action?action=delete_area&area=${{encodeURIComponent(area)}}`);
                refreshVault();
            }}
        }}

        async function deleteProject(area, project) {{
            if (confirm(`Permanently delete Project "${{project}}"?`)) {{
                await fetch(`/api/vault/action?action=delete_project&area=${{encodeURIComponent(area)}}&project=${{encodeURIComponent(project)}}`);
                refreshVault();
            }}
        }}

        async function deleteTask(area, project, id) {{
            if (confirm("Delete this task?")) {{
                await fetch(`/api/vault/action?action=delete_task&area=${{encodeURIComponent(area)}}&project=${{encodeURIComponent(project)}}&id=${{id}}`);
                refreshVault();
            }}
        }}

        async function updateTaskStatus(area, project, id, status) {{
            await fetch(`/api/vault/action?action=update_status&area=${{encodeURIComponent(area)}}&project=${{encodeURIComponent(project)}}&id=${{id}}&status=${{encodeURIComponent(status)}}`);
            refreshVault();
        }}

        function openNewTaskModal(area, project) {{
            document.getElementById('modal-title').innerText = `New Task (${{area}}${{project ? ' / ' + project : ''}})`;
            document.getElementById('task-id').value = '';
            document.getElementById('task-area').value = area;
            document.getElementById('task-project').value = project;
            document.getElementById('task-name').value = '';
            document.getElementById('task-notes').value = '';
            document.getElementById('task-items').value = '';
            document.getElementById('task-type').value = 'task';
            document.getElementById('task-energy').value = 'mp';
            document.getElementById('task-blocker').value = 'none';
            document.getElementById('task-status').value = 'pending';
            document.getElementById('task-modal').showModal();
        }}

        function editTaskModal(taskId) {{
            const t = taskCache.get(taskId);
            if (!t) return;

            document.getElementById('modal-title').innerText = "Edit Task";
            document.getElementById('task-id').value = t.id;
            document.getElementById('task-area').value = t.area;
            document.getElementById('task-project').value = t.project || '';
            document.getElementById('task-name').value = t.title || '';
            document.getElementById('task-notes').value = t.notes || '';
            document.getElementById('task-items').value = (t.items || []).join('\\n');
            document.getElementById('task-type').value = t.type || 'task';
            document.getElementById('task-energy').value = t.energy || 'mp';
            document.getElementById('task-blocker').value = t.block_type || 'none';
            document.getElementById('task-status').value = t.status || 'pending';
            document.getElementById('task-modal').showModal();
        }}

        async function submitTaskForm(e) {{
            e.preventDefault();
            const id = document.getElementById('task-id').value;
            const area = document.getElementById('task-area').value;
            const project = document.getElementById('task-project').value;
            const title = document.getElementById('task-name').value;
            const type = document.getElementById('task-type').value;
            const energy = document.getElementById('task-energy').value;
            const block_type = document.getElementById('task-blocker').value;
            const status = document.getElementById('task-status').value;
            const notes = document.getElementById('task-notes').value;
            const items = document.getElementById('task-items').value;

            const q = new URLSearchParams({{
                action: 'save_task',
                id, area, project, title, type, energy, block_type, status, notes, items
            }});

            await fetch(`/api/vault/action?${{q.toString()}}`);
            document.getElementById('task-modal').close();
            refreshVault();
        }}

        window.addEventListener('DOMContentLoaded', refreshVault);
    </script>
</body>
</html>"""
    return html_response(html)


# --- Dedicated Unblock Triage Page (/vault/blocked) ---

def handle_blocked_page(params):
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Paused & Blocked Tasks</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body { background: #070a12; color: #cbd5e1; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    </style>
</head>
<body class="p-4 md:p-8 max-w-4xl mx-auto space-y-6 pb-36">
    <header class="flex items-center justify-between border-b border-slate-800 pb-4">
        <div>
            <h1 class="text-lg font-black text-white uppercase tracking-wider">Paused / Blocked Work</h1>
            <p class="text-xs text-slate-400 font-mono">Isolated holding pen. Unblock only when bandwidth allows.</p>
        </div>
        <div class="flex items-center gap-2">
            <a href="/vault" class="px-3 py-1.5 bg-slate-900 border border-slate-800 text-slate-400 hover:text-white rounded-lg text-xs font-mono">← Back to Vault</a>
            <a href="/" class="px-3 py-1.5 bg-slate-900 border border-slate-800 text-slate-400 hover:text-white rounded-lg text-xs font-mono">Hub</a>
        </div>
    </header>

    <main id="blocked-items-container" class="space-y-3">
        <div class="text-slate-500 text-xs py-8 text-center">Loading items on hold...</div>
    </main>

    <script>
        async function loadBlocked() {
            const res = await fetch('/api/vault/data');
            const data = await res.json();
            const items = data.blocked || [];
            const container = document.getElementById('blocked-items-container');

            if (items.length === 0) {
                container.innerHTML = '<div class="p-8 text-center text-slate-500 text-xs border border-slate-800 rounded-2xl bg-slate-950/40">No items are currently paused or blocked.</div>';
                return;
            }

            container.innerHTML = items.map(b => `
                <div class="p-4 bg-slate-900/60 border border-slate-800 rounded-2xl flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                    <div class="space-y-1 min-w-0">
                        <div class="flex items-center gap-2">
                            <span class="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-bold">${b.block_type}</span>
                            <span class="text-[10px] font-mono text-slate-500">${b.area}${b.project ? ' / ' + b.project : ''}</span>
                        </div>
                        <div class="font-bold text-sm text-white truncate">${b.title}</div>
                        <div class="text-[10px] font-mono text-slate-600 truncate">${b.path}</div>
                    </div>
                    <button onclick="unblockTask('${b.area}', '${b.project}', '${b.task_guid}')" class="px-3.5 py-2 bg-indigo-600 hover:bg-indigo-500 active:scale-95 text-white font-bold text-xs rounded-xl transition shrink-0">
                        Unblock & Restore ↳
                    </button>
                </div>
            `).join('');
        }

        async function unblockTask(area, project, id) {
            await fetch(`/api/vault/action?action=unblock_task&area=${encodeURIComponent(area)}&project=${encodeURIComponent(project)}&id=${encodeURIComponent(id)}`);
            loadBlocked();
        }

        window.addEventListener('DOMContentLoaded', loadBlocked);
    </script>
</body>
</html>"""
    return html_response(html)


# --- Dashboard & Remote Widgets ---

def render_dashboard_widget(params):
    tree = get_vault_tree()
    blocked = _load_blocked_registry()
    areas = tree.get("areas", {})

    total_areas = len(areas)
    total_projects = 0
    total_tasks = 0

    for a_data in areas.values():
        total_tasks += len(a_data.get("tasks", []))
        projs = a_data.get("projects", {})
        total_projects += len(projs)
        for p_data in projs.values():
            total_tasks += len(p_data.get("tasks", []))

    return f"""
    <div class="bg-slate-950/60 border border-slate-800 rounded-2xl p-5 space-y-4">
        <div class="flex items-center justify-between border-b border-slate-800 pb-3">
            <div>
                <h2 class="text-sm font-bold uppercase tracking-wider text-indigo-400 flex items-center gap-2">
                    <span class="w-2.5 h-2.5 rounded-full bg-indigo-500"></span>
                    Vault Workspaces
                </h2>
                <span class="text-xs font-mono text-slate-400">Areas, Projects & Backlog</span>
            </div>
            <div class="flex items-center gap-2">
                <a href="/vault" class="bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-xs px-3 py-1.5 rounded-lg transition">
                    Open Vault ↗
                </a>
            </div>
        </div>

        <div class="grid grid-cols-3 gap-2 font-mono text-center">
            <div class="p-3 bg-slate-900 border border-slate-800 rounded-xl">
                <span class="text-[10px] text-slate-500 uppercase block tracking-wider">Areas</span>
                <span class="text-lg font-bold text-slate-200">{total_areas}</span>
            </div>
            <div class="p-3 bg-slate-900 border border-slate-800 rounded-xl">
                <span class="text-[10px] text-indigo-400 uppercase block tracking-wider">Projects</span>
                <span class="text-lg font-bold text-indigo-300">{total_projects}</span>
            </div>
            <div class="p-3 bg-slate-900 border border-slate-800 rounded-xl">
                <span class="text-[10px] text-emerald-400 uppercase block tracking-wider">Active Tasks</span>
                <span class="text-lg font-bold text-emerald-300">{total_tasks}</span>
            </div>
        </div>
    </div>
    """


def render_remote_widget(params):
    tree = get_vault_tree()
    areas = tree.get("areas", {})

    total_tasks = 0
    for a_data in areas.values():
        total_tasks += len(a_data.get("tasks", []))
        for p_data in a_data.get("projects", {}).values():
            total_tasks += len(p_data.get("tasks", []))

    return f"""
    <div class="bg-slate-900 border border-slate-800 rounded-xl p-3.5 flex items-center justify-between">
        <div>
            <span class="text-xs font-bold uppercase tracking-wider text-indigo-400 block">Vault Core</span>
            <span class="text-[11px] font-mono text-slate-400">
                {total_tasks} active tasks
            </span>
        </div>
        <a href="/vault" class="bg-indigo-600 active:bg-indigo-500 text-white font-bold text-xs px-3 py-1.5 rounded-lg">
            Manage →
        </a>
    </div>
    """


# --- Route Exports ---

ROUTES = {
    "/vault": handle_vault_page,
    "/vault/blocked": handle_blocked_page,
    "/api/vault/data": api_vault_data,
    "/api/vault/action": api_vault_action
}