from .common import *


class CreatorUiMixin:
    def build_creator_panel(self):
        creator = ttk.PanedWindow(self.creator_panel, orient="horizontal")
        creator.pack(fill="both", expand=True)
        self.creator_workspace = creator

        explorer = ttk.Frame(creator, padding=(0, 0, 8, 0))
        info = ttk.Frame(creator, padding=(8, 0, 0, 0))
        creator.add(explorer, weight=1)
        creator.add(info, weight=3)
        self.info_panel = info

        button_bar = ttk.Frame(explorer)
        button_bar.pack(fill="x", pady=(0, 8))
        self.creator_account_label = ttk.Label(button_bar)
        self.creator_account_label.pack(anchor="w", pady=(0, 8))
        self.update_creator_account_label()
        verify_row = ttk.Frame(button_bar)
        verify_row.pack(fill="x", pady=(0, 8))
        self.verify_button = ttk.Button(verify_row, text="Verify", command=self.verify_creator_account)
        self.verify_button.pack(anchor="center")
        self.verify_button.bind("<Enter>", lambda event: self.show_tooltip(event.x_root + 12, event.y_root + 12, VERIFY_IGNORE_MESSAGE))
        self.verify_button.bind("<Leave>", self.hide_tooltip)
        buttons = [
            ("New Project", self.new_project),
            ("Load Project", self.load_project),
            ("Save Project", self.save_project),
            ("Publish Project", self.publish_project),
            ("Import File", self.import_file),
            ("New File", self.new_file),
        ]
        for text, command in buttons:
            button = ttk.Button(button_bar, text=text, command=command)
            button.pack(fill="x", pady=(0, 4))
            self.creator_buttons[text] = button
        self.edit_button = ttk.Button(button_bar, text="Edit File", command=self.edit_or_save_file)
        self.edit_button.pack(fill="x")
        self.creator_buttons["Edit File"] = self.edit_button

        tree_frame = ttk.Frame(explorer)
        tree_frame.pack(fill="both", expand=True)
        self.project_tree = ttk.Treeview(tree_frame, show="tree")
        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.project_tree.yview)
        self.project_tree.configure(yscrollcommand=tree_scroll.set)
        self.project_tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")
        self.project_tree.bind("<ButtonPress-1>", self.on_project_tree_press)
        self.project_tree.bind("<ButtonRelease-1>", self.on_project_tree_release)

        approved_box = ttk.LabelFrame(explorer, text="Approved Projects", padding=6)
        approved_box.pack(fill="both", expand=False, pady=(8, 0))
        self.approved_tree = ttk.Treeview(approved_box, columns=("name", "author", "version", "status", "id"), show="headings", height=6, selectmode="browse")
        self.approved_tree.heading("name", text="Name")
        self.approved_tree.heading("author", text="Author")
        self.approved_tree.heading("version", text="Version")
        self.approved_tree.heading("status", text="Status")
        self.approved_tree.heading("id", text="ID")
        self.approved_tree.column("name", width=130)
        self.approved_tree.column("author", width=90)
        self.approved_tree.column("version", width=65)
        self.approved_tree.column("status", width=70)
        self.approved_tree.column("id", width=90)
        self.approved_tree.pack(fill="both", expand=True)
        self.approved_tree.tag_configure("obsolete", foreground="#b00020")
        ttk.Button(approved_box, text="Refresh Approved", command=self.refresh_approved_projects).pack(fill="x", pady=(6, 0))
        self.approved_menu = tk.Menu(self, tearoff=0)
        self.approved_menu.add_command(label="Package", command=self.package_selected_approved_project)
        self.approved_menu.add_command(label="Edit Metadata", command=self.edit_selected_approved_metadata)
        self.approved_menu.add_command(label="Mark as Obsolete", command=self.mark_selected_project_obsolete)
        self.approved_menu.add_command(label="Delete Project", command=self.delete_selected_approved_project)
        self.approved_context_id = None
        self.approved_tree.bind("<Button-3>", self.on_approved_right_click)
        self.approved_tree.bind("<Motion>", lambda event: self.on_author_badge_hover(event, self.approved_tree, self.approved_projects, "#2", self.approved_row_id))
        self.approved_tree.bind("<Leave>", self.hide_tooltip)

        self.build_info_form()
        self.refresh_approved_projects()
        self.build_creator_gate()
        self.update_creator_gate()

    def show_creator_auth_panel(self, mode):
        self.set_metadata_edit_mode(False)
        for child in self.info_panel.winfo_children():
            child.destroy()
        ttk.Label(self.info_panel, text=f"Creator {mode}", font=("Segoe UI", 16, "bold")).pack(anchor="w", pady=(0, 12))
        email_var = tk.StringVar(value=self.creator_account.get("email", ""))
        username_var = tk.StringVar(value=self.creator_username())
        password_var = tk.StringVar()
        ttk.Label(self.info_panel, text="Email").pack(anchor="w")
        ttk.Entry(self.info_panel, textvariable=email_var).pack(fill="x", pady=(0, 8))
        if mode.lower() == "signup":
            ttk.Label(self.info_panel, text="Username").pack(anchor="w")
            ttk.Entry(self.info_panel, textvariable=username_var).pack(fill="x", pady=(0, 8))
        ttk.Label(self.info_panel, text="Password").pack(anchor="w")
        ttk.Entry(self.info_panel, textvariable=password_var, show="*").pack(fill="x", pady=(0, 12))
        ttk.Label(
            self.info_panel,
            text="Creator accounts are required for creating, publishing, and managing projects.",
            wraplength=560
        ).pack(anchor="w", pady=(0, 12))
        ttk.Button(
            self.info_panel,
            text=mode,
            command=lambda: self.submit_creator_auth(mode.lower(), email_var.get(), password_var.get(), username_var.get())
        ).pack(anchor="w")
        self.show_creator_gate(auth_open=True)

    def build_creator_gate(self):
        self.creator_gate = ttk.Frame(self.creator_panel, padding=24)
        card = ttk.Frame(self.creator_gate, padding=24)
        card.place(relx=0.5, rely=0.5, anchor="center")
        ttk.Label(card, text="Creator Account Required", font=("Segoe UI", 16, "bold")).pack(pady=(0, 12))
        row = ttk.Frame(card)
        row.pack()
        ttk.Button(row, text="Login", command=lambda: self.show_creator_auth_panel("Login")).pack(side="left", padx=(0, 8))
        ttk.Button(row, text="Signup", command=lambda: self.show_creator_auth_panel("Signup")).pack(side="left")

    def show_creator_gate(self, auth_open=False):
        if not hasattr(self, "creator_gate"):
            return
        if self.has_creator_account():
            self.creator_gate.place_forget()
            return
        if auth_open:
            self.creator_gate.place_forget()
            return
        self.creator_gate.place(x=0, y=0, relwidth=1, relheight=1)
        self.creator_gate.lift()

    def update_creator_gate(self):
        if hasattr(self, "author_entry"):
            self.info_vars.setdefault("author", tk.StringVar()).set(self.creator_username())
        if self.has_creator_account():
            if not self.editing_approved_project:
                for button in self.creator_buttons.values():
                    button.configure(state="normal")
                if hasattr(self, "verify_button"):
                    self.verify_button.configure(state="disabled" if self.creator_account.get("verified") else "normal")
            if hasattr(self, "creator_gate"):
                self.creator_gate.place_forget()
            self.refresh_approved_projects()
        else:
            for button in self.creator_buttons.values():
                button.configure(state="disabled")
            if hasattr(self, "verify_button"):
                self.verify_button.configure(state="disabled")
            self.show_creator_gate()

    def restore_creator_form(self):
        self.build_info_form()
        if self.current_project and (self.current_project / ".metadata").exists():
            try:
                self.load_metadata_into_form(read_json(self.current_project / ".metadata"))
            except (OSError, json.JSONDecodeError):
                pass

    def submit_creator_auth(self, mode, email, password, username=""):
        endpoint = "/api/creator/signup" if mode == "signup" else "/api/creator/login"

        def auth():
            payload = {"email": email, "password": password}
            if mode == "signup":
                payload["username"] = username
            response = api_json(endpoint, method="POST", payload=payload)
            account = response.get("account", {})
            account["token"] = response.get("token", "")
            return account

        def done(account):
            self.save_creator_account(account)
            self.migrate_root_projects()
            self.restore_creator_form()
            self.refresh_approved_projects()
            if mode == "signup" and not account.get("verified"):
                messagebox.showinfo("Creator Account", VERIFY_IGNORE_MESSAGE)
            else:
                messagebox.showinfo("Creator Account", "Signed in.")

        self.run_background_task("Creator Account", auth, done)

    def verify_creator_account(self):
        if not self.require_creator_account():
            return
        code = simpledialog.askstring("Verify Account", "Verification code:")
        if not code:
            return

        def verify():
            response = api_json(
                "/api/creator/verify",
                method="POST",
                payload={"code": code},
                token=self.creator_token()
            )
            account = response.get("account", {})
            account["token"] = self.creator_token()
            return account

        def verified(account):
            self.save_creator_account(account)
            self.refresh_index_projects()
            messagebox.showinfo("Verify Account", "Account verified.")

        self.run_background_task("Verify Account", verify, verified)
