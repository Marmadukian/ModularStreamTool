import socket
import ssl
import threading
import time
from utils import read_json, get_data_path

CONFIG_FILE = get_data_path("config.json")


def parse_irc_line(raw: str):
    """
    Splits IRC lines into (tags, prefix, command, args).
    Enables zero-Helix parsing for bits, sub alerts, raids, and user metadata.
    """
    tags = {}
    line = raw.strip()
    if not line:
        return tags, None, None, []

    if line.startswith("@"):
        tag_str, line = line[1:].split(" ", 1)
        for pair in tag_str.split(";"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                tags[k] = v

    prefix = None
    if line.startswith(":"):
        prefix, line = line[1:].split(" ", 1)

    parts = line.split(" :", 1)
    args = parts[0].split(" ")
    command = args.pop(0)
    if len(parts) > 1:
        args.append(parts[1])

    return tags, prefix, command, args


class TwitchListener:
    def __init__(self, get_active_modules_fn=None):
        self.server = "irc.chat.twitch.tv"
        self.port = 6697  # SSL IRC
        self.sock = None
        self.running = False
        self.get_active_modules = get_active_modules_fn

    def _connect(self):
        cfg = read_json(CONFIG_FILE, {})
        username = cfg.get("bot_username", "").lower()
        oauth = cfg.get("oauth_token", "")
        channel = cfg.get("channel_name", "").lower().lstrip("#")

        if not username or not oauth or not channel:
            print("[!] Twitch config incomplete. Listener standing by.")
            return None

        if not oauth.startswith("oauth:"):
            oauth = f"oauth:{oauth}"

        raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        context = ssl.create_default_context()
        sock = context.wrap_socket(raw_sock, server_hostname=self.server)
        sock.connect((self.server, self.port))

        # Request Twitch capabilities for bits, sub alerts, raids, and badges
        sock.sendall(b"CAP REQ :twitch.tv/tags twitch.tv/commands\r\n")
        sock.sendall(f"PASS {oauth}\r\n".encode("utf-8"))
        sock.sendall(f"NICK {username}\r\n".encode("utf-8"))
        sock.sendall(f"JOIN #{channel}\r\n".encode("utf-8"))

        print(f"[+] Connected to #{channel} chat (Zero-Helix IRC)")
        return sock

    def _dispatch_command(self, user: str, command: str, args_text: str, tags: dict):
        """Passes chat commands to any active module with a handle_chat_command function."""
        if not self.get_active_modules:
            return

        for mod in self.get_active_modules():
            if hasattr(mod, "handle_chat_command"):
                try:
                    mod.handle_chat_command(user, command, args_text, tags)
                except Exception as e:
                    print(f"[!] Error in {getattr(mod, 'MODULE_ID', 'mod')} chat handler: {e}")

    def _dispatch_event(self, event_type: str, data: dict):
        """Passes stream events (bits, raids, subs) to active modules."""
        if not self.get_active_modules:
            return

        for mod in self.get_active_modules():
            if hasattr(mod, "handle_chat_event"):
                try:
                    mod.handle_chat_event(event_type, data)
                except Exception as e:
                    print(f"[!] Error in {getattr(mod, 'MODULE_ID', 'mod')} event handler: {e}")

    def _listen_loop(self):
        read_buffer = ""
        while self.running:
            try:
                if not self.sock:
                    self.sock = self._connect()
                    if not self.sock:
                        time.sleep(10)
                        continue

                data = self.sock.recv(4096)
                if not data:
                    print("[!] IRC disconnected. Reconnecting...")
                    self.sock.close()
                    self.sock = None
                    time.sleep(3)
                    continue

                read_buffer += data.decode("utf-8", errors="ignore")
                lines = read_buffer.split("\r\n")
                read_buffer = lines.pop()

                for raw in lines:
                    tags, prefix, cmd, args = parse_irc_line(raw)

                    # Keep-alive PING/PONG
                    if cmd == "PING":
                        pong_payload = args[0] if args else "tmi.twitch.tv"
                        self.sock.sendall(f"PONG :{pong_payload}\r\n".encode("utf-8"))
                        continue

                    # Chat Messages & Bits
                    if cmd == "PRIVMSG":
                        sender = tags.get("display-name") or (prefix.split("!")[0] if prefix else "Anonymous")
                        message = args[1] if len(args) > 1 else ""

                        if self.get_active_modules:
                            for mod in self.get_active_modules():
                                if hasattr(mod, "handle_chat_message"):
                                    try:
                                        mod.handle_chat_message(sender, message, tags)
                                    except Exception as e:
                                        print(f"[!] Error in chat message handler: {e}")

                        # 1. Cheered Bits Detection
                        if "bits" in tags:
                            bit_count = int(tags.get("bits", "0"))
                            self._dispatch_event("bits", {
                                "user": sender,
                                "amount": bit_count,
                                "message": message,
                                "tags": tags
                            })

                        # 2. Chat Commands (!bsr, !timer, etc.)
                        if message.startswith("!") or message.startswith("$"):
                            tokens = message.split(" ", 1)
                            command = tokens[0].lower()
                            cmd_args = tokens[1].strip() if len(tokens) > 1 else ""
                            self._dispatch_command(sender, command, cmd_args, tags)

                    # Raids & Subs / Resubs
                    elif cmd == "USERNOTICE":
                        msg_id = tags.get("msg-id", "")

                        if msg_id == "raid":
                            raider = tags.get("msg-param-displayName", "A Streamer")
                            viewers = int(tags.get("msg-param-viewerCount", "0"))
                            self._dispatch_event("raid", {
                                "user": raider,
                                "viewers": viewers,
                                "tags": tags
                            })

                        elif msg_id in ("sub", "resub"):
                            subber = tags.get("display-name", "A Viewer")
                            cumulative = tags.get("msg-param-cumulative-months", "1")
                            self._dispatch_event("sub", {
                                "user": subber,
                                "months": cumulative,
                                "tags": tags
                            })

            except (socket.error, ssl.SSLError):
                print("[!] Socket error. Reconnecting...")
                if self.sock:
                    try:
                        self.sock.close()
                    except Exception:
                        pass
                self.sock = None
                time.sleep(3)
            except Exception as e:
                print(f"[!] IRC loop error: {e}")
                time.sleep(3)

    def start(self):
        self.running = True
        thread = threading.Thread(target=self._listen_loop, daemon=True)
        thread.start()
        return thread

    def stop(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass