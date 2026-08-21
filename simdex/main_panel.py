from .common import *


class MainPanelMixin:
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
