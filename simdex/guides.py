from .common import *


class GuidesMixin:
    def build_guides_panel(self):
        shell = ttk.Frame(self.guides_panel, padding=16)
        shell.pack(fill="both", expand=True)
        ttk.Label(shell, text="Guides", font=("Segoe UI", 18, "bold")).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            shell,
            text="Choose a visual guide. Each guide will point at the controls it explains with yellow arrows and short on-screen notes.",
            wraplength=720
        ).pack(anchor="w", pady=(0, 16))

        buttons = ttk.Frame(shell)
        buttons.pack(anchor="nw", fill="x")
        guides = [
            ("Quick Tour", "quick"),
            ("Installing Projects", "installing"),
            ("Managing Installed Projects", "installed"),
            ("Browsing the Mod Index", "index"),
            ("Creator Workflow", "creator"),
            ("Modpacks and Dependencies", "modpacks"),
        ]
        for text, key in guides:
            ttk.Button(buttons, text=text, command=lambda key=key: self.start_visual_guide(key)).pack(fill="x", pady=(0, 6))

        ttk.Label(
            shell,
            text="Tip: press Escape to close a guide, or use Left and Right arrow keys to move between steps.",
            wraplength=720
        ).pack(anchor="w", pady=(14, 0))

    def start_visual_guide(self, key):
        steps = self.visual_guide_steps().get(key, [])
        VisualGuide(self, "Simdex Guide", steps).start()

    def tab_button(self, name):
        tab = self.tabs.tabs.get(name, {})
        return tab.get("button")

    def visual_guide_steps(self):
        return {
            "quick": [
                self.guide_step("Main", self.tab_button("Main"), "Main", "Installed projects live here. Double-click a row to open details, or right-click for actions."),
                self.guide_step("Main", self.install_button, "Install Projects", "Use Install to choose one or more .s4i files. They will be added to the install queue."),
                self.guide_step("Main", self.install_queue_button, "Install Queue", "The queue shows pending, paused, failed, and finished installs. Right-click queued items to pause or prioritize them."),
                self.guide_step("Mod Index", self.tab_button("Mod Index"), "Mod Index", "Browse approved projects from the website here. Open a project to read details, versions, dependencies, or modpack contents."),
                self.guide_step("Creator", self.tab_button("Creator"), "Creator Tools", "Creators build, package, publish, and edit project metadata from this tab."),
            ],
            "installing": [
                self.guide_step("Main", self.install_button, "Install Button", "Choose one or more .s4i files. Simdex verifies approved projects before installing them."),
                self.guide_step("Main", self.install_queue_button, "Install Queue", "Open the queue to watch progress. The item name updates after server approval and file verification."),
                self.guide_step("Main", self.mod_tree, "Installed List", "Finished installs appear here. Modpacks appear as one row; their bundled mods are shown inside the modpack detail page."),
                self.guide_step("Main", self.refresh_button, "Refresh", "Refresh checks installed files and remote project status."),
            ],
            "installed": [
                self.guide_step("Main", self.mod_tree, "Installed Projects", "The State column shows whether an install is enabled, missing, broken, disabled, or obsolete."),
                self.guide_step("Main", self.select_all_check, "Select Multiple", "Use the checkbox column or Select All to work with multiple installed projects."),
                self.guide_step("Main", self.disable_selected_button, "Disable", "Disable moves selected files out of the Sims 4 folders while keeping them managed by Simdex."),
                self.guide_step("Main", self.enable_selected_button, "Enable", "Enable moves disabled files back into the Sims 4 folders."),
                self.guide_step("Main", self.mod_tree, "Context Menu", "Right-click an installed project to enable, disable, or uninstall it."),
            ],
            "index": [
                self.guide_step("Mod Index", self.index_tree, "Project Index", "Approved mods and modpacks from the server are listed here. Double-click or press Enter to open one."),
                self.guide_step("Mod Index", lambda: self.index_controls, "Filters", "Use search, type, obsolete, and verified filters to narrow the project list."),
                self.guide_step("Mod Index", lambda: self.index_pages_frame, "Pages", "Use page buttons here when there are more results."),
            ],
            "creator": [
                self.guide_step("Creator", lambda: self.creator_workspace, "Creator Workspace", "The left side manages files and approved projects. The right side edits metadata."),
                self.guide_step("Creator", lambda: self.project_tree, "Project Files", "Project folders contain .metadata, Icon.png, and the content folders for the project type."),
                self.guide_step("Creator", lambda: self.dependencies_box if hasattr(self, "dependencies_box") else self.info_panel, "Dependencies", "Mods can list dependencies. Selected dependencies stay at the top. Modpacks do not use dependencies."),
                self.guide_step("Creator", lambda: self.approved_tree, "Approved Projects", "Approved projects can be packaged, edited, marked obsolete, or deleted from this list."),
            ],
            "modpacks": [
                self.guide_step("Creator", lambda: self.project_type_label if hasattr(self, "project_type_label") else self.info_panel, "Detected Type", "Project type is detected from the folder layout. Modpacks use Mods with .s4i files and no Tray folder."),
                self.guide_step("Creator", lambda: self.project_tree, "Modpack Files", "For modpacks, import .s4i files into the Mods folder. Those files become the modpack's installed mod list."),
                self.guide_step("Mod Index", self.index_tree, "Modpack Pages", "Open a modpack from the index to see its Mods panel before the Versions panel."),
                self.guide_step("Main", self.mod_tree, "Installed Modpacks", "A modpack installs as one main row. Open it to view or manage the mods it installed."),
            ],
        }

    def guide_step(self, panel, widget, title, text):
        return {
            "panel": panel,
            "widget": widget,
            "title": title,
            "text": text
        }
