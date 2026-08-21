from .common import *


class CoreMixin:
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
