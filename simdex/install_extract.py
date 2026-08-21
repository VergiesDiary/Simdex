from .common import *


class InstallExtractMixin:
    def extract_and_install(self, s4i_path, parent_modpack=None, install_job=None):
        temp_root = None
        installed_paths = {}
        installed_files = {}
        project_id = s4i_path.stem
        try:
            project = api_json(f"/api/projects/{project_id}")
            if not project.get("project"):
                raise ValueError("No approved project was found for this file id.")
            approved = project["project"]
            if approved.get("obsolete"):
                prompt = (
                    "This version is marked obsolete.\n\n"
                    f"{approved.get('name', project_id)} {approved.get('version', '')}\n\n"
                    "Continue with the install?"
                )
                if not messagebox.askyesno("Obsolete version", prompt):
                    return None
            if approved.get("sha256") and approved["sha256"].lower() != file_sha256(s4i_path).lower():
                raise ValueError("The install file does not match the approved project.")
            self.update_install_job_name(install_job, approved, s4i_path)

            temp_parent = APP_ROOT / "InstallTemp"
            temp_parent.mkdir(parents=True, exist_ok=True)
            temp_root = Path(tempfile.mkdtemp(prefix=f"{project_id}-", dir=temp_parent))
            encrypted = s4i_path.read_bytes()
            archive_bytes = decrypt_bytes(encrypted, project_id)
            temp_zip = temp_root / "package.zip"
            temp_zip.write_bytes(archive_bytes)
            with ZipFile(temp_zip, "r") as archive:
                extract_archive(archive, temp_root)
            temp_zip.unlink(missing_ok=True)

            project_root = self.find_project_root(temp_root)
            metadata_path = project_root / ".metadata"
            if not metadata_path.exists():
                raise ValueError("Missing .metadata")
            metadata = read_json(metadata_path)
            validate_metadata(metadata)
            metadata = apply_project_type(metadata, project_root)
            candidate = {
                "project_id": project_id,
                "name": metadata["name"],
                "author": metadata["author"],
                "version": metadata.get("version", "")
            }
            if metadata.get("is_modpack"):
                return self.extract_and_install_modpack(s4i_path, project_id, project_root, metadata, approved)
            self.prompt_for_missing_dependencies(metadata)
            existing = self.find_existing_install(candidate)
            if existing:
                if existing.get("version") == candidate["version"]:
                    self.apply_approved_metadata(existing, approved)
                    self.save_installed_mods()
                    self.refresh_mod_list()
                    self.refresh_index_list()
                    messagebox.showinfo("Install", "You already have this mod installed.")
                    return None
                prompt = (
                    f"You already have {existing.get('name')} installed.\n\n"
                    f"Current version: {existing.get('version')}\n"
                    f"New version: {candidate['version']}\n\n"
                    "Overwrite the current install?"
                )
                if not messagebox.askyesno("Overwrite install", prompt):
                    return None

            folder_name = install_folder_name(metadata["author"], metadata["name"])
            mods_source = project_root / "Mods"
            tray_source = project_root / "Tray"
            has_mods = folder_has_files(mods_source)
            has_tray = folder_has_files(tray_source)

            if not has_mods and not has_tray:
                raise ValueError("No files found in Mods or Tray")

            if has_mods:
                target = SIMS_MODS / folder_name
                staged = temp_root / "StagedInstall" / "mods"
                shutil.copytree(mods_source, staged)
                installed_paths["mods"] = str(target)
                installed_files["mods"] = relative_files(staged)
            if has_tray:
                target = SIMS_TRAY / folder_name
                staged = temp_root / "StagedInstall" / "tray"
                shutil.copytree(tray_source, staged)
                installed_paths["tray"] = str(target)
                installed_files["tray"] = relative_files(staged)

            self.commit_staged_install(temp_root / "StagedInstall", installed_paths, existing)
            if existing:
                self.remove_disabled_files(existing)
                self.remove_app_kept_files(existing)
                self.installed_mods = [item for item in self.installed_mods if item.get("id") != existing.get("id")]

            icon_path = None
            root_icon = project_root / "Icon.png"
            if root_icon.exists():
                icon_target = APP_ROOT / "Icons" / f"{folder_name}.png"
                icon_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(root_icon, icon_target)
                icon_path = str(icon_target)

            final_extract = APP_ROOT / "InstalledSources" / project_id
            if final_extract.exists():
                shutil.rmtree(final_extract)
            final_extract.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(project_root, final_extract)
            hide_metadata_file(final_extract)

            mod = {
                "id": f"{folder_name}-{int(time.time() * 1000)}",
                "project_id": project_id,
                "name": metadata["name"],
                "short_description": metadata["short_description"],
                "author": metadata["author"],
                "version": metadata.get("version", ""),
                "is_mod": bool(metadata.get("is_mod")),
                "is_modpack": bool(metadata.get("is_modpack")),
                "dependencies": metadata.get("dependencies", []),
                "modpack_parent_id": parent_modpack.get("project_id", "") if parent_modpack else "",
                "modpack_parent_name": parent_modpack.get("name", "") if parent_modpack else "",
                "obsolete": bool(approved.get("obsolete")),
                "creator_verified": bool(approved.get("creator_verified")),
                "download_page": metadata.get("download_page", ""),
                "icon": metadata.get("icon", ""),
                "icon_path": icon_path,
                "long_description": metadata.get("long_description", ""),
                "source_s4i": str(s4i_path),
                "source_extract": str(final_extract),
                "installed_paths": installed_paths,
                "installed_files": installed_files,
                "disabled_paths": {},
                "enabled": True,
                "favorite": False,
                "status": "ok"
            }
            self.apply_approved_metadata(mod, approved)
            return mod
        except Exception:
            raise
        finally:
            if temp_root and temp_root.exists():
                shutil.rmtree(temp_root, ignore_errors=True)

    def extract_and_install_modpack(self, s4i_path, project_id, project_root, metadata, approved):
        mods_source = project_root / "Mods"
        s4i_files = sorted(mods_source.rglob("*.s4i"), key=lambda item: str(item.relative_to(mods_source)).lower())
        if not s4i_files:
            raise ValueError("Modpack Mods folder does not contain any .s4i files.")

        folder_name = install_folder_name(metadata["author"], metadata["name"])
        existing = self.find_existing_install({
            "project_id": project_id,
            "name": metadata["name"],
            "author": metadata["author"],
            "version": metadata.get("version", "")
        })
        if existing and existing.get("version") == metadata.get("version", ""):
            messagebox.showinfo("Install", "You already have this modpack installed.")
            return None
        if existing:
            prompt = (
                f"You already have {existing.get('name')} installed.\n\n"
                f"Current version: {existing.get('version')}\n"
                f"New version: {metadata.get('version', '')}\n\n"
                "Overwrite the current install?"
            )
            if not messagebox.askyesno("Overwrite install", prompt):
                return None
            self.uninstall_mod(existing["id"])

        parent = {"project_id": project_id, "name": metadata["name"]}
        installed_items = []
        for child_s4i in s4i_files:
            try:
                child_info = self.read_s4i_metadata(child_s4i)
            except (BadZipFile, OSError, ValueError, json.JSONDecodeError):
                child_info = {}
            existing_child = self.find_installed_version({
                "project_id": child_info.get("project_id") or child_info.get("id"),
                "name": child_info.get("name"),
                "author": child_info.get("author"),
                "version": child_info.get("version")
            }) if child_info else None
            if existing_child:
                installed_items.append({
                    "id": existing_child.get("project_id", ""),
                    "project_id": existing_child.get("project_id", ""),
                    "name": existing_child.get("name", ""),
                    "author": existing_child.get("author", ""),
                    "version": existing_child.get("version", ""),
                    "installed_id": existing_child.get("id", ""),
                    "external": True
                })
                continue
            existing_child = self.find_existing_install({
                "project_id": child_info.get("project_id") or child_info.get("id"),
                "name": child_info.get("name"),
                "author": child_info.get("author")
            }) if child_info else None
            if existing_child:
                child = self.extract_and_install(child_s4i)
                if child:
                    self.installed_mods.append(child)
                    installed_items.append({
                        "id": child.get("project_id", ""),
                        "project_id": child.get("project_id", ""),
                        "name": child.get("name", ""),
                        "author": child.get("author", ""),
                        "version": child.get("version", ""),
                        "installed_id": child.get("id", ""),
                        "external": True
                    })
                continue
            child = self.extract_and_install(child_s4i, parent)
            if child:
                installed_items.append({
                    "id": child.get("project_id", ""),
                    "project_id": child.get("project_id", ""),
                    "name": child.get("name", ""),
                    "author": child.get("author", ""),
                    "version": child.get("version", ""),
                    "installed_id": child.get("id", ""),
                    "external": False,
                    "installed_paths": child.get("installed_paths", {}),
                    "installed_files": child.get("installed_files", {}),
                    "disabled_paths": {},
                    "enabled": True,
                    "source_extract": child.get("source_extract", ""),
                    "icon_path": child.get("icon_path", "")
                })

        icon_path = None
        root_icon = project_root / "Icon.png"
        if root_icon.exists():
            icon_target = APP_ROOT / "Icons" / f"{folder_name}.png"
            icon_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root_icon, icon_target)
            icon_path = str(icon_target)

        final_extract = APP_ROOT / "InstalledSources" / project_id
        if final_extract.exists():
            shutil.rmtree(final_extract)
        final_extract.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(project_root, final_extract)
        hide_metadata_file(final_extract)

        modpack = {
            "id": f"{folder_name}-{int(time.time() * 1000)}",
            "project_id": project_id,
            "name": metadata["name"],
            "short_description": metadata["short_description"],
            "author": metadata["author"],
            "version": metadata.get("version", ""),
            "is_mod": False,
            "is_modpack": True,
            "dependencies": [],
            "modpack_items": installed_items or metadata.get("modpack_items", []),
            "obsolete": bool(approved.get("obsolete")),
            "creator_verified": bool(approved.get("creator_verified")),
            "download_page": metadata.get("download_page", ""),
            "icon": metadata.get("icon", ""),
            "icon_path": icon_path,
            "long_description": metadata.get("long_description", ""),
            "source_s4i": str(s4i_path),
            "source_extract": str(final_extract),
            "installed_paths": {},
            "installed_files": {},
            "disabled_paths": {},
            "enabled": True,
            "favorite": False,
            "status": "ok"
        }
        self.apply_approved_metadata(modpack, approved)
        return modpack

    def installed_child_for_modpack(self, s4i_path):
        try:
            item = self.read_s4i_metadata(s4i_path)
        except (BadZipFile, OSError, ValueError, json.JSONDecodeError):
            return None
        return self.find_installed_version({
            "project_id": item.get("project_id") or item.get("id"),
            "name": item.get("name"),
            "author": item.get("author"),
            "version": item.get("version")
        })

    def prompt_for_missing_dependencies(self, metadata):
        dependencies = metadata.get("dependencies", [])
        if not dependencies:
            return
        missing = [item for item in dependencies if not self.find_existing_install(item)]
        if not missing:
            return
        names = "\n".join(f"- {item.get('name', 'Unknown')} {item.get('version', '')}".strip() for item in missing)
        if not messagebox.askyesno("Dependencies", f"This mod has missing dependencies:\n\n{names}\n\nOpen their download pages?"):
            return
        for item in missing:
            project = self.find_project_ref(item)
            if project and project.get("download_page"):
                self.open_download_page(project["download_page"])

    def find_existing_install(self, mod):
        project_id = mod.get("project_id")
        if project_id:
            match = next((item for item in self.installed_mods if item.get("project_id") == project_id), None)
            if match:
                return match
        return next(
            (
                item for item in self.installed_mods
                if item.get("name") == mod.get("name") and item.get("author") == mod.get("author")
            ),
            None
        )

    def find_installed_version(self, mod):
        project_id = mod.get("project_id")
        version = mod.get("version")
        if project_id:
            match = next(
                (
                    item for item in self.installed_mods
                    if item.get("project_id") == project_id and item.get("version") == version
                ),
                None
            )
            if match:
                return match
        return next(
            (
                item for item in self.installed_mods
                if item.get("name") == mod.get("name")
                and item.get("author") == mod.get("author")
                and item.get("version") == version
            ),
            None
        )

    def find_project_root(self, extract_root):
        if (extract_root / ".metadata").exists():
            return extract_root
        matches = list(extract_root.glob("*/.metadata"))
        if len(matches) == 1:
            return matches[0].parent
        raise ValueError("Could not find a single project root")

    def commit_staged_install(self, staged_root, installed_paths, existing):
        backup_root = APP_ROOT / "InstallBackups" / f"{int(time.time() * 1000)}"
        backups = []
        moved_targets = []
        try:
            backup_root.mkdir(parents=True, exist_ok=True)
            existing_paths = existing.get("installed_paths", {}) if existing else {}
            for key, path_text in existing_paths.items():
                path = Path(path_text)
                if not path.exists():
                    continue
                backup = backup_root / f"old-{key}"
                shutil.move(str(path), str(backup))
                backups.append((path, backup))

            for key, path_text in installed_paths.items():
                target = Path(path_text)
                if target.exists():
                    backup = backup_root / f"target-{key}"
                    shutil.move(str(target), str(backup))
                    backups.append((target, backup))
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(staged_root / key), str(target))
                moved_targets.append(target)

            shutil.rmtree(backup_root, ignore_errors=True)
        except Exception:
            for target in moved_targets:
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
            for target, backup in reversed(backups):
                if backup.exists():
                    if target.exists():
                        shutil.rmtree(target, ignore_errors=True)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(backup), str(target))
            shutil.rmtree(backup_root, ignore_errors=True)
            raise

    def uninstall_context_mod(self):
        if self.context_mod_id:
            self.uninstall_mod(self.context_mod_id)

    def uninstall_mod(self, mod_id):
        mod = self.find_mod(mod_id)
        if not mod:
            return
        if mod.get("is_modpack"):
            for child in list(self.installed_mods):
                if child.get("modpack_parent_id") == mod.get("project_id"):
                    self.uninstall_mod(child["id"])
        self.remove_installed_files(mod)
        self.remove_disabled_files(mod)
        self.remove_app_kept_files(mod)
        self.installed_mods = [item for item in self.installed_mods if item.get("id") != mod_id]
        self.selected_mod_ids.discard(mod_id)
        self.close_mod_panels(mod_id)
        self.save_installed_mods()
        self.refresh_mod_list()
        self.refresh_index_list()

    def close_mod_panels(self, mod_id):
        suffix = f"({mod_id[:8]})"
        for name in list(self.temp_panels):
            if name.endswith(suffix):
                self.close_temp_panel(name)

    def remove_installed_files(self, mod):
        if mod.get("is_modpack"):
            for item in mod.get("modpack_items", []):
                if not item.get("external"):
                    self.remove_installed_files(item)
        for path in mod.get("installed_paths", {}).values():
            install_path = Path(path)
            if install_path.exists():
                shutil.rmtree(install_path)

    def remove_disabled_files(self, mod):
        if mod.get("is_modpack"):
            for item in mod.get("modpack_items", []):
                if not item.get("external"):
                    self.remove_disabled_files(item)
        for path in self.mod_disabled_paths(mod).values():
            disabled_path = Path(path)
            if disabled_path.exists():
                shutil.rmtree(disabled_path)
        disabled_root = DISABLED_MODS_ROOT / self.disabled_folder_name(mod)
        if disabled_root.exists() and not any(disabled_root.iterdir()):
            disabled_root.rmdir()

    def remove_app_kept_files(self, mod):
        if mod.get("is_modpack"):
            for item in mod.get("modpack_items", []):
                if not item.get("external"):
                    self.remove_app_kept_files(item)
        source_extract = mod.get("source_extract")
        if source_extract:
            source_path = Path(source_extract)
            if self.is_app_path(source_path) and source_path.exists():
                shutil.rmtree(source_path)

        icon_path = mod.get("icon_path")
        if icon_path:
            icon_file = Path(icon_path)
            if self.is_app_path(icon_file) and icon_file.exists():
                icon_file.unlink()

    def is_app_path(self, path):
        try:
            path.resolve().relative_to(APP_ROOT.resolve())
        except ValueError:
            return False
        return True
