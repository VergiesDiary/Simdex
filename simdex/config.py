import os
from pathlib import Path



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

