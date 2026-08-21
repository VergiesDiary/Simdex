import base64
import ctypes
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    AESGCM = None

from .config import *

def bundled_path(name):
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
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
