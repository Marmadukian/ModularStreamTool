# Stream Overlay & Utility Suite

A lightweight, local-first utility suite for stream counters, timers, and static text labels. Runs completely offline on your local network with zero external cloud dependencies or lag.

Controlled via a responsive web dashboard, a streamlined mobile remote, or plain HTTP GET requests.

---

## Requirements

* Python 3.10+
* Operating System: Windows, macOS, or Linux

---

## Quick Start

1. Launch the suite:
   python server.py

2. Open the interfaces:
   * Desktop Dashboard: http://localhost:5000/ 
   * Mobile Remote: http://<YOUR-LOCAL-IP>:5000/remote

---

## OBS Studio Setup

Add a Browser Source in OBS pointing to the local overlay URL:
* URL: http://localhost:8080/obs/text_display (or specific widget URLs depending on module)
* Set width and height to match your stream canvas.


---

## HTTP Control Endpoints

You can trigger any action via simple HTTP GET requests (compatible with Stream Deck, Touch Portal, shell scripts, or browser bookmarks).

### 1. Web dashboard and mobile remote

| Route | Description |
| :--- | :--- |
| / | Main desktop control dashboard (includes drag-and-drop widget layout). |
| /remote | Mobile-optimized remote interface with persistent module switcher. |

---

### 2. Module State Toggles

Enable or disable specific modules on the fly via / or /remote.

| Parameter | Type | Required | Values / Example | Description |
| :--- | :--- | :--- | :--- | :--- |
| action | string | Yes | module_enable, module_disable | Changes module active state |
| target_mod | string | Yes | counters, timers, text | Target module identifier |

Examples:
* Enable timers:
  GET /remote?action=module_enable&target_mod=timers
* Disable static text labels:
  GET /remote?action=module_disable&target_mod=text

---

### 3. Counter Endpoints

All counter actions require the target counter `name`.

| Action (action=) | Required Parameters | Optional Parameters | Description |
| :--- | :--- | :--- | :--- |
| inc | name=<counter_name> | amt=1 | Increments counter by amt (defaults to 1). |
| dec | name=<counter_name> | amt=1 | Decrements counter by amt (clamped to 0). |
| set | name=<counter_name> | amt=<int> or val=<int> | Sets counter explicitly (defaults to 0). |
| rename | name=<current_name>, new_name=<new_name> | — | Renames an existing counter. |
| delete | name=<counter_name> | — | Permanently deletes a counter. |

Examples:
* Increment death counter:
  GET /?action=inc&name=deaths
* Add 5 wins:
  GET /?action=inc&name=wins&amt=5
* Reset death counter to 0:
  GET /?action=set&name=deaths&val=0
* Rename counter:
  GET /?action=rename&name=deaths&new_name=wipes

---

### 4. Text Label / Message Endpoints

Messages use the `msg_` command prefix. All actions require a `label`.

| Action (action=) | Required Parameters | Optional Parameters | Description |
| :--- | :--- | :--- | :--- |
| msg_save | label=<message_key> | content=<text_body> | Creates or updates text content. |
| msg_rename | label=<current_key>, new_label=<new_key> | — | Renames the message key. |
| msg_delete | label=<message_key> | — | Deletes the message entry. |

Examples:
* Update current game label:
  GET /?action=msg_save&label=current_game&content=Elden+Ring
* Rename label:
  GET /?action=msg_rename&label=current_game&new_label=now_playing
* Delete label:
  GET /?action=msg_delete&label=now_playing