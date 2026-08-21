from .common import *


class CreatorFormMixin:
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
