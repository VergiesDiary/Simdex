from .common import *


class CreatorAccountMixin:
    def load_creator_account(self):
        try:
            data = read_json(CREATOR_ACCOUNT_FILE)
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def save_creator_account(self, account):
        self.creator_account = account
        write_json(CREATOR_ACCOUNT_FILE, account)
        if hasattr(self, "creator_account_label"):
            self.update_creator_account_label()
        self.update_creator_gate()

    def clear_creator_account(self, message=""):
        self.creator_account = {}
        try:
            CREATOR_ACCOUNT_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        self.editing_approved_project = None
        self.approved_projects = []
        self.approved_project_paths = {}
        if hasattr(self, "approved_tree"):
            self.approved_tree.delete(*self.approved_tree.get_children())
        if hasattr(self, "creator_account_label"):
            self.update_creator_account_label()
        self.update_creator_gate()
        if message:
            messagebox.showerror("Creator Account", message)

    def check_creator_account_status(self):
        if self.creator_status_running:
            self.after(self.creator_status_interval_ms, self.check_creator_account_status)
            return
        if not self.has_creator_account():
            self.after(self.creator_status_interval_ms, self.check_creator_account_status)
            return

        token = self.creator_token()
        self.creator_status_running = True

        def check():
            try:
                response = api_json("/api/creator/me", token=token)
            except ValueError as error:
                message = str(error)
                if "API request failed (401)" in message or "API request failed (403)" in message:
                    return {"error": message}
                return {}
            except (OSError, json.JSONDecodeError):
                return {}
            account = response.get("account", {})
            account["token"] = token
            return {"account": account}

        def checked(result):
            self.creator_status_running = False
            if result.get("account"):
                if self.creator_token() == token:
                    self.creator_account = result["account"]
                    write_json(CREATOR_ACCOUNT_FILE, self.creator_account)
                    if hasattr(self, "creator_account_label"):
                        self.update_creator_account_label()
                    if hasattr(self, "verify_button"):
                        self.verify_button.configure(state="disabled" if self.creator_account.get("verified") else "normal")
            elif result.get("error") and self.creator_token() == token:
                self.clear_creator_account("Your creator account is no longer available. You have been logged out.")
            self.after(self.creator_status_interval_ms, self.check_creator_account_status)

        self.run_background_task("Creator Account", check, checked)

    def creator_token(self):
        return self.creator_account.get("token", "")

    def creator_username(self):
        username = self.creator_account.get("username")
        if username:
            return username
        email = self.creator_account.get("email", "")
        return email.split("@", 1)[0] if email else ""

    def has_creator_account(self):
        return bool(self.creator_token() and self.creator_username())

    def require_creator_account(self):
        if self.has_creator_account():
            return True
        messagebox.showerror("Creator Account", "Sign in to a creator account first.")
        self.show_creator_gate()
        return False

    def update_creator_account_label(self):
        if not hasattr(self, "creator_account_label"):
            return
        username = self.creator_username()
        suffix = VERIFIED_BADGE if self.creator_account.get("verified") else ""
        self.creator_account_label.configure(text=f"Logged in: {username}{suffix}" if username else "Creator account: not logged in")
        self.creator_account_label.unbind("<Enter>")
        self.creator_account_label.unbind("<Leave>")
        if self.creator_account.get("verified"):
            self.creator_account_label.bind("<Enter>", lambda event: self.show_tooltip(event.x_root + 12, event.y_root + 12, VERIFIED_CREATOR_TOOLTIP))
            self.creator_account_label.bind("<Leave>", self.hide_tooltip)

    def migrate_root_projects(self):
        PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)
        for item in APP_ROOT.iterdir():
            if not item.is_dir() or item.name in APP_MANAGED_FOLDERS:
                continue
            if not (item / ".metadata").exists():
                continue
            target = PROJECTS_ROOT / item.name
            if target.exists():
                hide_metadata_file(item)
                continue
            shutil.move(str(item), str(target))
            hide_metadata_file(target)
            if self.current_project == item:
                self.current_project = target
