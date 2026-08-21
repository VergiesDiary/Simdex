from .common import *


class IndexMixin:
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
