from .common import *


class CreatorPublishMixin:
    def save_approved_metadata(self):
        if not self.require_creator_account():
            return
        project = self.editing_approved_project
        try:
            metadata = self.collect_metadata_from_form()
        except (BadZipFile, OSError, ValueError, json.JSONDecodeError) as error:
            messagebox.showerror("Save Project", str(error))
            return
        metadata["is_mod"] = bool(project.get("is_mod"))
        metadata["is_modpack"] = bool(project.get("is_modpack"))
        current_project = self.current_project
        local_version_match = self.approved_edit_matches_local_version(project)

        def save():
            validate_metadata(metadata)
            if local_version_match:
                self.validate_icon(metadata, current_project)
            request_metadata = dict(metadata)
            if local_version_match:
                self.add_request_icon(request_metadata, current_project)
            api_json(
                "/api/requests",
                method="POST",
                payload={
                    "metadata": request_metadata,
                    "edit_project_id": project.get("id", ""),
                    "edit_version": project.get("version", "")
                },
                token=self.creator_token()
            )

        def saved(_result):
            self.set_metadata_edit_mode(False)
            self.refresh_approved_projects()
            self.refresh_index_projects()
            messagebox.showinfo(
                "Save Project",
                "Metadata changes were submitted for approval. The approved project and your local metadata have not been changed yet."
            )

        self.run_background_task("Save Project", save, saved)

    def approved_edit_matches_local_version(self, project):
        if not self.current_project:
            return False
        try:
            local_metadata = read_json(self.current_project / ".metadata")
        except (OSError, json.JSONDecodeError):
            return False
        return self.project_match_key(local_metadata) == self.project_match_key(project)

    def publish_project(self):
        if not self.require_creator_account():
            return
        if not self.current_project:
            messagebox.showerror("Publish Project", "No project is loaded.")
            return
        project_path = self.current_project
        try:
            metadata = self.collect_metadata_from_form()
        except (BadZipFile, OSError, ValueError, json.JSONDecodeError) as error:
            messagebox.showerror("Publish Project", str(error))
            return

        def publish():
            validate_metadata(metadata)
            self.validate_project_folder(project_path)
            self.validate_icon(metadata, project_path)
            write_json(project_path / ".metadata", metadata)
            hide_file(project_path / ".metadata")
            request_metadata = dict(metadata)
            self.add_request_icon(request_metadata, project_path)
            api_json(
                "/api/requests",
                method="POST",
                payload={"metadata": request_metadata},
                token=self.creator_token()
            )

        self.run_background_task(
            "Publish Project",
            publish,
            lambda _result: messagebox.showinfo("Publish Project", "Submitted project for approval.")
        )

    def collect_modpack_items(self, project):
        items = []
        for file in sorted((project / "Mods").rglob("*.s4i"), key=lambda item: str(item.relative_to(project / "Mods")).lower()):
            try:
                item = self.read_s4i_metadata(file)
            except (BadZipFile, OSError, ValueError, json.JSONDecodeError):
                item = {
                    "id": file.stem,
                    "project_id": file.stem,
                    "name": file.stem,
                    "author": "",
                    "version": ""
                }
            items.append(item)
        return items

    def read_s4i_metadata(self, s4i_path):
        project_id = s4i_path.stem
        temp_root = None
        try:
            temp_parent = APP_ROOT / "InstallTemp"
            temp_parent.mkdir(parents=True, exist_ok=True)
            temp_root = Path(tempfile.mkdtemp(prefix=f"meta-{project_id}-", dir=temp_parent))
            archive_bytes = decrypt_bytes(s4i_path.read_bytes(), project_id)
            temp_zip = temp_root / "package.zip"
            temp_zip.write_bytes(archive_bytes)
            with ZipFile(temp_zip, "r") as archive:
                extract_archive(archive, temp_root)
            project_root = self.find_project_root(temp_root)
            metadata = read_json(project_root / ".metadata")
            return {
                "id": project_id,
                "project_id": project_id,
                "name": metadata.get("name", project_id),
                "author": metadata.get("author", ""),
                "version": metadata.get("version", "")
            }
        finally:
            if temp_root and temp_root.exists():
                shutil.rmtree(temp_root, ignore_errors=True)

    def validate_project_folder(self, project):
        metadata = apply_project_type(read_json(project / ".metadata"), project)
        for item in project.iterdir():
            if item.name not in PROJECT_ALLOWED:
                raise ValueError(f"File not allowed in project root: {item.name}")
        if not (project / "Mods").is_dir():
            raise ValueError("Missing Mods folder")
        if metadata.get("is_modpack"):
            if (project / "Tray").exists():
                raise ValueError("Modpack projects cannot include a Tray folder.")
            if not folder_has_files(project / "Mods"):
                raise ValueError("Modpack Mods folder cannot be empty.")
            for file in (project / "Mods").rglob("*"):
                if file.is_file() and file.suffix.lower() not in MODPACK_EXTENSIONS:
                    raise ValueError(f"File not allowed in modpack Mods: {file.name}")
            return

        if not (project / "Tray").is_dir():
            raise ValueError("Missing Tray folder")
        if not folder_has_files(project / "Mods") and not folder_has_files(project / "Tray"):
            raise ValueError("Mods and Tray cannot both be empty.")
        for file in (project / "Mods").rglob("*"):
            if file.is_file() and file.suffix.lower() not in MODS_EXTENSIONS:
                raise ValueError(f"File not allowed in Mods: {file.name}")
        for file in (project / "Tray").rglob("*"):
            if file.is_file() and file.suffix.lower() not in TRAY_EXTENSIONS:
                raise ValueError(f"File not allowed in Tray: {file.name}")

    def validate_icon(self, metadata, project=None):
        icon_link = metadata.get("icon", "")
        project = project or self.current_project
        root_icon = project / "Icon.png"
        if root_icon.exists():
            width, height = self.image_size(root_icon)
            if (width, height) != (512, 512):
                raise ValueError("Icon.png must be exactly 512x512 pixels.")
            return
        if not icon_link:
            raise ValueError("Add a project icon link or root Icon.png before saving.")
        local_icon = self.local_icon_path(icon_link)
        if local_icon:
            width, height = self.image_size(local_icon)
            if (width, height) != (512, 512):
                raise ValueError("Project Icon must be exactly 512x512 pixels.")
            return
        parsed = urlparse(icon_link)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Project Icon must be a direct image URL or local image file.")
        width, height = self.remote_image_size(icon_link)
        if (width, height) != (512, 512):
            raise ValueError("Project Icon must be exactly 512x512 pixels.")

    def add_request_icon(self, metadata, project=None):
        project = project or self.current_project
        root_icon = project / "Icon.png"
        icon_path = root_icon if root_icon.exists() else self.local_icon_path(metadata.get("icon", ""))
        if not icon_path:
            return
        mime_type = mimetypes.guess_type(icon_path.name)[0] or "image/png"
        if not mime_type.startswith("image/"):
            raise ValueError("Project Icon must be an image file.")
        metadata["icon"] = f"data:{mime_type};base64,{base64.b64encode(icon_path.read_bytes()).decode('ascii')}"

    def local_icon_path(self, value):
        path_text = str(value or "").strip().strip('"')
        if not path_text:
            return None
        path = Path(path_text).expanduser()
        if path.is_file():
            return path
        return None

    def image_size(self, path):
        if Image:
            with Image.open(path) as image:
                return image.size
        image = tk.PhotoImage(file=str(path))
        return image.width(), image.height()

    def remote_image_size(self, url):
        suffix = Path(urlparse(url).path).suffix or ".img"
        with urlopen(url, timeout=15) as response:
            data = response.read(10 * 1024 * 1024)
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
            temp.write(data)
            temp_path = Path(temp.name)
        try:
            return self.image_size(temp_path)
        finally:
            temp_path.unlink(missing_ok=True)

    def package_project(self, project):
        hide_metadata_file(project)
        metadata = apply_project_type(read_json(project / ".metadata"), project)
        if metadata.get("is_modpack"):
            metadata["modpack_items"] = self.collect_modpack_items(project)
        write_json(project / ".metadata", metadata)
        hide_file(project / ".metadata")
        approved = self.find_approved_project(metadata)
        if not approved:
            raise ValueError("This project is not approved yet.")
        project_id = approved["id"]
        downloads = Path.home() / "Downloads"
        folder_copy = downloads / project.name
        archive_base = downloads / project.name
        zip_path = downloads / f"{project.name}.zip"
        s4i_path = downloads / f"{project_id}.s4i"

        shutil.rmtree(folder_copy, ignore_errors=True)
        zip_path.unlink(missing_ok=True)
        s4i_path.unlink(missing_ok=True)
        shutil.copytree(project, folder_copy)
        shutil.make_archive(str(archive_base), "zip", root_dir=downloads, base_dir=project.name)
        encrypted = encrypt_bytes(zip_path.read_bytes(), project_id)
        s4i_path.write_bytes(encrypted)
        shutil.rmtree(folder_copy)
        zip_path.unlink(missing_ok=True)
        api_json(
            f"/api/projects/{project_id}/sha",
            method="POST",
            payload={"sha256": bytes_sha256(encrypted), "version": metadata.get("version", "")},
            token=self.creator_token()
        )
        return s4i_path

    def import_file(self):
        if not self.require_creator_account():
            return
        if not self.current_project:
            messagebox.showerror("Import File", "No project is loaded.")
            return
        path = filedialog.askopenfilename(title="Import File")
        if not path:
            return
        source = Path(path)
        target_dir = self.current_project
        if project_folder_type(self.current_project) == "modpack" and source.suffix.lower() == ".s4i":
            target_dir = self.current_project / "Mods"
        shutil.copy2(source, target_dir / source.name)
        self.refresh_project_tree()

    def new_file(self):
        if not self.require_creator_account():
            return
        if not self.current_project:
            messagebox.showerror("New File", "No project is loaded.")
            return
        name = simpledialog.askstring("New File", "File name:")
        if not name:
            return
        target = self.current_project / name
        if target.exists():
            messagebox.showerror("New File", "A file with that name already exists.")
            return
        target.touch()
        self.refresh_project_tree()

    def refresh_project_tree(self):
        self.project_tree.delete(*self.project_tree.get_children())
        if not self.current_project:
            return
        hide_metadata_file(self.current_project)
        try:
            self.update_project_type_label(read_json(self.current_project / ".metadata"))
        except (OSError, json.JSONDecodeError):
            pass
        root_id = self.project_tree.insert("", "end", text=self.current_project.name, open=True, values=(str(self.current_project),))
        self.add_tree_children(root_id, self.current_project)

    def add_tree_children(self, parent_id, path):
        for child in sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            if child.name == ".metadata":
                continue
            node = self.project_tree.insert(parent_id, "end", text=child.name, open=True, values=(str(child),))
            if child.is_dir():
                self.add_tree_children(node, child)

    def on_project_tree_press(self, event):
        if not self.has_creator_account():
            self.dragged_tree_path = None
            return
        item_id = self.project_tree.identify_row(event.y)
        if not item_id:
            self.dragged_tree_path = None
            return
        values = self.project_tree.item(item_id, "values")
        self.dragged_tree_path = Path(values[0]) if values else None

    def on_project_tree_release(self, event):
        if not self.has_creator_account():
            return
        source = self.dragged_tree_path
        self.dragged_tree_path = None
        if not source or not self.current_project or source == self.current_project or source.name == ".metadata":
            return
        if self.is_core_project_folder(source):
            return
        target_id = self.project_tree.identify_row(event.y)
        if not target_id:
            return
        values = self.project_tree.item(target_id, "values")
        if not values:
            return
        target = Path(values[0])
        if target.is_file():
            target = target.parent
        if not target.is_dir() or source == target or target in source.parents:
            return
        try:
            shutil.move(str(source), str(target / source.name))
        except OSError as error:
            messagebox.showerror("Move File", str(error))
            return
        self.refresh_project_tree()

    def is_core_project_folder(self, path):
        if not self.current_project or not path.is_dir():
            return False
        return path.parent == self.current_project and path.name in {"Mods", "Tray"}
