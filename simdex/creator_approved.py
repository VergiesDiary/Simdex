from .common import *


class CreatorApprovedMixin:
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
