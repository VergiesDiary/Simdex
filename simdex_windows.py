import ctypes
import json
import mimetypes
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import tkinter as tk
import base64
import hashlib
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from urllib.parse import quote, urlencode, urlparse
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zipfile import ZipFile, BadZipFile


try:
    from PIL import Image
except ImportError:
    Image = None

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    AESGCM = None


APP_ROOT = Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming")) / "vergiesdiary" / "SimdexWindows"
INSTALLS_FILE = APP_ROOT / "installed_mods.json"
CREATOR_ACCOUNT_FILE = APP_ROOT / "creator_account.json"
APP_STATE_FILE = APP_ROOT / "app_state.json"
PROJECTS_ROOT = APP_ROOT / "Projects"
CREATOR_CACHE = APP_ROOT / "CreatorCache"
DISABLED_MODS_ROOT = APP_ROOT / "DisabledMods"
SIMS_ROOT = Path.home() / "Documents" / "Electronic Arts" / "The Sims 4"
SIMS_MODS = SIMS_ROOT / "Mods"
SIMS_TRAY = SIMS_ROOT / "Tray"
DEFAULT_API_BASE_URL = "https://simdex.vercel.app"
API_BASE_URL = os.getenv("SIMDEX_API_URL", DEFAULT_API_BASE_URL).rstrip("/")
TERMS_URL = "https://simdex.vercel.app/terms"
PRIVACY_URL = "https://simdex.vercel.app/privacy"
VERIFY_IGNORE_MESSAGE = "Your account is unverified and you will be contacted in the future by staff for verification. Ignore this button until then."
VERIFIED_CREATOR_TOOLTIP = "This creator is verified by email."
VERIFIED_BADGE = " \u2714"
INDEX_PAGE_SIZE = 20

PROJECT_ALLOWED = {".metadata", "Icon.png", "Mods", "Tray"}
APP_MANAGED_FOLDERS = {"CreatorCache", "DisabledMods", "Icons", "InstallBackups", "InstalledSources", "InstallTemp", "Projects"}
MODS_EXTENSIONS = {".package", ".ts4script"}
MODPACK_EXTENSIONS = {".s4i"}
TRAY_EXTENSIONS = {".trayitem", ".blueprint", ".bpi", ".hhi", ".sgi", ".householdbinary", ".room", ".rmi"}
TEXT_EXTENSIONS = {".txt", ".md", ".json", ".xml", ".html", ".css", ".js", ".py", ".csv", ".ini", ".cfg", ".metadata"}
S4I_MAGIC = b"SIMDEX-S4I-1\n"
FILE_ATTRIBUTE_HIDDEN = 0x02
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF


def bundled_path(name):
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root / name


def metadata_template(project_name=""):
    return {
        "name": project_name,
        "short_description": "",
        "author": "",
        "version": "1.0.0",
        "download_page": "",
        "icon": "",
        "long_description": "",
        "is_mod": True,
        "is_modpack": False,
        "dependencies": [],
        "modpack_items": []
    }


def app_slug(value):
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "unknown"


def install_folder_name(author, name):
    return f"{app_slug(author)}_{app_slug(name)}"


def metadata_type(metadata):
    if metadata.get("is_mod") and metadata.get("is_modpack"):
        return "Mod / Modpack"
    if metadata.get("is_modpack"):
        return "Modpack"
    if metadata.get("is_mod"):
        return "Mod"
    return ""


def project_folder_type(project):
    mods = project / "Mods"
    tray = project / "Tray"
    has_modpack_files = any(file.is_file() and file.suffix.lower() in MODPACK_EXTENSIONS for file in mods.rglob("*")) if mods.exists() else False
    has_mod_files = any(file.is_file() and file.suffix.lower() in MODS_EXTENSIONS for file in mods.rglob("*")) if mods.exists() else False
    has_tray_files = folder_has_files(tray) if tray.exists() else False
    if has_mod_files or has_tray_files:
        return "mod"
    if has_modpack_files and not has_mod_files and not has_tray_files:
        return "modpack"
    if not tray.exists():
        return "modpack"
    return "mod"


def apply_project_type(metadata, project):
    kind = project_folder_type(project)
    metadata["is_mod"] = kind == "mod"
    metadata["is_modpack"] = kind == "modpack"
    if metadata["is_modpack"]:
        metadata["dependencies"] = []
    return metadata


def author_display(item):
    suffix = VERIFIED_BADGE if item.get("creator_verified") else ""
    return f"{item.get('author', '')}{suffix}"


def read_json(path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    unhide_file(path)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)


def api_json(path, method="GET", payload=None, token=None):
    data = None
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(f"{API_BASE_URL}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
            message = payload.get("error") or body
        except json.JSONDecodeError:
            message = body or error.reason
        raise ValueError(f"API request failed ({error.code}): {message}") from error


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bytes_sha256(data):
    return hashlib.sha256(data).hexdigest()


def encryption_key(project_id, salt):
    return hashlib.pbkdf2_hmac("sha256", project_id.encode("utf-8"), salt, 200000, dklen=32)


def encrypt_bytes(data, project_id):
    if AESGCM is None:
        raise ValueError("Install cryptography before packaging encrypted .s4i files.")
    salt = os.urandom(16)
    nonce = os.urandom(12)
    encrypted = AESGCM(encryption_key(project_id, salt)).encrypt(nonce, data, project_id.encode("utf-8"))
    payload = {
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "data": base64.b64encode(encrypted).decode("ascii")
    }
    return S4I_MAGIC + json.dumps(payload, separators=(",", ":")).encode("utf-8")


def decrypt_bytes(data, project_id):
    if AESGCM is None:
        raise ValueError("Install cryptography before installing encrypted .s4i files.")
    if not data.startswith(S4I_MAGIC):
        raise ValueError("Not an encrypted Simdex install file")
    payload = json.loads(data[len(S4I_MAGIC):].decode("utf-8"))
    salt = base64.b64decode(payload["salt"])
    nonce = base64.b64decode(payload["nonce"])
    encrypted = base64.b64decode(payload["data"])
    return AESGCM(encryption_key(project_id, salt)).decrypt(nonce, encrypted, project_id.encode("utf-8"))


def hide_file(path):
    if os.name == "nt":
        set_hidden_file(path, True)


def unhide_file(path):
    if os.name == "nt" and path.exists():
        set_hidden_file(path, False)


def set_hidden_file(path, hidden):
    attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
    if attrs == INVALID_FILE_ATTRIBUTES:
        return
    if hidden:
        attrs |= FILE_ATTRIBUTE_HIDDEN
    else:
        attrs &= ~FILE_ATTRIBUTE_HIDDEN
    ctypes.windll.kernel32.SetFileAttributesW(str(path), attrs)


def hide_metadata_file(project):
    metadata_path = project / ".metadata"
    if metadata_path.exists():
        hide_file(metadata_path)


def folder_has_files(path):
    return path.exists() and any(item.is_file() for item in path.rglob("*"))


def relative_files(path):
    if not path.exists():
        return []
    return sorted(str(file.relative_to(path)) for file in path.rglob("*") if file.is_file())


def insert_markdown(text_widget, markdown):
    text_widget.tag_configure("h1", font=("Segoe UI", 16, "bold"))
    text_widget.tag_configure("h2", font=("Segoe UI", 14, "bold"))
    text_widget.tag_configure("h3", font=("Segoe UI", 12, "bold"))
    text_widget.tag_configure("bold", font=("Segoe UI", 10, "bold"))
    for line in markdown.splitlines():
        if line.startswith("# "):
            text_widget.insert("end", line[2:] + "\n", "h1")
        elif line.startswith("## "):
            text_widget.insert("end", line[3:] + "\n", "h2")
        elif line.startswith("### "):
            text_widget.insert("end", line[4:] + "\n", "h3")
        elif line.startswith("- "):
            text_widget.insert("end", "- " + line[2:] + "\n")
        else:
            insert_inline_markdown(text_widget, line)
            text_widget.insert("end", "\n")


def insert_inline_markdown(text_widget, line):
    parts = re.split(r"(\*\*.+?\*\*)", line)
    for part in parts:
        if part.startswith("**") and part.endswith("**"):
            text_widget.insert("end", part[2:-2], "bold")
        else:
            text_widget.insert("end", part)


def validate_metadata(metadata):
    required = ["name", "short_description", "author", "version", "download_page", "long_description"]
    missing = [field for field in required if not str(metadata.get(field, "")).strip()]
    if missing:
        raise ValueError("Missing metadata: " + ", ".join(missing))


def extract_archive(archive, target):
    target = target.resolve()
    for member in archive.infolist():
        destination = (target / member.filename).resolve()
        if target != destination and target not in destination.parents:
            raise ValueError("Archive contains unsafe paths")
    archive.extractall(target)


class ScrollableTabs(ttk.Frame):
    def __init__(self, parent, on_select):
        super().__init__(parent)
        self.on_select = on_select
        self.tabs = {}
        self.active_name = None

        self.canvas = tk.Canvas(self, height=34, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.inner = ttk.Frame(self.canvas)
        self.window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(xscrollcommand=self.scrollbar.set)
        self.canvas.pack(fill="x", expand=True)
        self.scrollbar.pack(fill="x")
        self.inner.bind("<Configure>", self._sync)
        self.canvas.bind("<Configure>", self._resize)

    def _sync(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _resize(self, event):
        self.canvas.itemconfigure(self.window, height=event.height)

    def add_tab(self, name, closable=False, close_command=None):
        if name in self.tabs:
            self.select(name)
            return

        frame = ttk.Frame(self.inner)
        button = ttk.Button(frame, text=name, command=lambda: self.select(name))
        button.pack(side="left")
        close = None
        if closable:
            close = ttk.Button(frame, text="x", width=3, command=close_command)
            close.pack(side="left")
        frame.pack(side="left", padx=(0, 2), pady=2)
        self.tabs[name] = {"frame": frame, "button": button, "close": close}
        self.select(name)

    def remove_tab(self, name):
        tab = self.tabs.pop(name, None)
        if not tab:
            return
        tab["frame"].destroy()
        if self.active_name == name:
            next_name = "Main" if "Main" in self.tabs else next(iter(self.tabs), None)
            if next_name:
                self.select(next_name)

    def select(self, name):
        if name not in self.tabs:
            return
        self.active_name = name
        for tab_name, tab in self.tabs.items():
            state = "disabled" if tab_name == name else "normal"
            tab["button"].configure(state=state)
        self.on_select(name)


class VisualGuide:
    def __init__(self, app, title, steps):
        self.app = app
        self.title = title
        self.steps = steps
        self.index = 0
        self.window = None
        self.canvas = None
        self.controls = None
        self.bindings = []
        self.app_bindings = []
        self.transparent_color = "#010203"

    def start(self):
        if not self.steps:
            return
        if self.app.active_visual_guide:
            self.app.active_visual_guide.close()
        self.app.active_visual_guide = self
        self.window = tk.Toplevel(self.app)
        self.window.title(self.title)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.transient(self.app)
        try:
            self.window.attributes("-transparentcolor", self.transparent_color)
        except tk.TclError:
            pass
        self.bind("<Escape>", lambda _event: self.close())
        self.bind("<Right>", lambda _event: self.next_step())
        self.bind("<Left>", lambda _event: self.previous_step())
        self.bind("<space>", lambda _event: self.next_step())
        self.window.bind("<FocusOut>", lambda _event: self.window.after(100, self.hide_if_app_inactive))
        self.bind_app("<FocusIn>", lambda _event: self.restore())
        self.bind_app("<Configure>", lambda _event: self.redraw())
        self.show_step()

    def bind(self, sequence, command):
        self.bindings.append((sequence, self.window.bind_all(sequence, command, add=True)))

    def bind_app(self, sequence, command):
        self.app_bindings.append((sequence, self.app.bind(sequence, command, add=True)))

    def close(self):
        for sequence, binding in self.bindings:
            if self.window:
                self.window.unbind_all(sequence)
        self.bindings = []
        for sequence, binding in self.app_bindings:
            self.app.unbind(sequence, binding)
        self.app_bindings = []
        if self.controls and self.controls.winfo_exists():
            self.controls.destroy()
        if self.window and self.window.winfo_exists():
            self.window.destroy()
        if self.app.active_visual_guide is self:
            self.app.active_visual_guide = None

    def hide_if_app_inactive(self):
        if not self.window or not self.window.winfo_exists():
            return
        focused = self.app.focus_displayof()
        if focused is None:
            self.window.withdraw()

    def restore(self):
        if not self.window or not self.window.winfo_exists():
            return
        self.position_window()
        self.window.deiconify()
        self.window.update_idletasks()
        self.window.lift(self.app)

    def redraw(self):
        if self.window and self.window.winfo_exists() and self.window.state() != "withdrawn":
            self.show_step()

    def previous_step(self):
        if self.index > 0:
            self.index -= 1
            self.show_step()

    def next_step(self):
        if self.index >= len(self.steps) - 1:
            self.close()
            return
        self.index += 1
        self.show_step()

    def show_step(self):
        step = self.steps[self.index]
        panel = step.get("panel")
        if panel:
            self.app.tabs.select(panel)
            self.app.update_idletasks()
        self.app.update_idletasks()
        if self.canvas and self.canvas.winfo_exists():
            self.canvas.destroy()
        if self.controls and self.controls.winfo_exists():
            self.controls.destroy()
        width, height = self.position_window()
        self.canvas = tk.Canvas(self.window, width=width, height=height, highlightthickness=0, bg=self.transparent_color)
        self.canvas.pack(fill="both", expand=True)
        self.window.deiconify()
        self.window.update_idletasks()
        self.canvas.configure(width=width, height=height)
        self.draw_step(step)
        self.window.lift()
        self.window.focus_force()

    def position_window(self):
        self.app.update_idletasks()
        width = max(self.app.winfo_width(), 600)
        height = max(self.app.winfo_height(), 400)
        self.window.geometry(f"{width}x{height}+{self.app.winfo_rootx()}+{self.app.winfo_rooty()}")
        return width, height

    def step_widget(self, step):
        widget = step.get("widget")
        if callable(widget):
            widget = widget()
        if widget and widget.winfo_exists():
            return widget
        return None

    def widget_box(self, widget):
        root_x = self.app.winfo_rootx()
        root_y = self.app.winfo_rooty()
        x = widget.winfo_rootx() - root_x
        y = widget.winfo_rooty() - root_y
        return x, y, x + widget.winfo_width(), y + widget.winfo_height()

    def draw_step(self, step):
        width = self.canvas.winfo_width() or self.app.winfo_width()
        height = self.canvas.winfo_height() or self.app.winfo_height()
        widget = self.step_widget(step)
        target_x = width // 2
        target_y = height // 2
        if widget:
            x1, y1, x2, y2 = self.widget_box(widget)
            pad = 8
            self.canvas.create_rectangle(x1 - pad, y1 - pad, x2 + pad, y2 + pad, outline="#ffcc00", width=5, fill=self.transparent_color)
            target_x = (x1 + x2) // 2
            target_y = (y1 + y2) // 2

        card_width = min(460, width - 40)
        card_height = 190
        card_x = 24 if target_x > width // 2 else max(24, width - card_width - 24)
        card_y = 24 if target_y > height // 2 else max(24, height - card_height - 24)
        self.canvas.create_rectangle(card_x, card_y, card_x + card_width, card_y + card_height, fill="#fff1a8", outline="#1f1f1f", width=2)
        self.canvas.create_text(card_x + 16, card_y + 16, anchor="nw", text=step.get("title", self.title), fill="#111111", font=("Segoe UI", 14, "bold"), width=card_width - 32)
        self.canvas.create_text(card_x + 16, card_y + 52, anchor="nw", text=step.get("text", ""), fill="#111111", font=("Segoe UI", 10), width=card_width - 32)
        if self.index == 0:
            self.canvas.create_text(
                card_x + 16,
                card_y + card_height - 58,
                anchor="w",
                text="Tip: Next, Right arrow, or Space continues. Left arrow goes back. Escape closes.",
                fill="#3a3100",
                font=("Segoe UI", 9),
                width=card_width - 32
            )

        start_x = card_x + card_width // 2
        start_y = card_y + card_height // 2
        self.canvas.create_line(start_x, start_y, target_x, target_y, fill="#ffcc00", width=6, arrow="last", arrowshape=(18, 22, 8))

        self.controls = ttk.Frame(self.window)
        ttk.Button(self.controls, text="Back", command=self.previous_step, state="normal" if self.index else "disabled").pack(side="left", padx=(0, 6))
        ttk.Button(self.controls, text="Next" if self.index < len(self.steps) - 1 else "Done", command=self.next_step).pack(side="left", padx=(0, 6))
        ttk.Button(self.controls, text="Close", command=self.close).pack(side="left")
        self.canvas.create_window(card_x + card_width - 16, card_y + card_height - 16, anchor="se", window=self.controls)
        self.canvas.create_text(card_x + 16, card_y + card_height - 30, anchor="w", text=f"{self.index + 1} of {len(self.steps)}", fill="#111111", font=("Segoe UI", 9))


class SimdexApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Simdex - Windows")
        try:
            self.iconbitmap(default=str(bundled_path("simdex.ico")))
        except tk.TclError:
            pass
        self.geometry("1120x720")
        self.minsize(900, 560)

        APP_ROOT.mkdir(parents=True, exist_ok=True)
        PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)
        CREATOR_CACHE.mkdir(parents=True, exist_ok=True)
        DISABLED_MODS_ROOT.mkdir(parents=True, exist_ok=True)

        self.installed_mods = self.load_installed_mods()
        self.filtered_mod_ids = []
        self.selected_mod_ids = set()
        self.temp_panels = {}
        self.dragging = False
        self.drag_start = None
        self.hover_item = None
        self.hover_after = None
        self.tooltip = None

        self.current_project = None
        self.editing_file = None
        self.info_vars = {}
        self.info_bool_vars = {}
        self.info_bool_widgets = {}
        self.dependency_vars = {}
        self.dependency_projects = []
        self.creator_buttons = {}
        self.editing_approved_project = None
        self.creator_account = self.load_creator_account()
        self.approved_projects = []
        self.approved_project_paths = {}
        self.index_projects = []
        self.filtered_index_projects = []
        self.index_page = 1
        self.index_total_pages = 1
        self.index_total_projects = 0
        self.index_request_id = 0
        self.dragged_tree_path = None
        self.remote_refresh_running = False
        self.remote_refresh_pending = False
        self.creator_status_running = False
        self.creator_status_interval_ms = 15000
        self.install_jobs = []
        self.install_worker_running = False
        self.install_queue_window = None
        self.install_queue_tree = None
        self.install_progress = None
        self.install_status_var = tk.StringVar(value="")
        self.paused_install_ids = set()
        self.prioritized_install_id = None
        self.active_install_id = None
        self.active_visual_guide = None

        if self.has_creator_account():
            self.migrate_root_projects()
        self.build_ui()
        self.refresh_mod_list()
        self.refresh_remote_mod_states()
        self.refresh_index_projects()
        self.after(300, self.show_first_launch_terms_notice)
        self.after(1000, self.check_creator_account_status)

    def build_ui(self):
        topbar = ttk.Frame(self, padding=(8, 8, 8, 4))
        topbar.pack(fill="x")

        self.install_button = ttk.Button(topbar, text="Install", command=self.install_s4i)
        self.install_button.pack(side="left", padx=(0, 6))
        self.install_queue_button = ttk.Button(topbar, text="Install Queue", command=self.show_install_queue)
        self.install_queue_button.pack(side="left", padx=(0, 6))
        self.refresh_button = ttk.Button(topbar, text="Refresh List", command=self.refresh_lists)
        self.refresh_button.pack(side="left", padx=(0, 6))
        self.disable_selected_button = ttk.Button(topbar, text="Disable Selected", command=lambda: self.set_selected_mods_enabled(False))
        self.disable_selected_button.pack(side="left", padx=(0, 6))
        self.enable_selected_button = ttk.Button(topbar, text="Enable Selected", command=lambda: self.set_selected_mods_enabled(True))
        self.enable_selected_button.pack(side="left", padx=(0, 6))
        self.select_all_var = tk.BooleanVar(value=False)
        self.select_all_check = ttk.Checkbutton(topbar, text="Select All", variable=self.select_all_var, command=self.toggle_select_all)
        self.select_all_check.pack(side="left", padx=(0, 12))
        ttk.Label(topbar, text="Search").pack(side="left", padx=(0, 4))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self.refresh_mod_list())
        self.search_entry = ttk.Entry(topbar, textvariable=self.search_var)
        self.search_entry.pack(side="left", fill="x", expand=True)

        self.tabs = ScrollableTabs(self, self.show_panel)
        self.tabs.pack(fill="x", padx=8)

        self.panel_host = ttk.Frame(self, padding=8)
        self.panel_host.pack(fill="both", expand=True)

        self.main_panel = ttk.Frame(self.panel_host)
        self.index_panel = ttk.Frame(self.panel_host)
        self.creator_panel = ttk.Frame(self.panel_host)
        self.guides_panel = ttk.Frame(self.panel_host)
        self.build_main_panel()
        self.build_index_panel()
        self.build_creator_panel()
        self.build_guides_panel()

        self.tabs.add_tab("Main")
        self.tabs.add_tab("Mod Index")
        self.tabs.add_tab("Creator")
        self.tabs.add_tab("Guides")
        self.tabs.select("Main")

        footer = ttk.Frame(self, padding=(8, 4, 8, 8))
        footer.pack(fill="x")
        ttk.Label(footer, text="Simdex Terms of Service and Privacy Policy apply to this app.").pack(side="left")
        ttk.Button(footer, text="Privacy Policy", command=self.open_privacy_page).pack(side="right")
        ttk.Button(footer, text="Terms of Service", command=self.open_terms_page).pack(side="right")

    def open_terms_page(self):
        webbrowser.open(TERMS_URL)

    def open_privacy_page(self):
        webbrowser.open(PRIVACY_URL)

    def show_first_launch_terms_notice(self):
        try:
            state = read_json(APP_STATE_FILE) if APP_STATE_FILE.exists() else {}
        except (OSError, json.JSONDecodeError):
            state = {}
        if state.get("legal_notice_seen"):
            return
        messagebox.showinfo(
            "Simdex Legal Notices",
            "Please read the Simdex Terms of Service and Privacy Policy by clicking the links in the footer. "
            "These documents are stored on the official Simdex website, but they apply to this app too."
        )
        state["legal_notice_seen"] = True
        try:
            write_json(APP_STATE_FILE, state)
        except OSError:
            pass

    def show_panel(self, name):
        for child in self.panel_host.winfo_children():
            child.pack_forget()
        panels = {"Main": self.main_panel, "Mod Index": self.index_panel, "Creator": self.creator_panel, "Guides": self.guides_panel}
        panel = self.temp_panels.get(name, panels.get(name, self.main_panel))
        panel.pack(fill="both", expand=True)
        if name == "Creator":
            self.update_creator_gate()

    def build_main_panel(self):
        columns = ("selected", "name", "short_description", "author", "version", "type", "state")
        self.mod_tree = ttk.Treeview(self.main_panel, columns=columns, show="headings", selectmode="none")
        self.mod_tree.heading("selected", text="")
        self.mod_tree.heading("name", text="Name")
        self.mod_tree.heading("short_description", text="Short Description")
        self.mod_tree.heading("author", text="Author")
        self.mod_tree.heading("version", text="Version")
        self.mod_tree.heading("type", text="Type")
        self.mod_tree.heading("state", text="State")
        self.mod_tree.column("selected", width=48, stretch=False, anchor="center")
        self.mod_tree.column("name", width=200)
        self.mod_tree.column("short_description", width=370)
        self.mod_tree.column("author", width=150)
        self.mod_tree.column("version", width=90, stretch=False)
        self.mod_tree.column("type", width=110, stretch=False)
        self.mod_tree.column("state", width=95, stretch=False)

        scrollbar = ttk.Scrollbar(self.main_panel, orient="vertical", command=self.mod_tree.yview)
        self.mod_tree.configure(yscrollcommand=scrollbar.set)
        self.mod_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.mod_tree.tag_configure("broken", foreground="#b00020")
        self.mod_tree.tag_configure("missing", foreground="#9a6a00")
        self.mod_tree.tag_configure("obsolete", foreground="#b00020")
        self.mod_tree.tag_configure("disabled", foreground="#666666")
        self.mod_tree.bind("<Button-1>", self.on_mod_click)
        self.mod_tree.bind("<B1-Motion>", self.on_mod_drag)
        self.mod_tree.bind("<ButtonRelease-1>", self.on_mod_release)
        self.mod_tree.bind("<Double-1>", self.on_mod_double_click)
        self.mod_tree.bind("<Button-3>", self.on_mod_right_click)
        self.mod_tree.bind("<Motion>", self.on_mod_hover)
        self.mod_tree.bind("<Leave>", self.hide_tooltip)

        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="Disable", command=lambda: self.set_context_mod_enabled(False))
        self.context_menu.add_command(label="Enable", command=lambda: self.set_context_mod_enabled(True))
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Uninstall", command=self.uninstall_context_mod)
        self.context_mod_id = None

    def load_creator_account(self):
        try:
            data = read_json(CREATOR_ACCOUNT_FILE)
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def save_creator_account(self, account):
        self.creator_account = account
        write_json(CREATOR_ACCOUNT_FILE, account)
        if hasattr(self, "creator_account_label"):
            self.update_creator_account_label()
        self.update_creator_gate()

    def clear_creator_account(self, message=""):
        self.creator_account = {}
        try:
            CREATOR_ACCOUNT_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        self.editing_approved_project = None
        self.approved_projects = []
        self.approved_project_paths = {}
        if hasattr(self, "approved_tree"):
            self.approved_tree.delete(*self.approved_tree.get_children())
        if hasattr(self, "creator_account_label"):
            self.update_creator_account_label()
        self.update_creator_gate()
        if message:
            messagebox.showerror("Creator Account", message)

    def check_creator_account_status(self):
        if self.creator_status_running:
            self.after(self.creator_status_interval_ms, self.check_creator_account_status)
            return
        if not self.has_creator_account():
            self.after(self.creator_status_interval_ms, self.check_creator_account_status)
            return

        token = self.creator_token()
        self.creator_status_running = True

        def check():
            try:
                response = api_json("/api/creator/me", token=token)
            except ValueError as error:
                message = str(error)
                if "API request failed (401)" in message or "API request failed (403)" in message:
                    return {"error": message}
                return {}
            except (OSError, json.JSONDecodeError):
                return {}
            account = response.get("account", {})
            account["token"] = token
            return {"account": account}

        def checked(result):
            self.creator_status_running = False
            if result.get("account"):
                if self.creator_token() == token:
                    self.creator_account = result["account"]
                    write_json(CREATOR_ACCOUNT_FILE, self.creator_account)
                    if hasattr(self, "creator_account_label"):
                        self.update_creator_account_label()
                    if hasattr(self, "verify_button"):
                        self.verify_button.configure(state="disabled" if self.creator_account.get("verified") else "normal")
            elif result.get("error") and self.creator_token() == token:
                self.clear_creator_account("Your creator account is no longer available. You have been logged out.")
            self.after(self.creator_status_interval_ms, self.check_creator_account_status)

        self.run_background_task("Creator Account", check, checked)

    def creator_token(self):
        return self.creator_account.get("token", "")

    def creator_username(self):
        username = self.creator_account.get("username")
        if username:
            return username
        email = self.creator_account.get("email", "")
        return email.split("@", 1)[0] if email else ""

    def has_creator_account(self):
        return bool(self.creator_token() and self.creator_username())

    def require_creator_account(self):
        if self.has_creator_account():
            return True
        messagebox.showerror("Creator Account", "Sign in to a creator account first.")
        self.show_creator_gate()
        return False

    def update_creator_account_label(self):
        if not hasattr(self, "creator_account_label"):
            return
        username = self.creator_username()
        suffix = VERIFIED_BADGE if self.creator_account.get("verified") else ""
        self.creator_account_label.configure(text=f"Logged in: {username}{suffix}" if username else "Creator account: not logged in")
        self.creator_account_label.unbind("<Enter>")
        self.creator_account_label.unbind("<Leave>")
        if self.creator_account.get("verified"):
            self.creator_account_label.bind("<Enter>", lambda event: self.show_tooltip(event.x_root + 12, event.y_root + 12, VERIFIED_CREATOR_TOOLTIP))
            self.creator_account_label.bind("<Leave>", self.hide_tooltip)

    def migrate_root_projects(self):
        PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)
        for item in APP_ROOT.iterdir():
            if not item.is_dir() or item.name in APP_MANAGED_FOLDERS:
                continue
            if not (item / ".metadata").exists():
                continue
            target = PROJECTS_ROOT / item.name
            if target.exists():
                hide_metadata_file(item)
                continue
            shutil.move(str(item), str(target))
            hide_metadata_file(target)
            if self.current_project == item:
                self.current_project = target

    def build_index_panel(self):
        controls = ttk.Frame(self.index_panel)
        self.index_controls = controls
        controls.pack(fill="x", pady=(0, 8))
        ttk.Label(controls, text="Search").pack(side="left", padx=(0, 4))
        self.index_search_var = tk.StringVar()
        self.index_search_var.trace_add("write", lambda *_: self.refresh_index_list())
        ttk.Entry(controls, textvariable=self.index_search_var).pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.index_type_var = tk.StringVar(value="All")
        ttk.Combobox(controls, textvariable=self.index_type_var, values=("All", "Mods", "Modpacks"), state="readonly", width=12).pack(side="left", padx=(0, 8))
        self.index_type_var.trace_add("write", lambda *_: self.refresh_index_list())
        self.index_obsolete_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(controls, text="Show obsolete", variable=self.index_obsolete_var, command=self.refresh_index_list).pack(side="left", padx=(0, 8))
        self.index_verified_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(controls, text="Verified Creators Only", variable=self.index_verified_var, command=self.refresh_index_list).pack(side="left", padx=(0, 8))
        ttk.Button(controls, text="Refresh", command=self.refresh_index_projects).pack(side="left")

        columns = ("name", "short_description", "author", "version", "type", "status")
        tree_frame = ttk.Frame(self.index_panel)
        tree_frame.pack(fill="both", expand=True)
        self.index_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse")
        self.index_tree.heading("name", text="Name")
        self.index_tree.heading("short_description", text="Short Description")
        self.index_tree.heading("author", text="Author")
        self.index_tree.heading("version", text="Version")
        self.index_tree.heading("type", text="Type")
        self.index_tree.heading("status", text="Status")
        self.index_tree.column("name", width=200)
        self.index_tree.column("short_description", width=370)
        self.index_tree.column("author", width=150)
        self.index_tree.column("version", width=90, stretch=False)
        self.index_tree.column("type", width=110, stretch=False)
        self.index_tree.column("status", width=90, stretch=False)
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.index_tree.yview)
        self.index_tree.configure(yscrollcommand=scrollbar.set)
        self.index_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.index_pages_frame = ttk.Frame(self.index_panel)
        self.index_pages_frame.pack(fill="x", pady=(8, 0))
        self.index_tree.tag_configure("obsolete", foreground="#b00020")
        self.index_tree.bind("<ButtonRelease-1>", self.on_index_open)
        self.index_tree.bind("<Double-1>", self.on_index_open)
        self.index_tree.bind("<Return>", self.on_index_open)
        self.index_tree.bind("<Motion>", lambda event: self.on_author_badge_hover(event, self.index_tree, self.index_projects, "#3", self.index_row_id))
        self.index_tree.bind("<Leave>", self.hide_tooltip)

    def load_installed_mods(self):
        if not INSTALLS_FILE.exists():
            return []
        try:
            data = read_json(INSTALLS_FILE)
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def save_installed_mods(self):
        write_json(INSTALLS_FILE, self.installed_mods)

    def run_background_task(self, title, work, on_success=None):
        def finish_success(result):
            if on_success:
                on_success(result)

        def finish_error(error):
            messagebox.showerror(title, str(error))

        def run():
            try:
                result = work()
            except Exception as error:
                self.after(0, lambda error=error: finish_error(error))
                return
            self.after(0, lambda result=result: finish_success(result))

        threading.Thread(target=run, daemon=True).start()

    def refresh_lists(self):
        self.refresh_mod_list()
        self.refresh_remote_mod_states()
        self.refresh_index_projects()
        self.refresh_approved_projects()

    def refresh_index_projects(self):
        if not hasattr(self, "index_tree"):
            return
        self.index_request_id += 1
        request_id = self.index_request_id
        query = self.index_search_var.get().strip() if hasattr(self, "index_search_var") else ""
        kind = self.index_type_var.get() if hasattr(self, "index_type_var") else "All"
        show_obsolete = self.index_obsolete_var.get() if hasattr(self, "index_obsolete_var") else False
        verified_only = self.index_verified_var.get() if hasattr(self, "index_verified_var") else True
        project_type = "mod" if kind == "Mods" else "modpack" if kind == "Modpacks" else "all"
        params = {
            "paged": "1",
            "page": str(self.index_page),
            "q": query,
            "type": project_type
        }
        if show_obsolete:
            params["obsolete"] = "1"
        if not verified_only:
            params["verified"] = "0"

        def load():
            return api_json(f"/api/projects?{urlencode(params)}")

        def apply(response):
            if request_id != self.index_request_id:
                return
            self.index_projects = response.get("projects", [])
            self.index_page = int(response.get("page") or 1)
            self.index_total_pages = int(response.get("total_pages") or 1)
            self.index_total_projects = int(response.get("total") or 0)
            self.render_index_list()
            self.render_index_pages()
            self.refresh_dependency_choices()

        self.run_background_task("Mod Index", load, apply)

    def refresh_index_list(self):
        if not hasattr(self, "index_tree"):
            return
        self.index_page = 1
        self.refresh_index_projects()

    def render_index_list(self):
        self.index_tree.delete(*self.index_tree.get_children())
        self.filtered_index_projects = []
        for project in self.index_projects:
            row_id = self.index_row_id(project)
            self.filtered_index_projects.append(project)
            self.index_tree.insert(
                "",
                "end",
                iid=row_id,
                values=(
                    project.get("name", ""),
                    project.get("short_description", ""),
                    author_display(project),
                    project.get("version", ""),
                    metadata_type(project),
                    "Obsolete" if project.get("obsolete") else "Active"
                ),
                tags=("obsolete",) if project.get("obsolete") else ()
            )

    def render_index_pages(self):
        if not hasattr(self, "index_pages_frame"):
            return
        for child in self.index_pages_frame.winfo_children():
            child.destroy()
        ttk.Button(
            self.index_pages_frame,
            text="Previous",
            command=lambda: self.open_index_page(self.index_page - 1),
            state="normal" if self.index_page > 1 else "disabled"
        ).pack(side="left", padx=(0, 8))
        for page in range(1, self.index_total_pages + 1):
            ttk.Button(
                self.index_pages_frame,
                text=str(page),
                command=lambda page=page: self.open_index_page(page),
                state="disabled" if page == self.index_page else "normal",
                width=3
            ).pack(side="left", padx=(0, 4))
        ttk.Button(
            self.index_pages_frame,
            text="Next",
            command=lambda: self.open_index_page(self.index_page + 1),
            state="normal" if self.index_page < self.index_total_pages else "disabled"
        ).pack(side="left", padx=(8, 0))
        start = ((self.index_page - 1) * INDEX_PAGE_SIZE) + 1 if self.index_total_projects else 0
        end = min(self.index_page * INDEX_PAGE_SIZE, self.index_total_projects)
        ttk.Label(
            self.index_pages_frame,
            text=f"{start}-{end} of {self.index_total_projects}"
        ).pack(side="right")

    def open_index_page(self, page):
        page = max(1, min(page, self.index_total_pages))
        if page == self.index_page:
            return
        self.index_page = page
        self.refresh_index_projects()

    def latest_index_projects(self, projects):
        grouped = {}
        for project in projects:
            key = self.project_identity_key(project)
            current = grouped.get(key)
            if not current or self.version_sort_key(project) > self.version_sort_key(current):
                grouped[key] = project
        return sorted(grouped.values(), key=self.index_sort_key)

    def index_sort_key(self, project):
        return (str(project.get("name", "")).lower(), self.version_sort_key(project))

    def version_sort_key(self, project):
        parts = []
        for part in str(project.get("version", "")).split("."):
            try:
                parts.append(int(part))
            except ValueError:
                parts.append(0)
        return tuple(parts)

    def index_row_id(self, project):
        return f"{project.get('id', '')}::{project.get('version', '')}"

    def on_index_open(self, event):
        item_id = ""
        if getattr(event, "keysym", "") == "Return":
            selected = self.index_tree.selection()
            item_id = selected[0] if selected else ""
        elif hasattr(event, "y"):
            item_id = self.index_tree.identify_row(event.y)
        if not item_id:
            return "break"
        project = next((item for item in self.index_projects if self.index_row_id(item) == item_id), None)
        if not project:
            return "break"
        installed = self.find_installed_version({
            "project_id": project.get("id"),
            "name": project.get("name"),
            "author": project.get("author"),
            "version": project.get("version")
        })
        self.open_project_panel(project, installed)
        return "break"

    def refresh_mod_list(self):
        query = self.search_var.get().strip().lower() if hasattr(self, "search_var") else ""
        self.mod_tree.delete(*self.mod_tree.get_children())
        self.filtered_mod_ids = []

        changed = False
        for mod in self.installed_mods:
            old_status = mod.get("status")
            self.update_mod_status(mod)
            changed = changed or old_status != mod.get("status")
        self.installed_mods.sort(key=lambda item: (not item.get("favorite", False), item.get("name", "").lower()))

        for mod in self.installed_mods:
            if mod.get("modpack_parent_id"):
                continue
            haystack = " ".join(str(mod.get(key, "")) for key in ("name", "short_description", "author", "version")).lower()
            if query and query not in haystack:
                continue
            mod_id = mod["id"]
            self.filtered_mod_ids.append(mod_id)
            selected = "[x]" if mod_id in self.selected_mod_ids else "[ ]"
            tags = ()
            if mod.get("status") == "broken":
                tags = ("broken",)
            elif mod.get("status") == "missing":
                tags = ("missing",)
            elif mod.get("obsolete"):
                tags = ("obsolete",)
            elif not mod.get("enabled", True):
                tags = ("disabled",)
            self.mod_tree.insert(
                "",
                "end",
                iid=mod_id,
                values=(
                    selected,
                    mod.get("name", ""),
                    mod.get("short_description", ""),
                    author_display(mod),
                    mod.get("version", ""),
                    metadata_type(mod),
                    self.mod_state_text(mod)
                ),
                tags=tags
            )

        if hasattr(self, "select_all_var"):
            self.select_all_var.set(bool(self.filtered_mod_ids) and set(self.filtered_mod_ids).issubset(self.selected_mod_ids))
        if changed:
            self.save_installed_mods()

    def refresh_remote_mod_states(self):
        if self.remote_refresh_running:
            self.remote_refresh_pending = True
            return
        mods = [
            {
                "id": mod.get("id"),
                "project_id": mod.get("project_id"),
                "version": mod.get("version")
            }
            for mod in self.installed_mods
            if mod.get("id") and mod.get("project_id") and mod.get("version")
        ]
        if not mods:
            return

        self.remote_refresh_running = True
        thread = threading.Thread(target=self.load_remote_mod_states, args=(mods,), daemon=True)
        thread.start()

    def load_remote_mod_states(self, mods):
        states = {}
        mod_ids_by_project = {
            (mod["project_id"], mod["version"]): mod["id"]
            for mod in mods
        }
        try:
            response = api_json(
                "/api/projects/status",
                method="POST",
                payload={
                    "projects": [
                        {"id": mod["project_id"], "version": mod["version"]}
                        for mod in mods
                    ]
                }
            )
            for project in response.get("projects", []):
                key = (
                    str(project.get("id", "")),
                    str(project.get("version", ""))
                )
                mod_id = mod_ids_by_project.get(key)
                if mod_id:
                    states[mod_id] = project
            self.after(0, lambda: self.apply_remote_mod_states(states))
            return
        except (OSError, ValueError, json.JSONDecodeError):
            pass

        for mod in mods:
            try:
                response = api_json(
                    f"/api/projects/{quote(mod['project_id'])}?include_obsolete=1&version={quote(mod['version'])}"
                )
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            project = response.get("project")
            if project and project.get("version") == mod["version"]:
                states[mod["id"]] = project
        self.after(0, lambda: self.apply_remote_mod_states(states))

    def apply_remote_mod_states(self, states):
        for mod in self.installed_mods:
            state = states.get(mod.get("id"))
            if state:
                self.apply_approved_metadata(mod, state)
        self.remote_refresh_running = False
        self.save_installed_mods()
        self.refresh_mod_list()
        if self.remote_refresh_pending:
            self.remote_refresh_pending = False
            self.refresh_remote_mod_states()

    def apply_approved_metadata(self, mod, project):
        for key in (
            "name",
            "short_description",
            "author",
            "version",
            "download_page",
            "icon",
            "long_description",
            "dependencies"
        ):
            if key in project:
                mod[key] = project.get(key, [] if key == "dependencies" else "")
        mod["is_mod"] = bool(project.get("is_mod"))
        mod["is_modpack"] = bool(project.get("is_modpack"))
        mod["obsolete"] = bool(project.get("obsolete"))
        mod["creator_verified"] = bool(project.get("creator_verified"))
        if project.get("icon"):
            mod["icon_path"] = None

    def update_mod_status(self, mod):
        if mod.get("is_modpack"):
            self.update_modpack_status(mod)
            return
        paths = mod.get("installed_paths", {})
        if not mod.get("enabled", True):
            disabled_paths = self.mod_disabled_paths(mod)
            active_paths = [Path(path) for path in disabled_paths.values() if path]
            if not active_paths:
                mod["status"] = "missing"
                return
            folder_exists = [path.exists() for path in active_paths]
            file_exists = []
            expected_files = mod.get("installed_files", {})
            for key, folder in disabled_paths.items():
                folder_path = Path(folder)
                for relative_path in expected_files.get(key, []):
                    file_exists.append((folder_path / relative_path).exists())
            files_ok = all(file_exists) if file_exists else True
            mod["status"] = "disabled" if all(folder_exists) and files_ok else "missing"
            return

        active_paths = [Path(path) for path in paths.values() if path]
        if not active_paths:
            mod["status"] = "missing"
            return
        folder_exists = [path.exists() for path in active_paths]
        file_exists = []
        expected_files = mod.get("installed_files", {})
        for key, folder in paths.items():
            folder_path = Path(folder)
            for relative_path in expected_files.get(key, []):
                file_exists.append((folder_path / relative_path).exists())

        files_ok = all(file_exists) if file_exists else True
        if all(folder_exists) and files_ok:
            mod["status"] = "ok"
        elif len(active_paths) == 1:
            mod["status"] = "missing"
        else:
            mod["status"] = "broken"

    def update_modpack_status(self, modpack):
        items = modpack.get("modpack_items", [])
        if not items:
            modpack["status"] = "missing"
            return
        statuses = [self.modpack_item_status(item) for item in items]
        if statuses and all(status in {"Installed", "Outdated"} for status in statuses):
            modpack["status"] = "ok"
        elif any(status in {"Installed", "Outdated"} for status in statuses):
            modpack["status"] = "broken"
        else:
            modpack["status"] = "missing"

    def mod_state_text(self, mod):
        if not mod.get("enabled", True):
            return "Disabled"
        if mod.get("status") == "broken":
            return "Broken"
        if mod.get("status") == "missing":
            return "Missing"
        if mod.get("obsolete"):
            return "Obsolete"
        return "Enabled"

    def toggle_select_all(self):
        if self.select_all_var.get():
            self.selected_mod_ids.update(self.filtered_mod_ids)
        else:
            self.selected_mod_ids.difference_update(self.filtered_mod_ids)
        self.refresh_mod_list()

    def set_context_mod_enabled(self, enabled):
        if not self.context_mod_id:
            return
        self.selected_mod_ids = {self.context_mod_id}
        self.set_selected_mods_enabled(enabled)

    def set_selected_mods_enabled(self, enabled):
        selected = [mod for mod in self.installed_mods if mod.get("id") in self.selected_mod_ids]
        selected = [mod for mod in selected if mod.get("enabled", True) != enabled]
        if not selected:
            action = "enable" if enabled else "disable"
            messagebox.showinfo("Mods", f"No selected projects need to be {action}d.")
            return
        prompt = (
            "Close The Sims 4 before continuing. Moving mod files while the game is running can fail.\n\n"
            f"Do you want to {'enable' if enabled else 'disable'} {len(selected)} selected project(s)?"
        )
        if not messagebox.askyesno("The Sims 4", prompt):
            return
        try:
            for mod in selected:
                self.set_mod_enabled(mod, enabled)
        except OSError as error:
            self.save_installed_mods()
            messagebox.showerror("Mods", str(error))
            self.refresh_mod_list()
            return
        self.save_installed_mods()
        self.refresh_mod_list()

    def set_mod_enabled(self, mod, enabled):
        if enabled:
            self.enable_mod(mod)
        else:
            self.disable_mod(mod)

    def mod_disabled_paths(self, mod):
        disabled_paths = mod.get("disabled_paths")
        if isinstance(disabled_paths, dict) and disabled_paths:
            return disabled_paths
        root = DISABLED_MODS_ROOT / self.disabled_folder_name(mod)
        return {
            key: str(root / key)
            for key, path in mod.get("installed_paths", {}).items()
            if path
        }

    def disabled_folder_name(self, mod):
        return app_slug(mod.get("id") or f"{mod.get('author', '')}-{mod.get('name', '')}-{mod.get('version', '')}")

    def disable_mod(self, mod):
        disabled_paths = self.mod_disabled_paths(mod)
        moved = []
        try:
            for key, path_text in mod.get("installed_paths", {}).items():
                source = Path(path_text)
                target = Path(disabled_paths[key])
                if not source.exists():
                    raise OSError(f"Cannot disable {mod.get('name', 'project')}: missing {source}")
                if target.exists():
                    shutil.rmtree(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(target))
                moved.append((source, target))
            mod["disabled_paths"] = disabled_paths
            mod["enabled"] = False
            mod["status"] = "disabled"
            self.verify_mod_files(mod, disabled_paths)
        except OSError:
            for source, target in reversed(moved):
                if target.exists():
                    source.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(target), str(source))
            mod["enabled"] = True
            raise

    def enable_mod(self, mod):
        disabled_paths = self.mod_disabled_paths(mod)
        moved = []
        try:
            for key, path_text in mod.get("installed_paths", {}).items():
                source = Path(disabled_paths[key])
                target = Path(path_text)
                if not source.exists():
                    raise OSError(f"Cannot enable {mod.get('name', 'project')}: missing {source}")
                if target.exists():
                    raise OSError(f"Cannot enable {mod.get('name', 'project')}: target already exists: {target}")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(target))
                moved.append((source, target))
            mod["enabled"] = True
            mod["status"] = "ok"
            self.verify_mod_files(mod, mod.get("installed_paths", {}))
        except OSError:
            for source, target in reversed(moved):
                if target.exists():
                    source.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(target), str(source))
            mod["enabled"] = False
            raise

    def verify_mod_files(self, mod, paths):
        for key, folder in paths.items():
            folder_path = Path(folder)
            if not folder_path.exists():
                raise OSError(f"Missing folder: {folder_path}")
            for relative_path in mod.get("installed_files", {}).get(key, []):
                file_path = folder_path / relative_path
                if not file_path.exists():
                    raise OSError(f"Missing file: {file_path}")

    def on_mod_click(self, event):
        item_id = self.mod_tree.identify_row(event.y)
        column = self.mod_tree.identify_column(event.x)
        self.dragging = False
        self.drag_start = item_id
        if item_id and column == "#1":
            if item_id in self.selected_mod_ids:
                self.selected_mod_ids.remove(item_id)
            else:
                self.selected_mod_ids.add(item_id)
            self.refresh_mod_list()
            return "break"
        return "break"

    def on_mod_drag(self, event):
        item_id = self.mod_tree.identify_row(event.y)
        if not item_id or not self.drag_start:
            return "break"
        self.dragging = True
        start_index = self.filtered_mod_ids.index(self.drag_start)
        current_index = self.filtered_mod_ids.index(item_id)
        low, high = sorted((start_index, current_index))
        self.selected_mod_ids = set(self.filtered_mod_ids[low:high + 1])
        self.refresh_mod_list()
        return "break"

    def on_mod_release(self, _event):
        self.dragging = False
        self.drag_start = None
        return "break"

    def on_mod_double_click(self, event):
        item_id = self.mod_tree.identify_row(event.y)
        column = self.mod_tree.identify_column(event.x)
        if item_id and column != "#1":
            self.open_mod_panel(item_id)
        return "break"

    def on_mod_right_click(self, event):
        item_id = self.mod_tree.identify_row(event.y)
        if not item_id:
            return
        self.context_mod_id = item_id
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def on_mod_hover(self, event):
        item_id = self.mod_tree.identify_row(event.y)
        column = self.mod_tree.identify_column(event.x)
        hover_key = ("mod", item_id, column)
        if hover_key == self.hover_item:
            return
        self.hover_item = hover_key
        self.clear_tooltip()
        mod = self.find_mod(item_id)
        message = ""
        if mod:
            if column == "#4" and mod.get("creator_verified"):
                message = VERIFIED_CREATOR_TOOLTIP
            elif mod.get("status") == "broken":
                message = "Broken: an installed folder or file is missing."
            elif mod.get("status") == "missing":
                message = "Uninstalled incorrectly or missing files. Right click and choose uninstall."
            elif mod.get("status") == "disabled":
                message = "Disabled: files are stored outside The Sims 4 folders."
            elif mod.get("obsolete"):
                message = "This installed version is obsolete."
        if message:
            self.hover_after = self.after(500, lambda: self.show_tooltip(event.x_root + 12, event.y_root + 12, message))

    def on_author_badge_hover(self, event, tree, projects, author_column, row_id):
        item_id = tree.identify_row(event.y)
        column = tree.identify_column(event.x)
        hover_key = (str(tree), item_id, column)
        if hover_key == self.hover_item:
            return
        self.hover_item = hover_key
        self.clear_tooltip()
        if column != author_column:
            return
        project = next((item for item in projects if row_id(item) == item_id), None)
        if project and project.get("creator_verified"):
            self.hover_after = self.after(500, lambda: self.show_tooltip(event.x_root + 12, event.y_root + 12, VERIFIED_CREATOR_TOOLTIP))

    def show_tooltip(self, x, y, message):
        self.clear_tooltip()
        self.tooltip = tk.Toplevel(self)
        self.tooltip.wm_overrideredirect(True)
        self.tooltip.wm_geometry(f"+{x}+{y}")
        ttk.Label(self.tooltip, text=message, padding=6, relief="solid", borderwidth=1).pack()

    def clear_tooltip(self):
        if self.hover_after:
            self.after_cancel(self.hover_after)
            self.hover_after = None
        if self.tooltip:
            self.tooltip.destroy()
            self.tooltip = None

    def hide_tooltip(self, _event=None):
        self.hover_item = None
        self.clear_tooltip()

    def create_verified_badge(self, parent):
        badge = ttk.Label(parent, text=VERIFIED_BADGE, foreground="#2f80ff")
        badge.bind("<Enter>", lambda event: self.show_tooltip(event.x_root + 12, event.y_root + 12, VERIFIED_CREATOR_TOOLTIP))
        badge.bind("<Leave>", self.hide_tooltip)
        return badge

    def find_mod(self, mod_id):
        return next((mod for mod in self.installed_mods if mod.get("id") == mod_id), None)

    def open_mod_panel(self, mod_id):
        mod = self.find_mod(mod_id)
        if not mod:
            return
        self.open_project_panel(mod, mod)

    def open_project_panel(self, project, installed_mod=None):
        panel_id = installed_mod.get("id") if installed_mod else self.index_row_id(project)
        tab_name = f"{project.get('name', 'Mod')} {project.get('version', '')} ({panel_id[:8]})"
        if tab_name in self.temp_panels:
            self.tabs.select(tab_name)
            return

        panel = ttk.Frame(self.panel_host)
        top = ttk.Frame(panel, padding=(0, 0, 0, 10))
        top.pack(fill="x")

        icon_holder = ttk.Label(top, text="Icon", relief="groove", anchor="center", width=18)
        icon_holder.pack(side="left", padx=(0, 12), pady=(4, 0))
        self.load_panel_icon(icon_holder, installed_mod or project)

        text_area = ttk.Frame(top)
        text_area.pack(side="left", fill="x", expand=True)
        ttk.Label(text_area, text=project.get("name", ""), font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(text_area, text=project.get("short_description", ""), font=("Segoe UI", 10, "bold"), wraplength=560).pack(anchor="w", pady=(8, 0))
        author_row = ttk.Frame(text_area)
        author_row.pack(anchor="w", pady=(8, 0))
        ttk.Label(author_row, text=f"Author: {project.get('author', '')}").pack(side="left")
        if project.get("creator_verified"):
            self.create_verified_badge(author_row).pack(side="left")
        ttk.Label(text_area, text=f"Version: {project.get('version', '')}").pack(anchor="w")
        other_install = None if installed_mod else self.find_existing_install({
            "project_id": project.get("id"),
            "name": project.get("name"),
            "author": project.get("author"),
            "version": project.get("version")
        })
        if other_install:
            ttk.Label(
                text_area,
                text=f"Another version is installed: {other_install.get('version', '')}",
                foreground="#b00020"
            ).pack(anchor="w", pady=(6, 0))

        actions = ttk.Frame(top)
        actions.pack(side="right", padx=(14, 0), anchor="ne")
        if installed_mod:
            fav_text = "Unfavorite" if installed_mod.get("favorite") else "Favorite"
            ttk.Button(actions, text=fav_text, command=lambda: self.toggle_favorite(installed_mod["id"], tab_name)).pack(fill="x", pady=(0, 6))
            ttk.Button(actions, text="Uninstall", command=lambda: self.uninstall_mod(installed_mod["id"])).pack(fill="x")
        else:
            download_page = project.get("download_page", "")
            ttk.Button(actions, text="Download", command=lambda url=download_page: self.open_download_page(url), state="normal" if download_page else "disabled").pack(fill="x")

        ttk.Separator(panel, orient="horizontal").pack(fill="x", pady=(0, 10))
        body = ttk.PanedWindow(panel, orient="horizontal")
        body.pack(fill="both", expand=True)

        description = tk.Text(body, wrap="word", height=20)
        insert_markdown(description, project.get("long_description", ""))
        description.configure(state="disabled")
        body.add(description, weight=3)

        if project.get("is_modpack"):
            mods_frame = ttk.LabelFrame(body, text="Mods", padding=6)
            mods_tree = ttk.Treeview(mods_frame, columns=("name", "author", "version", "status"), show="headings", height=10, selectmode="browse")
            mods_tree.heading("name", text="Name")
            mods_tree.heading("author", text="Author")
            mods_tree.heading("version", text="Version")
            mods_tree.heading("status", text="Status")
            mods_tree.column("name", width=140)
            mods_tree.column("author", width=90)
            mods_tree.column("version", width=70, stretch=False)
            mods_tree.column("status", width=85, stretch=False)
            mods_tree.pack(fill="both", expand=True)
            mod_rows = {}
            for item in project.get("modpack_items", []):
                row_id = self.dependency_key(item)
                mod_rows[row_id] = item
                mods_tree.insert("", "end", iid=row_id, values=(item.get("name", ""), item.get("author", ""), item.get("version", ""), self.modpack_item_status(item)))
            mods_tree.bind("<Double-1>", lambda event, tree=mods_tree, rows=mod_rows: self.open_project_ref_from_tree(event, tree, rows))
            mods_tree.bind("<Return>", lambda event, tree=mods_tree, rows=mod_rows: self.open_project_ref_from_tree(event, tree, rows))
            mods_tree.bind("<Button-3>", lambda event, tree=mods_tree, rows=mod_rows: self.on_modpack_item_right_click(event, tree, rows))
            body.add(mods_frame, weight=1)
        elif project.get("dependencies"):
            dependencies_frame = ttk.LabelFrame(body, text="Dependencies", padding=6)
            dependencies_tree = ttk.Treeview(dependencies_frame, columns=("name", "author", "version"), show="headings", height=10, selectmode="browse")
            dependencies_tree.heading("name", text="Name")
            dependencies_tree.heading("author", text="Author")
            dependencies_tree.heading("version", text="Version")
            dependencies_tree.column("name", width=140)
            dependencies_tree.column("author", width=90)
            dependencies_tree.column("version", width=70, stretch=False)
            dependencies_tree.pack(fill="both", expand=True)
            dependency_rows = {}
            for item in project.get("dependencies", []):
                row_id = self.dependency_key(item)
                dependency_rows[row_id] = item
                dependencies_tree.insert("", "end", iid=row_id, values=(item.get("name", ""), item.get("author", ""), item.get("version", "")))
            dependencies_tree.bind("<Double-1>", lambda event, tree=dependencies_tree, rows=dependency_rows: self.open_project_ref_from_tree(event, tree, rows))
            dependencies_tree.bind("<Return>", lambda event, tree=dependencies_tree, rows=dependency_rows: self.open_project_ref_from_tree(event, tree, rows))
            body.add(dependencies_frame, weight=1)

        versions_frame = ttk.LabelFrame(body, text="Versions", padding=6)
        versions_tree = ttk.Treeview(versions_frame, columns=("version", "status"), show="headings", height=10, selectmode="browse")
        versions_tree.heading("version", text="Version")
        versions_tree.heading("status", text="Status")
        versions_tree.column("version", width=90, stretch=False)
        versions_tree.column("status", width=90, stretch=False)
        versions_tree.tag_configure("obsolete", foreground="#b00020")
        versions_tree.pack(fill="both", expand=True)
        version_rows = {}
        for version_project in self.project_versions(project):
            row_id = self.index_row_id(version_project)
            version_rows[row_id] = version_project
            versions_tree.insert(
                "",
                "end",
                iid=row_id,
                values=(version_project.get("version", ""), "Obsolete" if version_project.get("obsolete") else "Active"),
                tags=("obsolete",) if version_project.get("obsolete") else ()
            )
            if version_project.get("version") == project.get("version"):
                versions_tree.selection_set(row_id)
        versions_tree.bind("<ButtonRelease-1>", lambda event, tree=versions_tree, rows=version_rows: self.open_version_from_tree(event, tree, rows))
        versions_tree.bind("<Return>", lambda event, tree=versions_tree, rows=version_rows: self.open_version_from_tree(event, tree, rows))
        body.add(versions_frame, weight=1)

        self.temp_panels[tab_name] = panel
        self.tabs.add_tab(tab_name, closable=True, close_command=lambda name=tab_name: self.close_temp_panel(name))

    def project_versions(self, project):
        project_id = project.get("project_id") or project.get("id")
        if project_id:
            try:
                response = api_json(f"/api/projects/{quote(project_id)}?versions=1")
                versions = response.get("projects", [])
            except ValueError:
                versions = [item for item in self.index_projects if item.get("id") == project_id]
        else:
            versions = [item for item in self.index_projects if self.project_identity_key(item) == self.project_identity_key(project)]
        if not any(item.get("version") == project.get("version") for item in versions):
            versions.append(project)
        return sorted(versions, key=self.version_sort_key, reverse=True)

    def open_version_from_tree(self, event, tree, rows):
        item_id = ""
        if getattr(event, "keysym", "") == "Return":
            selected = tree.selection()
            item_id = selected[0] if selected else ""
        elif hasattr(event, "y"):
            item_id = tree.identify_row(event.y)
        if not item_id:
            return "break"
        project = rows.get(item_id)
        if not project:
            return "break"
        installed = self.find_installed_version({
            "project_id": project.get("id"),
            "name": project.get("name"),
            "author": project.get("author"),
            "version": project.get("version")
        })
        self.open_project_panel(project, installed)
        return "break"

    def open_project_ref_from_tree(self, event, tree, rows):
        item_id = ""
        if getattr(event, "keysym", "") == "Return":
            selected = tree.selection()
            item_id = selected[0] if selected else ""
        elif hasattr(event, "y"):
            item_id = tree.identify_row(event.y)
        if not item_id:
            return "break"
        ref = rows.get(item_id)
        project = self.find_project_ref(ref)
        if project:
            installed = self.find_installed_version({
                "project_id": project.get("id"),
                "name": project.get("name"),
                "author": project.get("author"),
                "version": project.get("version")
            })
            self.open_project_panel(project, installed)
        return "break"

    def find_project_ref(self, ref):
        project_id = ref.get("project_id") or ref.get("id")
        if project_id:
            for project in self.index_projects + self.approved_projects:
                if project.get("id") == project_id:
                    return project
            try:
                return api_json(f"/api/projects/{quote(project_id)}").get("project")
            except ValueError:
                return None
        for project in self.index_projects + self.approved_projects:
            if self.project_identity_key(project) == self.project_identity_key(ref):
                return project
        return None

    def modpack_item_status(self, item):
        installed = self.find_modpack_child(item)
        if not installed and not item.get("installed_paths"):
            return "Missing"
        if not installed:
            expected_files = item.get("installed_files", {})
            paths = item.get("installed_paths", {})
            if not paths:
                return "Missing"
            active_paths = [Path(path) for path in paths.values() if path]
            if not active_paths or not all(path.exists() for path in active_paths):
                return "Missing"
            for key, folder in paths.items():
                folder_path = Path(folder)
                for relative_path in expected_files.get(key, []):
                    if not (folder_path / relative_path).exists():
                        return "Missing"
            installed = item
        project = self.find_project_ref(item)
        if project and self.version_sort_key(project) > self.version_sort_key(installed):
            return "Outdated"
        return "Installed"

    def find_modpack_child(self, item):
        installed_id = item.get("installed_id")
        if installed_id:
            mod = self.find_mod(installed_id)
            if mod:
                return mod
        project_id = item.get("project_id") or item.get("id")
        if project_id:
            return next((mod for mod in self.installed_mods if mod.get("project_id") == project_id), None)
        return self.find_existing_install(item)

    def on_modpack_item_right_click(self, event, tree, rows):
        item_id = tree.identify_row(event.y)
        if not item_id:
            return
        item = rows.get(item_id)
        if not item:
            return
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Update", command=lambda item=item: self.update_modpack_item(item))
        menu.add_command(label="Uninstall", command=lambda item=item: self.uninstall_modpack_item(item))
        menu.tk_popup(event.x_root, event.y_root)

    def update_modpack_item(self, item):
        project = self.find_project_ref(item)
        if project and project.get("download_page"):
            self.open_download_page(project["download_page"])
        else:
            messagebox.showinfo("Update", "No download page was found for this mod.")

    def uninstall_modpack_item(self, item):
        installed = self.find_modpack_child(item)
        if installed:
            self.uninstall_mod(installed["id"])
            return
        self.remove_installed_files(item)
        self.remove_disabled_files(item)
        self.remove_app_kept_files(item)
        for modpack in self.installed_mods:
            if not modpack.get("is_modpack"):
                continue
            modpack["modpack_items"] = [
                child for child in modpack.get("modpack_items", [])
                if self.dependency_key(child) != self.dependency_key(item)
            ]
        self.save_installed_mods()
        self.refresh_mod_list()

    def load_panel_icon(self, label, mod):
        icon_path = mod.get("icon_path")
        try:
            if icon_path and Path(icon_path).exists():
                image = tk.PhotoImage(file=icon_path)
            else:
                icon = str(mod.get("icon", ""))
                if not icon.startswith("data:image/") or ";base64," not in icon:
                    return
                image = tk.PhotoImage(data=icon.split(";base64,", 1)[1])
            if image.width() > 96 or image.height() > 96:
                image = image.subsample(max(1, image.width() // 96), max(1, image.height() // 96))
            label.configure(image=image, text="")
            label.image = image
        except tk.TclError:
            pass

    def open_download_page(self, url):
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            messagebox.showerror("Download", "Download page must be an http or https link.")
            return
        prompt = (
            "This button redirects to a third-party website; although all mods and modpacks available in the app "
            "have been vetted by Simdex staff, caution is still recommended when visiting external sites.\n\n"
            "Do you wish to proceed?"
        )
        if not messagebox.askyesno("Download", prompt):
            return
        webbrowser.open(url)

    def close_temp_panel(self, name):
        panel = self.temp_panels.pop(name, None)
        if panel:
            panel.destroy()
        self.tabs.remove_tab(name)

    def toggle_favorite(self, mod_id, tab_name=None):
        mod = self.find_mod(mod_id)
        if not mod:
            return
        mod["favorite"] = not mod.get("favorite", False)
        self.save_installed_mods()
        self.refresh_mod_list()
        if tab_name in self.temp_panels:
            self.close_temp_panel(tab_name)
            self.open_mod_panel(mod_id)

    def install_s4i(self):
        paths = filedialog.askopenfilenames(title="Install .s4i", filetypes=[("Simdex install files", "*.s4i")])
        if not paths:
            return
        for path in paths:
            path = Path(path)
            job_id = f"install-{int(time.time() * 1000)}-{len(self.install_jobs)}"
            self.install_jobs.append({
                "id": job_id,
                "path": str(path),
                "name": path.name,
                "status": "Queued",
                "progress": 0
            })
        self.show_install_queue()
        self.render_install_queue()
        self.after(50, self.process_install_queue)

    def show_install_queue(self):
        if self.install_queue_window and self.install_queue_window.winfo_exists():
            self.install_queue_window.lift()
            return
        window = tk.Toplevel(self)
        window.title("Install Queue")
        window.geometry("520x300")
        self.install_queue_window = window
        self.install_queue_tree = ttk.Treeview(window, columns=("name", "status"), show="headings", selectmode="browse")
        self.install_queue_tree.heading("name", text="File")
        self.install_queue_tree.heading("status", text="Status")
        self.install_queue_tree.column("name", width=330)
        self.install_queue_tree.column("status", width=150)
        self.install_queue_tree.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        self.install_queue_tree.bind("<Button-3>", self.on_install_queue_right_click)
        self.install_progress = ttk.Progressbar(window, maximum=100, variable=tk.DoubleVar(value=0))
        self.install_progress.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Label(window, textvariable=self.install_status_var).pack(anchor="w", padx=8, pady=(0, 8))
        self.install_queue_menu = tk.Menu(window, tearoff=0)
        self.install_queue_menu.add_command(label="Pause", command=self.pause_install_job)
        self.install_queue_menu.add_command(label="Prioritize", command=self.prioritize_install_job)
        self.install_queue_context_id = None
        self.render_install_queue()

    def render_install_queue(self):
        if not self.install_queue_tree or not self.install_queue_tree.winfo_exists():
            return
        self.install_queue_tree.delete(*self.install_queue_tree.get_children())
        for job in self.install_jobs:
            self.install_queue_tree.insert("", "end", iid=job["id"], values=(job["name"], job["status"]))

    def on_install_queue_right_click(self, event):
        item_id = self.install_queue_tree.identify_row(event.y)
        if not item_id:
            return
        self.install_queue_context_id = item_id
        job = next((item for item in self.install_jobs if item["id"] == item_id), None)
        if job and job["id"] in self.paused_install_ids:
            self.install_queue_menu.entryconfigure(0, label="Resume")
        else:
            self.install_queue_menu.entryconfigure(0, label="Pause")
        self.install_queue_menu.tk_popup(event.x_root, event.y_root)

    def pause_install_job(self):
        job_id = self.install_queue_context_id
        if not job_id:
            return
        if job_id in self.paused_install_ids:
            self.paused_install_ids.remove(job_id)
        else:
            self.paused_install_ids.add(job_id)
        for job in self.install_jobs:
            if job["id"] == job_id and job["status"] in {"Queued", "Paused"}:
                job["status"] = "Queued" if job_id not in self.paused_install_ids else "Paused"
        self.render_install_queue()
        self.after(50, self.process_install_queue)

    def prioritize_install_job(self):
        if self.install_queue_context_id:
            self.prioritized_install_id = self.install_queue_context_id
            self.paused_install_ids.discard(self.install_queue_context_id)
            self.after(50, self.process_install_queue)

    def process_install_queue(self):
        if self.install_worker_running:
            return
        job = self.next_install_job()
        if not job:
            return
        self.install_worker_running = True
        self.active_install_id = job["id"]
        job["status"] = "Installing"
        self.install_status_var.set(f"Installing {job['name']}")
        if self.install_progress:
            self.install_progress.configure(mode="indeterminate")
            self.install_progress.start(12)
        self.render_install_queue()
        self.update_idletasks()
        try:
            mod = self.extract_and_install(Path(job["path"]), install_job=job)
        except (BadZipFile, OSError, ValueError, json.JSONDecodeError) as error:
            job["status"] = f"Failed: {error}"
            messagebox.showerror("Install failed", str(error))
            mod = None
        finally:
            if self.install_progress:
                self.install_progress.stop()
                self.install_progress.configure(mode="determinate")
                self.install_progress["value"] = 100
            self.install_worker_running = False
            self.active_install_id = None
        if mod is None:
            if not job["status"].startswith("Failed"):
                job["status"] = "Skipped"
        else:
            self.installed_mods.append(mod)
            job["status"] = "Done"
        self.save_installed_mods()
        self.refresh_mod_list()
        self.refresh_index_list()
        self.render_install_queue()
        if self.prioritized_install_id == job["id"]:
            self.prioritized_install_id = None
        self.install_status_var.set("Install queue finished." if not self.next_install_job() else "")
        self.after(50, self.process_install_queue)

    def next_install_job(self):
        if self.prioritized_install_id:
            job = next((item for item in self.install_jobs if item["id"] == self.prioritized_install_id and item["status"] in {"Queued", "Paused"}), None)
            if job:
                return job
        return next((item for item in self.install_jobs if item["status"] == "Queued" and item["id"] not in self.paused_install_ids), None)

    def update_install_job_name(self, install_job, project, s4i_path):
        if install_job and project.get("name"):
            install_job["name"] = f"{project['name']} ({s4i_path.name})"
            self.render_install_queue()

    def extract_and_install(self, s4i_path, parent_modpack=None, install_job=None):
        temp_root = None
        installed_paths = {}
        installed_files = {}
        project_id = s4i_path.stem
        try:
            project = api_json(f"/api/projects/{project_id}")
            if not project.get("project"):
                raise ValueError("No approved project was found for this file id.")
            approved = project["project"]
            if approved.get("obsolete"):
                prompt = (
                    "This version is marked obsolete.\n\n"
                    f"{approved.get('name', project_id)} {approved.get('version', '')}\n\n"
                    "Continue with the install?"
                )
                if not messagebox.askyesno("Obsolete version", prompt):
                    return None
            if approved.get("sha256") and approved["sha256"].lower() != file_sha256(s4i_path).lower():
                raise ValueError("The install file does not match the approved project.")
            self.update_install_job_name(install_job, approved, s4i_path)

            temp_parent = APP_ROOT / "InstallTemp"
            temp_parent.mkdir(parents=True, exist_ok=True)
            temp_root = Path(tempfile.mkdtemp(prefix=f"{project_id}-", dir=temp_parent))
            encrypted = s4i_path.read_bytes()
            archive_bytes = decrypt_bytes(encrypted, project_id)
            temp_zip = temp_root / "package.zip"
            temp_zip.write_bytes(archive_bytes)
            with ZipFile(temp_zip, "r") as archive:
                extract_archive(archive, temp_root)
            temp_zip.unlink(missing_ok=True)

            project_root = self.find_project_root(temp_root)
            metadata_path = project_root / ".metadata"
            if not metadata_path.exists():
                raise ValueError("Missing .metadata")
            metadata = read_json(metadata_path)
            validate_metadata(metadata)
            metadata = apply_project_type(metadata, project_root)
            candidate = {
                "project_id": project_id,
                "name": metadata["name"],
                "author": metadata["author"],
                "version": metadata.get("version", "")
            }
            if metadata.get("is_modpack"):
                return self.extract_and_install_modpack(s4i_path, project_id, project_root, metadata, approved)
            self.prompt_for_missing_dependencies(metadata)
            existing = self.find_existing_install(candidate)
            if existing:
                if existing.get("version") == candidate["version"]:
                    self.apply_approved_metadata(existing, approved)
                    self.save_installed_mods()
                    self.refresh_mod_list()
                    self.refresh_index_list()
                    messagebox.showinfo("Install", "You already have this mod installed.")
                    return None
                prompt = (
                    f"You already have {existing.get('name')} installed.\n\n"
                    f"Current version: {existing.get('version')}\n"
                    f"New version: {candidate['version']}\n\n"
                    "Overwrite the current install?"
                )
                if not messagebox.askyesno("Overwrite install", prompt):
                    return None

            folder_name = install_folder_name(metadata["author"], metadata["name"])
            mods_source = project_root / "Mods"
            tray_source = project_root / "Tray"
            has_mods = folder_has_files(mods_source)
            has_tray = folder_has_files(tray_source)

            if not has_mods and not has_tray:
                raise ValueError("No files found in Mods or Tray")

            if has_mods:
                target = SIMS_MODS / folder_name
                staged = temp_root / "StagedInstall" / "mods"
                shutil.copytree(mods_source, staged)
                installed_paths["mods"] = str(target)
                installed_files["mods"] = relative_files(staged)
            if has_tray:
                target = SIMS_TRAY / folder_name
                staged = temp_root / "StagedInstall" / "tray"
                shutil.copytree(tray_source, staged)
                installed_paths["tray"] = str(target)
                installed_files["tray"] = relative_files(staged)

            self.commit_staged_install(temp_root / "StagedInstall", installed_paths, existing)
            if existing:
                self.remove_disabled_files(existing)
                self.remove_app_kept_files(existing)
                self.installed_mods = [item for item in self.installed_mods if item.get("id") != existing.get("id")]

            icon_path = None
            root_icon = project_root / "Icon.png"
            if root_icon.exists():
                icon_target = APP_ROOT / "Icons" / f"{folder_name}.png"
                icon_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(root_icon, icon_target)
                icon_path = str(icon_target)

            final_extract = APP_ROOT / "InstalledSources" / project_id
            if final_extract.exists():
                shutil.rmtree(final_extract)
            final_extract.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(project_root, final_extract)
            hide_metadata_file(final_extract)

            mod = {
                "id": f"{folder_name}-{int(time.time() * 1000)}",
                "project_id": project_id,
                "name": metadata["name"],
                "short_description": metadata["short_description"],
                "author": metadata["author"],
                "version": metadata.get("version", ""),
                "is_mod": bool(metadata.get("is_mod")),
                "is_modpack": bool(metadata.get("is_modpack")),
                "dependencies": metadata.get("dependencies", []),
                "modpack_parent_id": parent_modpack.get("project_id", "") if parent_modpack else "",
                "modpack_parent_name": parent_modpack.get("name", "") if parent_modpack else "",
                "obsolete": bool(approved.get("obsolete")),
                "creator_verified": bool(approved.get("creator_verified")),
                "download_page": metadata.get("download_page", ""),
                "icon": metadata.get("icon", ""),
                "icon_path": icon_path,
                "long_description": metadata.get("long_description", ""),
                "source_s4i": str(s4i_path),
                "source_extract": str(final_extract),
                "installed_paths": installed_paths,
                "installed_files": installed_files,
                "disabled_paths": {},
                "enabled": True,
                "favorite": False,
                "status": "ok"
            }
            self.apply_approved_metadata(mod, approved)
            return mod
        except Exception:
            raise
        finally:
            if temp_root and temp_root.exists():
                shutil.rmtree(temp_root, ignore_errors=True)

    def extract_and_install_modpack(self, s4i_path, project_id, project_root, metadata, approved):
        mods_source = project_root / "Mods"
        s4i_files = sorted(mods_source.rglob("*.s4i"), key=lambda item: str(item.relative_to(mods_source)).lower())
        if not s4i_files:
            raise ValueError("Modpack Mods folder does not contain any .s4i files.")

        folder_name = install_folder_name(metadata["author"], metadata["name"])
        existing = self.find_existing_install({
            "project_id": project_id,
            "name": metadata["name"],
            "author": metadata["author"],
            "version": metadata.get("version", "")
        })
        if existing and existing.get("version") == metadata.get("version", ""):
            messagebox.showinfo("Install", "You already have this modpack installed.")
            return None
        if existing:
            prompt = (
                f"You already have {existing.get('name')} installed.\n\n"
                f"Current version: {existing.get('version')}\n"
                f"New version: {metadata.get('version', '')}\n\n"
                "Overwrite the current install?"
            )
            if not messagebox.askyesno("Overwrite install", prompt):
                return None
            self.uninstall_mod(existing["id"])

        parent = {"project_id": project_id, "name": metadata["name"]}
        installed_items = []
        for child_s4i in s4i_files:
            try:
                child_info = self.read_s4i_metadata(child_s4i)
            except (BadZipFile, OSError, ValueError, json.JSONDecodeError):
                child_info = {}
            existing_child = self.find_installed_version({
                "project_id": child_info.get("project_id") or child_info.get("id"),
                "name": child_info.get("name"),
                "author": child_info.get("author"),
                "version": child_info.get("version")
            }) if child_info else None
            if existing_child:
                installed_items.append({
                    "id": existing_child.get("project_id", ""),
                    "project_id": existing_child.get("project_id", ""),
                    "name": existing_child.get("name", ""),
                    "author": existing_child.get("author", ""),
                    "version": existing_child.get("version", ""),
                    "installed_id": existing_child.get("id", ""),
                    "external": True
                })
                continue
            existing_child = self.find_existing_install({
                "project_id": child_info.get("project_id") or child_info.get("id"),
                "name": child_info.get("name"),
                "author": child_info.get("author")
            }) if child_info else None
            if existing_child:
                child = self.extract_and_install(child_s4i)
                if child:
                    self.installed_mods.append(child)
                    installed_items.append({
                        "id": child.get("project_id", ""),
                        "project_id": child.get("project_id", ""),
                        "name": child.get("name", ""),
                        "author": child.get("author", ""),
                        "version": child.get("version", ""),
                        "installed_id": child.get("id", ""),
                        "external": True
                    })
                continue
            child = self.extract_and_install(child_s4i, parent)
            if child:
                installed_items.append({
                    "id": child.get("project_id", ""),
                    "project_id": child.get("project_id", ""),
                    "name": child.get("name", ""),
                    "author": child.get("author", ""),
                    "version": child.get("version", ""),
                    "installed_id": child.get("id", ""),
                    "external": False,
                    "installed_paths": child.get("installed_paths", {}),
                    "installed_files": child.get("installed_files", {}),
                    "disabled_paths": {},
                    "enabled": True,
                    "source_extract": child.get("source_extract", ""),
                    "icon_path": child.get("icon_path", "")
                })

        icon_path = None
        root_icon = project_root / "Icon.png"
        if root_icon.exists():
            icon_target = APP_ROOT / "Icons" / f"{folder_name}.png"
            icon_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root_icon, icon_target)
            icon_path = str(icon_target)

        final_extract = APP_ROOT / "InstalledSources" / project_id
        if final_extract.exists():
            shutil.rmtree(final_extract)
        final_extract.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(project_root, final_extract)
        hide_metadata_file(final_extract)

        modpack = {
            "id": f"{folder_name}-{int(time.time() * 1000)}",
            "project_id": project_id,
            "name": metadata["name"],
            "short_description": metadata["short_description"],
            "author": metadata["author"],
            "version": metadata.get("version", ""),
            "is_mod": False,
            "is_modpack": True,
            "dependencies": [],
            "modpack_items": installed_items or metadata.get("modpack_items", []),
            "obsolete": bool(approved.get("obsolete")),
            "creator_verified": bool(approved.get("creator_verified")),
            "download_page": metadata.get("download_page", ""),
            "icon": metadata.get("icon", ""),
            "icon_path": icon_path,
            "long_description": metadata.get("long_description", ""),
            "source_s4i": str(s4i_path),
            "source_extract": str(final_extract),
            "installed_paths": {},
            "installed_files": {},
            "disabled_paths": {},
            "enabled": True,
            "favorite": False,
            "status": "ok"
        }
        self.apply_approved_metadata(modpack, approved)
        return modpack

    def installed_child_for_modpack(self, s4i_path):
        try:
            item = self.read_s4i_metadata(s4i_path)
        except (BadZipFile, OSError, ValueError, json.JSONDecodeError):
            return None
        return self.find_installed_version({
            "project_id": item.get("project_id") or item.get("id"),
            "name": item.get("name"),
            "author": item.get("author"),
            "version": item.get("version")
        })

    def prompt_for_missing_dependencies(self, metadata):
        dependencies = metadata.get("dependencies", [])
        if not dependencies:
            return
        missing = [item for item in dependencies if not self.find_existing_install(item)]
        if not missing:
            return
        names = "\n".join(f"- {item.get('name', 'Unknown')} {item.get('version', '')}".strip() for item in missing)
        if not messagebox.askyesno("Dependencies", f"This mod has missing dependencies:\n\n{names}\n\nOpen their download pages?"):
            return
        for item in missing:
            project = self.find_project_ref(item)
            if project and project.get("download_page"):
                self.open_download_page(project["download_page"])

    def find_existing_install(self, mod):
        project_id = mod.get("project_id")
        if project_id:
            match = next((item for item in self.installed_mods if item.get("project_id") == project_id), None)
            if match:
                return match
        return next(
            (
                item for item in self.installed_mods
                if item.get("name") == mod.get("name") and item.get("author") == mod.get("author")
            ),
            None
        )

    def find_installed_version(self, mod):
        project_id = mod.get("project_id")
        version = mod.get("version")
        if project_id:
            match = next(
                (
                    item for item in self.installed_mods
                    if item.get("project_id") == project_id and item.get("version") == version
                ),
                None
            )
            if match:
                return match
        return next(
            (
                item for item in self.installed_mods
                if item.get("name") == mod.get("name")
                and item.get("author") == mod.get("author")
                and item.get("version") == version
            ),
            None
        )

    def find_project_root(self, extract_root):
        if (extract_root / ".metadata").exists():
            return extract_root
        matches = list(extract_root.glob("*/.metadata"))
        if len(matches) == 1:
            return matches[0].parent
        raise ValueError("Could not find a single project root")

    def commit_staged_install(self, staged_root, installed_paths, existing):
        backup_root = APP_ROOT / "InstallBackups" / f"{int(time.time() * 1000)}"
        backups = []
        moved_targets = []
        try:
            backup_root.mkdir(parents=True, exist_ok=True)
            existing_paths = existing.get("installed_paths", {}) if existing else {}
            for key, path_text in existing_paths.items():
                path = Path(path_text)
                if not path.exists():
                    continue
                backup = backup_root / f"old-{key}"
                shutil.move(str(path), str(backup))
                backups.append((path, backup))

            for key, path_text in installed_paths.items():
                target = Path(path_text)
                if target.exists():
                    backup = backup_root / f"target-{key}"
                    shutil.move(str(target), str(backup))
                    backups.append((target, backup))
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(staged_root / key), str(target))
                moved_targets.append(target)

            shutil.rmtree(backup_root, ignore_errors=True)
        except Exception:
            for target in moved_targets:
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
            for target, backup in reversed(backups):
                if backup.exists():
                    if target.exists():
                        shutil.rmtree(target, ignore_errors=True)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(backup), str(target))
            shutil.rmtree(backup_root, ignore_errors=True)
            raise

    def uninstall_context_mod(self):
        if self.context_mod_id:
            self.uninstall_mod(self.context_mod_id)

    def uninstall_mod(self, mod_id):
        mod = self.find_mod(mod_id)
        if not mod:
            return
        if mod.get("is_modpack"):
            for child in list(self.installed_mods):
                if child.get("modpack_parent_id") == mod.get("project_id"):
                    self.uninstall_mod(child["id"])
        self.remove_installed_files(mod)
        self.remove_disabled_files(mod)
        self.remove_app_kept_files(mod)
        self.installed_mods = [item for item in self.installed_mods if item.get("id") != mod_id]
        self.selected_mod_ids.discard(mod_id)
        self.close_mod_panels(mod_id)
        self.save_installed_mods()
        self.refresh_mod_list()
        self.refresh_index_list()

    def close_mod_panels(self, mod_id):
        suffix = f"({mod_id[:8]})"
        for name in list(self.temp_panels):
            if name.endswith(suffix):
                self.close_temp_panel(name)

    def remove_installed_files(self, mod):
        if mod.get("is_modpack"):
            for item in mod.get("modpack_items", []):
                if not item.get("external"):
                    self.remove_installed_files(item)
        for path in mod.get("installed_paths", {}).values():
            install_path = Path(path)
            if install_path.exists():
                shutil.rmtree(install_path)

    def remove_disabled_files(self, mod):
        if mod.get("is_modpack"):
            for item in mod.get("modpack_items", []):
                if not item.get("external"):
                    self.remove_disabled_files(item)
        for path in self.mod_disabled_paths(mod).values():
            disabled_path = Path(path)
            if disabled_path.exists():
                shutil.rmtree(disabled_path)
        disabled_root = DISABLED_MODS_ROOT / self.disabled_folder_name(mod)
        if disabled_root.exists() and not any(disabled_root.iterdir()):
            disabled_root.rmdir()

    def remove_app_kept_files(self, mod):
        if mod.get("is_modpack"):
            for item in mod.get("modpack_items", []):
                if not item.get("external"):
                    self.remove_app_kept_files(item)
        source_extract = mod.get("source_extract")
        if source_extract:
            source_path = Path(source_extract)
            if self.is_app_path(source_path) and source_path.exists():
                shutil.rmtree(source_path)

        icon_path = mod.get("icon_path")
        if icon_path:
            icon_file = Path(icon_path)
            if self.is_app_path(icon_file) and icon_file.exists():
                icon_file.unlink()

    def is_app_path(self, path):
        try:
            path.resolve().relative_to(APP_ROOT.resolve())
        except ValueError:
            return False
        return True

    def build_creator_panel(self):
        creator = ttk.PanedWindow(self.creator_panel, orient="horizontal")
        creator.pack(fill="both", expand=True)
        self.creator_workspace = creator

        explorer = ttk.Frame(creator, padding=(0, 0, 8, 0))
        info = ttk.Frame(creator, padding=(8, 0, 0, 0))
        creator.add(explorer, weight=1)
        creator.add(info, weight=3)
        self.info_panel = info

        button_bar = ttk.Frame(explorer)
        button_bar.pack(fill="x", pady=(0, 8))
        self.creator_account_label = ttk.Label(button_bar)
        self.creator_account_label.pack(anchor="w", pady=(0, 8))
        self.update_creator_account_label()
        verify_row = ttk.Frame(button_bar)
        verify_row.pack(fill="x", pady=(0, 8))
        self.verify_button = ttk.Button(verify_row, text="Verify", command=self.verify_creator_account)
        self.verify_button.pack(anchor="center")
        self.verify_button.bind("<Enter>", lambda event: self.show_tooltip(event.x_root + 12, event.y_root + 12, VERIFY_IGNORE_MESSAGE))
        self.verify_button.bind("<Leave>", self.hide_tooltip)
        buttons = [
            ("New Project", self.new_project),
            ("Load Project", self.load_project),
            ("Save Project", self.save_project),
            ("Publish Project", self.publish_project),
            ("Import File", self.import_file),
            ("New File", self.new_file),
        ]
        for text, command in buttons:
            button = ttk.Button(button_bar, text=text, command=command)
            button.pack(fill="x", pady=(0, 4))
            self.creator_buttons[text] = button
        self.edit_button = ttk.Button(button_bar, text="Edit File", command=self.edit_or_save_file)
        self.edit_button.pack(fill="x")
        self.creator_buttons["Edit File"] = self.edit_button

        tree_frame = ttk.Frame(explorer)
        tree_frame.pack(fill="both", expand=True)
        self.project_tree = ttk.Treeview(tree_frame, show="tree")
        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.project_tree.yview)
        self.project_tree.configure(yscrollcommand=tree_scroll.set)
        self.project_tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")
        self.project_tree.bind("<ButtonPress-1>", self.on_project_tree_press)
        self.project_tree.bind("<ButtonRelease-1>", self.on_project_tree_release)

        approved_box = ttk.LabelFrame(explorer, text="Approved Projects", padding=6)
        approved_box.pack(fill="both", expand=False, pady=(8, 0))
        self.approved_tree = ttk.Treeview(approved_box, columns=("name", "author", "version", "status", "id"), show="headings", height=6, selectmode="browse")
        self.approved_tree.heading("name", text="Name")
        self.approved_tree.heading("author", text="Author")
        self.approved_tree.heading("version", text="Version")
        self.approved_tree.heading("status", text="Status")
        self.approved_tree.heading("id", text="ID")
        self.approved_tree.column("name", width=130)
        self.approved_tree.column("author", width=90)
        self.approved_tree.column("version", width=65)
        self.approved_tree.column("status", width=70)
        self.approved_tree.column("id", width=90)
        self.approved_tree.pack(fill="both", expand=True)
        self.approved_tree.tag_configure("obsolete", foreground="#b00020")
        ttk.Button(approved_box, text="Refresh Approved", command=self.refresh_approved_projects).pack(fill="x", pady=(6, 0))
        self.approved_menu = tk.Menu(self, tearoff=0)
        self.approved_menu.add_command(label="Package", command=self.package_selected_approved_project)
        self.approved_menu.add_command(label="Edit Metadata", command=self.edit_selected_approved_metadata)
        self.approved_menu.add_command(label="Mark as Obsolete", command=self.mark_selected_project_obsolete)
        self.approved_menu.add_command(label="Delete Project", command=self.delete_selected_approved_project)
        self.approved_context_id = None
        self.approved_tree.bind("<Button-3>", self.on_approved_right_click)
        self.approved_tree.bind("<Motion>", lambda event: self.on_author_badge_hover(event, self.approved_tree, self.approved_projects, "#2", self.approved_row_id))
        self.approved_tree.bind("<Leave>", self.hide_tooltip)

        self.build_info_form()
        self.refresh_approved_projects()
        self.build_creator_gate()
        self.update_creator_gate()

    def build_guides_panel(self):
        shell = ttk.Frame(self.guides_panel, padding=16)
        shell.pack(fill="both", expand=True)
        ttk.Label(shell, text="Guides", font=("Segoe UI", 18, "bold")).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            shell,
            text="Choose a visual guide. Each guide will point at the controls it explains with yellow arrows and short on-screen notes.",
            wraplength=720
        ).pack(anchor="w", pady=(0, 16))

        buttons = ttk.Frame(shell)
        buttons.pack(anchor="nw", fill="x")
        guides = [
            ("Quick Tour", "quick"),
            ("Installing Projects", "installing"),
            ("Managing Installed Projects", "installed"),
            ("Browsing the Mod Index", "index"),
            ("Creator Workflow", "creator"),
            ("Modpacks and Dependencies", "modpacks"),
        ]
        for text, key in guides:
            ttk.Button(buttons, text=text, command=lambda key=key: self.start_visual_guide(key)).pack(fill="x", pady=(0, 6))

        ttk.Label(
            shell,
            text="Tip: press Escape to close a guide, or use Left and Right arrow keys to move between steps.",
            wraplength=720
        ).pack(anchor="w", pady=(14, 0))

    def start_visual_guide(self, key):
        steps = self.visual_guide_steps().get(key, [])
        VisualGuide(self, "Simdex Guide", steps).start()

    def tab_button(self, name):
        tab = self.tabs.tabs.get(name, {})
        return tab.get("button")

    def visual_guide_steps(self):
        return {
            "quick": [
                self.guide_step("Main", self.tab_button("Main"), "Main", "Installed projects live here. Double-click a row to open details, or right-click for actions."),
                self.guide_step("Main", self.install_button, "Install Projects", "Use Install to choose one or more .s4i files. They will be added to the install queue."),
                self.guide_step("Main", self.install_queue_button, "Install Queue", "The queue shows pending, paused, failed, and finished installs. Right-click queued items to pause or prioritize them."),
                self.guide_step("Mod Index", self.tab_button("Mod Index"), "Mod Index", "Browse approved projects from the website here. Open a project to read details, versions, dependencies, or modpack contents."),
                self.guide_step("Creator", self.tab_button("Creator"), "Creator Tools", "Creators build, package, publish, and edit project metadata from this tab."),
            ],
            "installing": [
                self.guide_step("Main", self.install_button, "Install Button", "Choose one or more .s4i files. Simdex verifies approved projects before installing them."),
                self.guide_step("Main", self.install_queue_button, "Install Queue", "Open the queue to watch progress. The item name updates after server approval and file verification."),
                self.guide_step("Main", self.mod_tree, "Installed List", "Finished installs appear here. Modpacks appear as one row; their bundled mods are shown inside the modpack detail page."),
                self.guide_step("Main", self.refresh_button, "Refresh", "Refresh checks installed files and remote project status."),
            ],
            "installed": [
                self.guide_step("Main", self.mod_tree, "Installed Projects", "The State column shows whether an install is enabled, missing, broken, disabled, or obsolete."),
                self.guide_step("Main", self.select_all_check, "Select Multiple", "Use the checkbox column or Select All to work with multiple installed projects."),
                self.guide_step("Main", self.disable_selected_button, "Disable", "Disable moves selected files out of the Sims 4 folders while keeping them managed by Simdex."),
                self.guide_step("Main", self.enable_selected_button, "Enable", "Enable moves disabled files back into the Sims 4 folders."),
                self.guide_step("Main", self.mod_tree, "Context Menu", "Right-click an installed project to enable, disable, or uninstall it."),
            ],
            "index": [
                self.guide_step("Mod Index", self.index_tree, "Project Index", "Approved mods and modpacks from the server are listed here. Double-click or press Enter to open one."),
                self.guide_step("Mod Index", lambda: self.index_controls, "Filters", "Use search, type, obsolete, and verified filters to narrow the project list."),
                self.guide_step("Mod Index", lambda: self.index_pages_frame, "Pages", "Use page buttons here when there are more results."),
            ],
            "creator": [
                self.guide_step("Creator", lambda: self.creator_workspace, "Creator Workspace", "The left side manages files and approved projects. The right side edits metadata."),
                self.guide_step("Creator", lambda: self.project_tree, "Project Files", "Project folders contain .metadata, Icon.png, and the content folders for the project type."),
                self.guide_step("Creator", lambda: self.dependencies_box if hasattr(self, "dependencies_box") else self.info_panel, "Dependencies", "Mods can list dependencies. Selected dependencies stay at the top. Modpacks do not use dependencies."),
                self.guide_step("Creator", lambda: self.approved_tree, "Approved Projects", "Approved projects can be packaged, edited, marked obsolete, or deleted from this list."),
            ],
            "modpacks": [
                self.guide_step("Creator", lambda: self.project_type_label if hasattr(self, "project_type_label") else self.info_panel, "Detected Type", "Project type is detected from the folder layout. Modpacks use Mods with .s4i files and no Tray folder."),
                self.guide_step("Creator", lambda: self.project_tree, "Modpack Files", "For modpacks, import .s4i files into the Mods folder. Those files become the modpack's installed mod list."),
                self.guide_step("Mod Index", self.index_tree, "Modpack Pages", "Open a modpack from the index to see its Mods panel before the Versions panel."),
                self.guide_step("Main", self.mod_tree, "Installed Modpacks", "A modpack installs as one main row. Open it to view or manage the mods it installed."),
            ],
        }

    def guide_step(self, panel, widget, title, text):
        return {
            "panel": panel,
            "widget": widget,
            "title": title,
            "text": text
        }

    def show_creator_auth_panel(self, mode):
        self.set_metadata_edit_mode(False)
        for child in self.info_panel.winfo_children():
            child.destroy()
        ttk.Label(self.info_panel, text=f"Creator {mode}", font=("Segoe UI", 16, "bold")).pack(anchor="w", pady=(0, 12))
        email_var = tk.StringVar(value=self.creator_account.get("email", ""))
        username_var = tk.StringVar(value=self.creator_username())
        password_var = tk.StringVar()
        ttk.Label(self.info_panel, text="Email").pack(anchor="w")
        ttk.Entry(self.info_panel, textvariable=email_var).pack(fill="x", pady=(0, 8))
        if mode.lower() == "signup":
            ttk.Label(self.info_panel, text="Username").pack(anchor="w")
            ttk.Entry(self.info_panel, textvariable=username_var).pack(fill="x", pady=(0, 8))
        ttk.Label(self.info_panel, text="Password").pack(anchor="w")
        ttk.Entry(self.info_panel, textvariable=password_var, show="*").pack(fill="x", pady=(0, 12))
        ttk.Label(
            self.info_panel,
            text="Creator accounts are required for creating, publishing, and managing projects.",
            wraplength=560
        ).pack(anchor="w", pady=(0, 12))
        ttk.Button(
            self.info_panel,
            text=mode,
            command=lambda: self.submit_creator_auth(mode.lower(), email_var.get(), password_var.get(), username_var.get())
        ).pack(anchor="w")
        self.show_creator_gate(auth_open=True)

    def build_creator_gate(self):
        self.creator_gate = ttk.Frame(self.creator_panel, padding=24)
        card = ttk.Frame(self.creator_gate, padding=24)
        card.place(relx=0.5, rely=0.5, anchor="center")
        ttk.Label(card, text="Creator Account Required", font=("Segoe UI", 16, "bold")).pack(pady=(0, 12))
        row = ttk.Frame(card)
        row.pack()
        ttk.Button(row, text="Login", command=lambda: self.show_creator_auth_panel("Login")).pack(side="left", padx=(0, 8))
        ttk.Button(row, text="Signup", command=lambda: self.show_creator_auth_panel("Signup")).pack(side="left")

    def show_creator_gate(self, auth_open=False):
        if not hasattr(self, "creator_gate"):
            return
        if self.has_creator_account():
            self.creator_gate.place_forget()
            return
        if auth_open:
            self.creator_gate.place_forget()
            return
        self.creator_gate.place(x=0, y=0, relwidth=1, relheight=1)
        self.creator_gate.lift()

    def update_creator_gate(self):
        if hasattr(self, "author_entry"):
            self.info_vars.setdefault("author", tk.StringVar()).set(self.creator_username())
        if self.has_creator_account():
            if not self.editing_approved_project:
                for button in self.creator_buttons.values():
                    button.configure(state="normal")
                if hasattr(self, "verify_button"):
                    self.verify_button.configure(state="disabled" if self.creator_account.get("verified") else "normal")
            if hasattr(self, "creator_gate"):
                self.creator_gate.place_forget()
            self.refresh_approved_projects()
        else:
            for button in self.creator_buttons.values():
                button.configure(state="disabled")
            if hasattr(self, "verify_button"):
                self.verify_button.configure(state="disabled")
            self.show_creator_gate()

    def restore_creator_form(self):
        self.build_info_form()
        if self.current_project and (self.current_project / ".metadata").exists():
            try:
                self.load_metadata_into_form(read_json(self.current_project / ".metadata"))
            except (OSError, json.JSONDecodeError):
                pass

    def submit_creator_auth(self, mode, email, password, username=""):
        endpoint = "/api/creator/signup" if mode == "signup" else "/api/creator/login"

        def auth():
            payload = {"email": email, "password": password}
            if mode == "signup":
                payload["username"] = username
            response = api_json(endpoint, method="POST", payload=payload)
            account = response.get("account", {})
            account["token"] = response.get("token", "")
            return account

        def done(account):
            self.save_creator_account(account)
            self.migrate_root_projects()
            self.restore_creator_form()
            self.refresh_approved_projects()
            if mode == "signup" and not account.get("verified"):
                messagebox.showinfo("Creator Account", VERIFY_IGNORE_MESSAGE)
            else:
                messagebox.showinfo("Creator Account", "Signed in.")

        self.run_background_task("Creator Account", auth, done)

    def verify_creator_account(self):
        if not self.require_creator_account():
            return
        code = simpledialog.askstring("Verify Account", "Verification code:")
        if not code:
            return

        def verify():
            response = api_json(
                "/api/creator/verify",
                method="POST",
                payload={"code": code},
                token=self.creator_token()
            )
            account = response.get("account", {})
            account["token"] = self.creator_token()
            return account

        def verified(account):
            self.save_creator_account(account)
            self.refresh_index_projects()
            messagebox.showinfo("Verify Account", "Account verified.")

        self.run_background_task("Verify Account", verify, verified)

    def build_info_form(self):
        for child in self.info_panel.winfo_children():
            child.destroy()
        self.editing_file = None
        self.info_bool_widgets = {}
        self.edit_button.configure(text="Edit File")
        fields = [
            ("Project Name", "name"),
            ("Project Short Description", "short_description"),
            ("Project Icon", "icon"),
            ("Project Author", "author"),
            ("Project Version", "version"),
            ("Download Page", "download_page"),
        ]
        for label, key in fields:
            ttk.Label(self.info_panel, text=label).pack(anchor="w")
            var = self.info_vars.setdefault(key, tk.StringVar())
            if key == "author":
                var.set(self.creator_username())
                self.author_entry = ttk.Entry(self.info_panel, textvariable=var, state="disabled")
                self.author_entry.pack(fill="x", pady=(0, 8))
            else:
                ttk.Entry(self.info_panel, textvariable=var).pack(fill="x", pady=(0, 8))

        self.project_type_label = ttk.Label(self.info_panel, text="Project Type: Mod")
        self.project_type_label.pack(anchor="w", pady=(0, 8))

        self.dependencies_box = ttk.LabelFrame(self.info_panel, text="Dependencies", padding=6)
        self.dependencies_box.pack(fill="both", expand=False, pady=(0, 8))
        self.dependencies_tree = ttk.Treeview(
            self.dependencies_box,
            columns=("selected", "name", "author", "version"),
            show="headings",
            height=6,
            selectmode="none"
        )
        self.dependencies_tree.heading("selected", text="")
        self.dependencies_tree.heading("name", text="Name")
        self.dependencies_tree.heading("author", text="Author")
        self.dependencies_tree.heading("version", text="Version")
        self.dependencies_tree.column("selected", width=34, stretch=False, anchor="center")
        self.dependencies_tree.column("name", width=180)
        self.dependencies_tree.column("author", width=120)
        self.dependencies_tree.column("version", width=70, stretch=False)
        self.dependencies_tree.pack(fill="both", expand=True)
        self.dependencies_tree.bind("<ButtonRelease-1>", self.on_dependency_click)
        ttk.Button(self.dependencies_box, text="Refresh Dependencies", command=self.refresh_dependency_choices).pack(fill="x", pady=(6, 0))

        self.long_description_label = ttk.Label(self.info_panel, text="Project Long Description")
        self.long_description_label.pack(anchor="w")
        self.long_description = tk.Text(self.info_panel, height=14, wrap="word")
        self.long_description.pack(fill="both", expand=True)

    def new_project(self):
        if not self.require_creator_account():
            return
        name = simpledialog.askstring("New Project", "Project name:")
        if not name:
            return
        is_modpack = messagebox.askyesno("New Project", "Create this project as a modpack?")
        shutil.rmtree(CREATOR_CACHE, ignore_errors=True)
        CREATOR_CACHE.mkdir(parents=True, exist_ok=True)

        project = PROJECTS_ROOT / name
        if project.exists():
            messagebox.showerror("New Project", "A project with that name already exists.")
            return
        project.mkdir(parents=True)
        (project / "Mods").mkdir()
        if not is_modpack:
            (project / "Tray").mkdir()
        metadata_path = project / ".metadata"
        metadata = metadata_template(name)
        metadata["author"] = self.creator_username()
        metadata["is_mod"] = not is_modpack
        metadata["is_modpack"] = is_modpack
        write_json(metadata_path, metadata)
        hide_file(metadata_path)
        self.current_project = project
        self.load_metadata_into_form(metadata)
        self.refresh_project_tree()

    def load_project(self):
        if not self.require_creator_account():
            return
        path = filedialog.askdirectory(title="Load Project", initialdir=str(PROJECTS_ROOT))
        if not path:
            return
        project = Path(path)
        if not (project / ".metadata").exists():
            messagebox.showerror("Load Project", "That folder does not contain a .metadata file.")
            return
        self.current_project = project
        try:
            self.load_metadata_into_form(read_json(project / ".metadata"))
        except (OSError, json.JSONDecodeError):
            messagebox.showerror("Load Project", "Could not read project metadata.")
            return
        hide_metadata_file(project)
        self.refresh_project_tree()

    def load_metadata_into_form(self, metadata):
        for key in metadata_template().keys():
            if key not in {"long_description", "is_mod", "is_modpack", "dependencies", "modpack_items"}:
                self.info_vars.setdefault(key, tk.StringVar())
        for key, var in self.info_vars.items():
            value = metadata.get(key, "")
            if key == "download_page" and not value:
                value = metadata.get("page", "")
            if key == "author" and self.has_creator_account():
                value = self.creator_username()
            var.set(value)
        for key, var in self.info_bool_vars.items():
            var.set(bool(metadata.get(key)))
        if hasattr(self, "long_description"):
            self.long_description.delete("1.0", "end")
            self.long_description.insert("1.0", metadata.get("long_description", ""))
        self.dependency_vars = {
            self.dependency_key(item): bool(item)
            for item in metadata.get("dependencies", [])
            if self.dependency_key(item)
        }
        self.refresh_dependency_choices()
        self.update_project_type_label(metadata)

    def collect_metadata_from_form(self):
        metadata = {key: var.get().strip() for key, var in self.info_vars.items()}
        metadata["author"] = self.creator_username()
        metadata["long_description"] = self.long_description.get("1.0", "end").strip()
        metadata["dependencies"] = self.selected_dependency_metadata()
        metadata["modpack_items"] = []
        if self.current_project:
            metadata = apply_project_type(metadata, self.current_project)
            if metadata.get("is_modpack"):
                metadata["modpack_items"] = self.collect_modpack_items(self.current_project)
        return metadata

    def update_project_type_label(self, metadata=None):
        metadata = metadata or {}
        if self.current_project:
            metadata = apply_project_type(dict(metadata), self.current_project)
        kind = metadata_type(metadata) or "Mod"
        if hasattr(self, "project_type_label"):
            self.project_type_label.configure(text=f"Project Type: {kind}")
        if hasattr(self, "dependencies_box"):
            if metadata.get("is_modpack"):
                self.dependencies_box.pack_forget()
            elif not self.dependencies_box.winfo_ismapped():
                self.dependencies_box.pack(fill="both", expand=False, pady=(0, 8), before=self.long_description_label)

    def dependency_key(self, item):
        return str(item.get("id") or item.get("project_id") or f"{item.get('author', '')}|{item.get('name', '')}").strip()

    def selected_dependency_metadata(self):
        projects = {self.dependency_key(project): project for project in self.dependency_projects}
        selected = []
        for key in self.dependency_vars:
            project = projects.get(key)
            if project:
                selected.append({
                    "id": project.get("id", ""),
                    "project_id": project.get("id", ""),
                    "name": project.get("name", ""),
                    "author": project.get("author", ""),
                    "version": project.get("version", "")
                })
        return selected

    def refresh_dependency_choices(self):
        if not hasattr(self, "dependencies_tree"):
            return
        projects = [project for project in self.latest_index_projects(self.index_projects + self.approved_projects) if not project.get("is_modpack")]
        seen = set()
        self.dependency_projects = []
        for project in projects:
            key = self.dependency_key(project)
            if key and key not in seen:
                seen.add(key)
                self.dependency_projects.append(project)
        self.dependency_projects.sort(key=lambda item: (not self.dependency_vars.get(self.dependency_key(item), False), item.get("name", "").lower()))
        self.dependencies_tree.delete(*self.dependencies_tree.get_children())
        for project in self.dependency_projects:
            key = self.dependency_key(project)
            checked = "x" if self.dependency_vars.get(key, False) else ""
            self.dependencies_tree.insert("", "end", iid=key, values=(checked, project.get("name", ""), project.get("author", ""), project.get("version", "")))

    def on_dependency_click(self, event):
        item_id = self.dependencies_tree.identify_row(event.y)
        if not item_id:
            return "break"
        self.dependency_vars[item_id] = not self.dependency_vars.get(item_id, False)
        if not self.dependency_vars[item_id]:
            self.dependency_vars.pop(item_id, None)
        self.refresh_dependency_choices()
        return "break"

    def save_project(self):
        if not self.require_creator_account():
            return
        if self.editing_approved_project:
            self.save_approved_metadata()
            return
        if not self.current_project:
            messagebox.showerror("Save Project", "No project is loaded.")
            return
        try:
            metadata = self.collect_metadata_from_form()
            self.rename_current_project_folder(metadata.get("name", ""))
            write_json(self.current_project / ".metadata", metadata)
            hide_file(self.current_project / ".metadata")
        except (OSError, ValueError) as error:
            messagebox.showerror("Save Project", str(error))
            return
        self.refresh_project_tree()
        messagebox.showinfo("Save Project", "Project metadata saved.")

    def rename_current_project_folder(self, name):
        folder_name = str(name or "").strip()
        if not folder_name:
            raise ValueError("Project name is required.")
        if Path(folder_name).name != folder_name:
            raise ValueError("Project name cannot contain folder separators.")
        target = self.current_project.with_name(folder_name)
        if target == self.current_project:
            return
        if target.exists():
            raise ValueError("A project folder with that name already exists.")
        self.current_project.rename(target)
        self.current_project = target

    def save_approved_metadata(self):
        if not self.require_creator_account():
            return
        project = self.editing_approved_project
        try:
            metadata = self.collect_metadata_from_form()
        except (BadZipFile, OSError, ValueError, json.JSONDecodeError) as error:
            messagebox.showerror("Save Project", str(error))
            return
        metadata["is_mod"] = bool(project.get("is_mod"))
        metadata["is_modpack"] = bool(project.get("is_modpack"))
        current_project = self.current_project
        local_version_match = self.approved_edit_matches_local_version(project)

        def save():
            validate_metadata(metadata)
            if local_version_match:
                self.validate_icon(metadata, current_project)
            request_metadata = dict(metadata)
            if local_version_match:
                self.add_request_icon(request_metadata, current_project)
            api_json(
                "/api/requests",
                method="POST",
                payload={
                    "metadata": request_metadata,
                    "edit_project_id": project.get("id", ""),
                    "edit_version": project.get("version", "")
                },
                token=self.creator_token()
            )

        def saved(_result):
            self.set_metadata_edit_mode(False)
            self.refresh_approved_projects()
            self.refresh_index_projects()
            messagebox.showinfo(
                "Save Project",
                "Metadata changes were submitted for approval. The approved project and your local metadata have not been changed yet."
            )

        self.run_background_task("Save Project", save, saved)

    def approved_edit_matches_local_version(self, project):
        if not self.current_project:
            return False
        try:
            local_metadata = read_json(self.current_project / ".metadata")
        except (OSError, json.JSONDecodeError):
            return False
        return self.project_match_key(local_metadata) == self.project_match_key(project)

    def publish_project(self):
        if not self.require_creator_account():
            return
        if not self.current_project:
            messagebox.showerror("Publish Project", "No project is loaded.")
            return
        project_path = self.current_project
        try:
            metadata = self.collect_metadata_from_form()
        except (BadZipFile, OSError, ValueError, json.JSONDecodeError) as error:
            messagebox.showerror("Publish Project", str(error))
            return

        def publish():
            validate_metadata(metadata)
            self.validate_project_folder(project_path)
            self.validate_icon(metadata, project_path)
            write_json(project_path / ".metadata", metadata)
            hide_file(project_path / ".metadata")
            request_metadata = dict(metadata)
            self.add_request_icon(request_metadata, project_path)
            api_json(
                "/api/requests",
                method="POST",
                payload={"metadata": request_metadata},
                token=self.creator_token()
            )

        self.run_background_task(
            "Publish Project",
            publish,
            lambda _result: messagebox.showinfo("Publish Project", "Submitted project for approval.")
        )

    def collect_modpack_items(self, project):
        items = []
        for file in sorted((project / "Mods").rglob("*.s4i"), key=lambda item: str(item.relative_to(project / "Mods")).lower()):
            try:
                item = self.read_s4i_metadata(file)
            except (BadZipFile, OSError, ValueError, json.JSONDecodeError):
                item = {
                    "id": file.stem,
                    "project_id": file.stem,
                    "name": file.stem,
                    "author": "",
                    "version": ""
                }
            items.append(item)
        return items

    def read_s4i_metadata(self, s4i_path):
        project_id = s4i_path.stem
        temp_root = None
        try:
            temp_parent = APP_ROOT / "InstallTemp"
            temp_parent.mkdir(parents=True, exist_ok=True)
            temp_root = Path(tempfile.mkdtemp(prefix=f"meta-{project_id}-", dir=temp_parent))
            archive_bytes = decrypt_bytes(s4i_path.read_bytes(), project_id)
            temp_zip = temp_root / "package.zip"
            temp_zip.write_bytes(archive_bytes)
            with ZipFile(temp_zip, "r") as archive:
                extract_archive(archive, temp_root)
            project_root = self.find_project_root(temp_root)
            metadata = read_json(project_root / ".metadata")
            return {
                "id": project_id,
                "project_id": project_id,
                "name": metadata.get("name", project_id),
                "author": metadata.get("author", ""),
                "version": metadata.get("version", "")
            }
        finally:
            if temp_root and temp_root.exists():
                shutil.rmtree(temp_root, ignore_errors=True)

    def validate_project_folder(self, project):
        metadata = apply_project_type(read_json(project / ".metadata"), project)
        for item in project.iterdir():
            if item.name not in PROJECT_ALLOWED:
                raise ValueError(f"File not allowed in project root: {item.name}")
        if not (project / "Mods").is_dir():
            raise ValueError("Missing Mods folder")
        if metadata.get("is_modpack"):
            if (project / "Tray").exists():
                raise ValueError("Modpack projects cannot include a Tray folder.")
            if not folder_has_files(project / "Mods"):
                raise ValueError("Modpack Mods folder cannot be empty.")
            for file in (project / "Mods").rglob("*"):
                if file.is_file() and file.suffix.lower() not in MODPACK_EXTENSIONS:
                    raise ValueError(f"File not allowed in modpack Mods: {file.name}")
            return

        if not (project / "Tray").is_dir():
            raise ValueError("Missing Tray folder")
        if not folder_has_files(project / "Mods") and not folder_has_files(project / "Tray"):
            raise ValueError("Mods and Tray cannot both be empty.")
        for file in (project / "Mods").rglob("*"):
            if file.is_file() and file.suffix.lower() not in MODS_EXTENSIONS:
                raise ValueError(f"File not allowed in Mods: {file.name}")
        for file in (project / "Tray").rglob("*"):
            if file.is_file() and file.suffix.lower() not in TRAY_EXTENSIONS:
                raise ValueError(f"File not allowed in Tray: {file.name}")

    def validate_icon(self, metadata, project=None):
        icon_link = metadata.get("icon", "")
        project = project or self.current_project
        root_icon = project / "Icon.png"
        if root_icon.exists():
            width, height = self.image_size(root_icon)
            if (width, height) != (512, 512):
                raise ValueError("Icon.png must be exactly 512x512 pixels.")
            return
        if not icon_link:
            raise ValueError("Add a project icon link or root Icon.png before saving.")
        local_icon = self.local_icon_path(icon_link)
        if local_icon:
            width, height = self.image_size(local_icon)
            if (width, height) != (512, 512):
                raise ValueError("Project Icon must be exactly 512x512 pixels.")
            return
        parsed = urlparse(icon_link)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Project Icon must be a direct image URL or local image file.")
        width, height = self.remote_image_size(icon_link)
        if (width, height) != (512, 512):
            raise ValueError("Project Icon must be exactly 512x512 pixels.")

    def add_request_icon(self, metadata, project=None):
        project = project or self.current_project
        root_icon = project / "Icon.png"
        icon_path = root_icon if root_icon.exists() else self.local_icon_path(metadata.get("icon", ""))
        if not icon_path:
            return
        mime_type = mimetypes.guess_type(icon_path.name)[0] or "image/png"
        if not mime_type.startswith("image/"):
            raise ValueError("Project Icon must be an image file.")
        metadata["icon"] = f"data:{mime_type};base64,{base64.b64encode(icon_path.read_bytes()).decode('ascii')}"

    def local_icon_path(self, value):
        path_text = str(value or "").strip().strip('"')
        if not path_text:
            return None
        path = Path(path_text).expanduser()
        if path.is_file():
            return path
        return None

    def image_size(self, path):
        if Image:
            with Image.open(path) as image:
                return image.size
        image = tk.PhotoImage(file=str(path))
        return image.width(), image.height()

    def remote_image_size(self, url):
        suffix = Path(urlparse(url).path).suffix or ".img"
        with urlopen(url, timeout=15) as response:
            data = response.read(10 * 1024 * 1024)
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
            temp.write(data)
            temp_path = Path(temp.name)
        try:
            return self.image_size(temp_path)
        finally:
            temp_path.unlink(missing_ok=True)

    def package_project(self, project):
        hide_metadata_file(project)
        metadata = apply_project_type(read_json(project / ".metadata"), project)
        if metadata.get("is_modpack"):
            metadata["modpack_items"] = self.collect_modpack_items(project)
        write_json(project / ".metadata", metadata)
        hide_file(project / ".metadata")
        approved = self.find_approved_project(metadata)
        if not approved:
            raise ValueError("This project is not approved yet.")
        project_id = approved["id"]
        downloads = Path.home() / "Downloads"
        folder_copy = downloads / project.name
        archive_base = downloads / project.name
        zip_path = downloads / f"{project.name}.zip"
        s4i_path = downloads / f"{project_id}.s4i"

        shutil.rmtree(folder_copy, ignore_errors=True)
        zip_path.unlink(missing_ok=True)
        s4i_path.unlink(missing_ok=True)
        shutil.copytree(project, folder_copy)
        shutil.make_archive(str(archive_base), "zip", root_dir=downloads, base_dir=project.name)
        encrypted = encrypt_bytes(zip_path.read_bytes(), project_id)
        s4i_path.write_bytes(encrypted)
        shutil.rmtree(folder_copy)
        zip_path.unlink(missing_ok=True)
        api_json(
            f"/api/projects/{project_id}/sha",
            method="POST",
            payload={"sha256": bytes_sha256(encrypted), "version": metadata.get("version", "")},
            token=self.creator_token()
        )
        return s4i_path

    def import_file(self):
        if not self.require_creator_account():
            return
        if not self.current_project:
            messagebox.showerror("Import File", "No project is loaded.")
            return
        path = filedialog.askopenfilename(title="Import File")
        if not path:
            return
        source = Path(path)
        target_dir = self.current_project
        if project_folder_type(self.current_project) == "modpack" and source.suffix.lower() == ".s4i":
            target_dir = self.current_project / "Mods"
        shutil.copy2(source, target_dir / source.name)
        self.refresh_project_tree()

    def new_file(self):
        if not self.require_creator_account():
            return
        if not self.current_project:
            messagebox.showerror("New File", "No project is loaded.")
            return
        name = simpledialog.askstring("New File", "File name:")
        if not name:
            return
        target = self.current_project / name
        if target.exists():
            messagebox.showerror("New File", "A file with that name already exists.")
            return
        target.touch()
        self.refresh_project_tree()

    def refresh_project_tree(self):
        self.project_tree.delete(*self.project_tree.get_children())
        if not self.current_project:
            return
        hide_metadata_file(self.current_project)
        try:
            self.update_project_type_label(read_json(self.current_project / ".metadata"))
        except (OSError, json.JSONDecodeError):
            pass
        root_id = self.project_tree.insert("", "end", text=self.current_project.name, open=True, values=(str(self.current_project),))
        self.add_tree_children(root_id, self.current_project)

    def add_tree_children(self, parent_id, path):
        for child in sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            if child.name == ".metadata":
                continue
            node = self.project_tree.insert(parent_id, "end", text=child.name, open=True, values=(str(child),))
            if child.is_dir():
                self.add_tree_children(node, child)

    def on_project_tree_press(self, event):
        if not self.has_creator_account():
            self.dragged_tree_path = None
            return
        item_id = self.project_tree.identify_row(event.y)
        if not item_id:
            self.dragged_tree_path = None
            return
        values = self.project_tree.item(item_id, "values")
        self.dragged_tree_path = Path(values[0]) if values else None

    def on_project_tree_release(self, event):
        if not self.has_creator_account():
            return
        source = self.dragged_tree_path
        self.dragged_tree_path = None
        if not source or not self.current_project or source == self.current_project or source.name == ".metadata":
            return
        if self.is_core_project_folder(source):
            return
        target_id = self.project_tree.identify_row(event.y)
        if not target_id:
            return
        values = self.project_tree.item(target_id, "values")
        if not values:
            return
        target = Path(values[0])
        if target.is_file():
            target = target.parent
        if not target.is_dir() or source == target or target in source.parents:
            return
        try:
            shutil.move(str(source), str(target / source.name))
        except OSError as error:
            messagebox.showerror("Move File", str(error))
            return
        self.refresh_project_tree()

    def is_core_project_folder(self, path):
        if not self.current_project or not path.is_dir():
            return False
        return path.parent == self.current_project and path.name in {"Mods", "Tray"}

    def refresh_approved_projects(self):
        if not hasattr(self, "approved_tree"):
            return
        if not self.has_creator_account():
            self.approved_tree.delete(*self.approved_tree.get_children())
            self.approved_projects = []
            self.approved_project_paths = {}
            return

        def load():
            response = api_json("/api/projects?mine=1&include_obsolete=1", token=self.creator_token())
            local_projects = self.local_projects_by_metadata()
            approved_projects = []
            approved_paths = {}
            for project in response.get("projects", []):
                key = self.project_identity_key(project)
                local_path = local_projects.get(key)
                approved_projects.append(project)
                if local_path:
                    approved_paths[self.approved_row_id(project)] = local_path
            return approved_projects, approved_paths

        def apply(result):
            projects, paths = result
            self.approved_tree.delete(*self.approved_tree.get_children())
            self.approved_projects = projects
            self.approved_project_paths = paths
            self.refresh_dependency_choices()
            for project in projects:
                row_id = self.approved_row_id(project)
                self.approved_tree.insert(
                    "",
                    "end",
                    iid=row_id,
                    values=(
                        project.get("name", ""),
                        author_display(project),
                        project.get("version", ""),
                        "Obsolete" if project.get("obsolete") else "Active",
                        project.get("id", "")
                    ),
                    tags=("obsolete",) if project.get("obsolete") else ()
                )

        self.run_background_task("Approved Projects", load, apply)

    def local_projects_by_metadata(self):
        projects = {}
        if not PROJECTS_ROOT.exists():
            return projects
        for metadata_path in PROJECTS_ROOT.glob("*/.metadata"):
            try:
                metadata = read_json(metadata_path)
            except (OSError, json.JSONDecodeError):
                continue
            hide_file(metadata_path)
            projects[self.project_identity_key(metadata)] = metadata_path.parent
        return projects

    def project_identity_key(self, project):
        return (
            str(project.get("name", "")).strip().lower(),
            str(project.get("author", "")).strip().lower()
        )

    def project_match_key(self, project):
        return (
            str(project.get("name", "")).strip().lower(),
            str(project.get("author", "")).strip().lower(),
            str(project.get("version", "")).strip().lower()
        )

    def find_approved_project(self, metadata):
        key = self.project_match_key(metadata)
        return next((project for project in self.approved_projects if self.project_match_key(project) == key), None)

    def on_approved_right_click(self, event):
        item_id = self.approved_tree.identify_row(event.y)
        if not item_id:
            return
        self.approved_context_id = item_id
        self.approved_menu.tk_popup(event.x_root, event.y_root)

    def package_selected_approved_project(self):
        if not self.require_creator_account():
            return
        if not self.approved_context_id:
            return
        project_path = self.approved_project_paths.get(self.approved_context_id)
        if not project_path:
            messagebox.showerror("Package", "Could not find the local project folder.")
            return

        def package():
            self.validate_project_folder(project_path)
            return self.package_project(project_path)

        self.run_background_task(
            "Package",
            package,
            lambda output: messagebox.showinfo("Package", f"Saved {output.name} to Downloads.")
        )

    def selected_approved_project(self):
        if not self.approved_context_id:
            return None
        return next((project for project in self.approved_projects if self.approved_row_id(project) == self.approved_context_id), None)

    def approved_row_id(self, project):
        return f"{project.get('id', '')}::{project.get('version', '')}"

    def edit_selected_approved_metadata(self):
        if not self.require_creator_account():
            return
        project = self.selected_approved_project()
        if not project:
            return
        local_path = self.approved_project_paths.get(self.approved_context_id)
        self.current_project = local_path
        self.editing_approved_project = project
        self.load_metadata_into_form(project)
        self.set_metadata_edit_mode(True)
        self.tabs.select("Creator")

    def set_metadata_edit_mode(self, active):
        self.editing_approved_project = self.editing_approved_project if active else None
        for text, button in self.creator_buttons.items():
            enabled = self.has_creator_account() and (text == "Save Project" or not active)
            button.configure(state="normal" if enabled else "disabled")
        for checkbox in self.info_bool_widgets.values():
            checkbox.configure(state="disabled" if active else "normal")

    def mark_selected_project_obsolete(self):
        if not self.require_creator_account():
            return
        project = self.selected_approved_project()
        if not project:
            return
        if project.get("obsolete"):
            messagebox.showinfo("Mark as Obsolete", "This project version is already obsolete.")
            return

        def mark():
            api_json(
                f"/api/projects/{project['id']}/obsolete",
                method="POST",
                payload={"version": project.get("version", "")},
                token=self.creator_token()
            )

        self.run_background_task("Mark as Obsolete", mark, lambda _result: self.refresh_approved_projects())

    def delete_selected_approved_project(self):
        if not self.require_creator_account():
            return
        project = self.selected_approved_project()
        if not project:
            return
        prompt = (
            "Move this project to trash?\n\n"
            "It will be permanently deleted after 30 days unless an admin restores it."
        )
        if not messagebox.askyesno("Delete Project", prompt):
            return

        def delete():
            api_json(
                f"/api/projects/{project['id']}/trash",
                method="POST",
                payload={"version": project.get("version", "")},
                token=self.creator_token()
            )

        self.run_background_task("Delete Project", delete, lambda _result: self.refresh_approved_projects())

    def selected_tree_path(self):
        selected = self.project_tree.selection()
        if not selected:
            return None
        values = self.project_tree.item(selected[0], "values")
        return Path(values[0]) if values else None

    def edit_or_save_file(self):
        if not self.require_creator_account():
            return
        if self.editing_file:
            self.save_and_close_file()
            return

        path = self.selected_tree_path()
        if not path or not path.is_file():
            messagebox.showerror("Edit File", "Select a readable file first.")
            return
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            messagebox.showerror("Edit File", "They can't read that file.")
            return
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            messagebox.showerror("Edit File", "They can't read that file.")
            return

        for child in self.info_panel.winfo_children():
            child.destroy()
        self.editing_file = path
        self.edit_button.configure(text="Save And Close File")
        ttk.Label(self.info_panel, text=path.name).pack(anchor="w", pady=(0, 6))
        self.editor = tk.Text(self.info_panel, wrap="word")
        self.editor.insert("1.0", text)
        self.editor.pack(fill="both", expand=True)

    def save_and_close_file(self):
        try:
            self.editing_file.write_text(self.editor.get("1.0", "end-1c"), encoding="utf-8")
        except OSError as error:
            messagebox.showerror("Edit File", str(error))
            return
        self.build_info_form()
        if self.current_project and (self.current_project / ".metadata").exists():
            try:
                self.load_metadata_into_form(read_json(self.current_project / ".metadata"))
            except (OSError, json.JSONDecodeError):
                pass
        self.refresh_project_tree()


if __name__ == "__main__":
    app = SimdexApp()
    app.mainloop()
