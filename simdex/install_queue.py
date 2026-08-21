from .common import *


class InstallQueueMixin:
    def install_s4i(self):
        paths = filedialog.askopenfilenames(title="Install .s4i", filetypes=[("Simdex install files", "*.s4i")])
        if not paths:
            return
        for path in paths:
            path = Path(path)
            job_id = f"install-{int(time.time() * 1000)}-{len(self.install_jobs)}"
            self.install_jobs.append({
                "id": job_id,
                "path": str(path),
                "name": path.name,
                "status": "Queued",
                "progress": 0
            })
        self.show_install_queue()
        self.render_install_queue()
        self.after(50, self.process_install_queue)

    def show_install_queue(self):
        if self.install_queue_window and self.install_queue_window.winfo_exists():
            self.install_queue_window.lift()
            return
        window = tk.Toplevel(self)
        window.title("Install Queue")
        window.geometry("520x300")
        self.install_queue_window = window
        self.install_queue_tree = ttk.Treeview(window, columns=("name", "status"), show="headings", selectmode="browse")
        self.install_queue_tree.heading("name", text="File")
        self.install_queue_tree.heading("status", text="Status")
        self.install_queue_tree.column("name", width=330)
        self.install_queue_tree.column("status", width=150)
        self.install_queue_tree.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        self.install_queue_tree.bind("<Button-3>", self.on_install_queue_right_click)
        self.install_progress = ttk.Progressbar(window, maximum=100, variable=tk.DoubleVar(value=0))
        self.install_progress.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Label(window, textvariable=self.install_status_var).pack(anchor="w", padx=8, pady=(0, 8))
        self.install_queue_menu = tk.Menu(window, tearoff=0)
        self.install_queue_menu.add_command(label="Pause", command=self.pause_install_job)
        self.install_queue_menu.add_command(label="Prioritize", command=self.prioritize_install_job)
        self.install_queue_context_id = None
        self.render_install_queue()

    def render_install_queue(self):
        if not self.install_queue_tree or not self.install_queue_tree.winfo_exists():
            return
        self.install_queue_tree.delete(*self.install_queue_tree.get_children())
        for job in self.install_jobs:
            self.install_queue_tree.insert("", "end", iid=job["id"], values=(job["name"], job["status"]))

    def on_install_queue_right_click(self, event):
        item_id = self.install_queue_tree.identify_row(event.y)
        if not item_id:
            return
        self.install_queue_context_id = item_id
        job = next((item for item in self.install_jobs if item["id"] == item_id), None)
        if job and job["id"] in self.paused_install_ids:
            self.install_queue_menu.entryconfigure(0, label="Resume")
        else:
            self.install_queue_menu.entryconfigure(0, label="Pause")
        self.install_queue_menu.tk_popup(event.x_root, event.y_root)

    def pause_install_job(self):
        job_id = self.install_queue_context_id
        if not job_id:
            return
        if job_id in self.paused_install_ids:
            self.paused_install_ids.remove(job_id)
        else:
            self.paused_install_ids.add(job_id)
        for job in self.install_jobs:
            if job["id"] == job_id and job["status"] in {"Queued", "Paused"}:
                job["status"] = "Queued" if job_id not in self.paused_install_ids else "Paused"
        self.render_install_queue()
        self.after(50, self.process_install_queue)

    def prioritize_install_job(self):
        if self.install_queue_context_id:
            self.prioritized_install_id = self.install_queue_context_id
            self.paused_install_ids.discard(self.install_queue_context_id)
            self.after(50, self.process_install_queue)

    def process_install_queue(self):
        if self.install_worker_running:
            return
        job = self.next_install_job()
        if not job:
            return
        self.install_worker_running = True
        self.active_install_id = job["id"]
        job["status"] = "Installing"
        self.install_status_var.set(f"Installing {job['name']}")
        if self.install_progress:
            self.install_progress.configure(mode="indeterminate")
            self.install_progress.start(12)
        self.render_install_queue()
        self.update_idletasks()
        try:
            mod = self.extract_and_install(Path(job["path"]), install_job=job)
        except (BadZipFile, OSError, ValueError, json.JSONDecodeError) as error:
            job["status"] = f"Failed: {error}"
            messagebox.showerror("Install failed", str(error))
            mod = None
        finally:
            if self.install_progress:
                self.install_progress.stop()
                self.install_progress.configure(mode="determinate")
                self.install_progress["value"] = 100
            self.install_worker_running = False
            self.active_install_id = None
        if mod is None:
            if not job["status"].startswith("Failed"):
                job["status"] = "Skipped"
        else:
            self.installed_mods.append(mod)
            job["status"] = "Done"
        self.save_installed_mods()
        self.refresh_mod_list()
        self.refresh_index_list()
        self.render_install_queue()
        if self.prioritized_install_id == job["id"]:
            self.prioritized_install_id = None
        self.install_status_var.set("Install queue finished." if not self.next_install_job() else "")
        self.after(50, self.process_install_queue)

    def next_install_job(self):
        if self.prioritized_install_id:
            job = next((item for item in self.install_jobs if item["id"] == self.prioritized_install_id and item["status"] in {"Queued", "Paused"}), None)
            if job:
                return job
        return next((item for item in self.install_jobs if item["status"] == "Queued" and item["id"] not in self.paused_install_ids), None)

    def update_install_job_name(self, install_job, project, s4i_path):
        if install_job and project.get("name"):
            install_job["name"] = f"{project['name']} ({s4i_path.name})"
            self.render_install_queue()
