from .common import *


class ProjectPanelsMixin:
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
