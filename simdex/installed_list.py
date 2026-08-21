from .common import *


class InstalledListMixin:
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
