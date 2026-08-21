from .common import *
from .core import CoreMixin
from .creator_account import CreatorAccountMixin
from .guides import GuidesMixin
from .index import IndexMixin
from .creator_approved import CreatorApprovedMixin
from .creator_form import CreatorFormMixin
from .creator_publish import CreatorPublishMixin
from .creator_ui import CreatorUiMixin
from .install_extract import InstallExtractMixin
from .install_queue import InstallQueueMixin
from .installed_list import InstalledListMixin
from .project_panels import ProjectPanelsMixin
from .main_panel import MainPanelMixin


class SimdexApp(
    tk.Tk,
    CoreMixin,
    CreatorAccountMixin,
    MainPanelMixin,
    IndexMixin,
    InstalledListMixin,
    ProjectPanelsMixin,
    InstallQueueMixin,
    InstallExtractMixin,
    CreatorUiMixin,
    CreatorFormMixin,
    CreatorPublishMixin,
    CreatorApprovedMixin,
    GuidesMixin
):
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
