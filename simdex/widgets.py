import tkinter as tk
from tkinter import ttk


class ScrollableTabs(ttk.Frame):
    def __init__(self, parent, on_select):
        super().__init__(parent)
        self.on_select = on_select
        self.tabs = {}
        self.active_name = None

        self.canvas = tk.Canvas(self, height=34, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.inner = ttk.Frame(self.canvas)
        self.window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(xscrollcommand=self.scrollbar.set)
        self.canvas.pack(fill="x", expand=True)
        self.scrollbar.pack(fill="x")
        self.inner.bind("<Configure>", self._sync)
        self.canvas.bind("<Configure>", self._resize)

    def _sync(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _resize(self, event):
        self.canvas.itemconfigure(self.window, height=event.height)

    def add_tab(self, name, closable=False, close_command=None):
        if name in self.tabs:
            self.select(name)
            return

        frame = ttk.Frame(self.inner)
        button = ttk.Button(frame, text=name, command=lambda: self.select(name))
        button.pack(side="left")
        close = None
        if closable:
            close = ttk.Button(frame, text="x", width=3, command=close_command)
            close.pack(side="left")
        frame.pack(side="left", padx=(0, 2), pady=2)
        self.tabs[name] = {"frame": frame, "button": button, "close": close}
        self.select(name)

    def remove_tab(self, name):
        tab = self.tabs.pop(name, None)
        if not tab:
            return
        tab["frame"].destroy()
        if self.active_name == name:
            next_name = "Main" if "Main" in self.tabs else next(iter(self.tabs), None)
            if next_name:
                self.select(next_name)

    def select(self, name):
        if name not in self.tabs:
            return
        self.active_name = name
        for tab_name, tab in self.tabs.items():
            state = "disabled" if tab_name == name else "normal"
            tab["button"].configure(state=state)
        self.on_select(name)


class VisualGuide:
    def __init__(self, app, title, steps):
        self.app = app
        self.title = title
        self.steps = steps
        self.index = 0
        self.window = None
        self.canvas = None
        self.controls = None
        self.bindings = []
        self.app_bindings = []
        self.transparent_color = "#010203"

    def start(self):
        if not self.steps:
            return
        if self.app.active_visual_guide:
            self.app.active_visual_guide.close()
        self.app.active_visual_guide = self
        self.window = tk.Toplevel(self.app)
        self.window.title(self.title)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.transient(self.app)
        try:
            self.window.attributes("-transparentcolor", self.transparent_color)
        except tk.TclError:
            pass
        self.bind("<Escape>", lambda _event: self.close())
        self.bind("<Right>", lambda _event: self.next_step())
        self.bind("<Left>", lambda _event: self.previous_step())
        self.bind("<space>", lambda _event: self.next_step())
        self.window.bind("<FocusOut>", lambda _event: self.window.after(100, self.hide_if_app_inactive))
        self.bind_app("<FocusIn>", lambda _event: self.restore())
        self.bind_app("<Configure>", lambda _event: self.redraw())
        self.show_step()

    def bind(self, sequence, command):
        self.bindings.append((sequence, self.window.bind_all(sequence, command, add=True)))

    def bind_app(self, sequence, command):
        self.app_bindings.append((sequence, self.app.bind(sequence, command, add=True)))

    def close(self):
        for sequence, binding in self.bindings:
            if self.window:
                self.window.unbind_all(sequence)
        self.bindings = []
        for sequence, binding in self.app_bindings:
            self.app.unbind(sequence, binding)
        self.app_bindings = []
        if self.controls and self.controls.winfo_exists():
            self.controls.destroy()
        if self.window and self.window.winfo_exists():
            self.window.destroy()
        if self.app.active_visual_guide is self:
            self.app.active_visual_guide = None

    def hide_if_app_inactive(self):
        if not self.window or not self.window.winfo_exists():
            return
        focused = self.app.focus_displayof()
        if focused is None:
            self.window.withdraw()

    def restore(self):
        if not self.window or not self.window.winfo_exists():
            return
        self.position_window()
        self.window.deiconify()
        self.window.update_idletasks()
        self.window.lift(self.app)

    def redraw(self):
        if self.window and self.window.winfo_exists() and self.window.state() != "withdrawn":
            self.show_step()

    def previous_step(self):
        if self.index > 0:
            self.index -= 1
            self.show_step()

    def next_step(self):
        if self.index >= len(self.steps) - 1:
            self.close()
            return
        self.index += 1
        self.show_step()

    def show_step(self):
        step = self.steps[self.index]
        panel = step.get("panel")
        if panel:
            self.app.tabs.select(panel)
            self.app.update_idletasks()
        self.app.update_idletasks()
        if self.canvas and self.canvas.winfo_exists():
            self.canvas.destroy()
        if self.controls and self.controls.winfo_exists():
            self.controls.destroy()
        width, height = self.position_window()
        self.canvas = tk.Canvas(self.window, width=width, height=height, highlightthickness=0, bg=self.transparent_color)
        self.canvas.pack(fill="both", expand=True)
        self.window.deiconify()
        self.window.update_idletasks()
        self.canvas.configure(width=width, height=height)
        self.draw_step(step)
        self.window.lift()
        self.window.focus_force()

    def position_window(self):
        self.app.update_idletasks()
        width = max(self.app.winfo_width(), 600)
        height = max(self.app.winfo_height(), 400)
        self.window.geometry(f"{width}x{height}+{self.app.winfo_rootx()}+{self.app.winfo_rooty()}")
        return width, height

    def step_widget(self, step):
        widget = step.get("widget")
        if callable(widget):
            widget = widget()
        if widget and widget.winfo_exists():
            return widget
        return None

    def widget_box(self, widget):
        root_x = self.app.winfo_rootx()
        root_y = self.app.winfo_rooty()
        x = widget.winfo_rootx() - root_x
        y = widget.winfo_rooty() - root_y
        return x, y, x + widget.winfo_width(), y + widget.winfo_height()

    def draw_step(self, step):
        width = self.canvas.winfo_width() or self.app.winfo_width()
        height = self.canvas.winfo_height() or self.app.winfo_height()
        widget = self.step_widget(step)
        target_x = width // 2
        target_y = height // 2
        if widget:
            x1, y1, x2, y2 = self.widget_box(widget)
            pad = 8
            self.canvas.create_rectangle(x1 - pad, y1 - pad, x2 + pad, y2 + pad, outline="#ffcc00", width=5, fill=self.transparent_color)
            target_x = (x1 + x2) // 2
            target_y = (y1 + y2) // 2

        card_width = min(460, width - 40)
        card_height = 190
        card_x = 24 if target_x > width // 2 else max(24, width - card_width - 24)
        card_y = 24 if target_y > height // 2 else max(24, height - card_height - 24)
        self.canvas.create_rectangle(card_x, card_y, card_x + card_width, card_y + card_height, fill="#fff1a8", outline="#1f1f1f", width=2)
        self.canvas.create_text(card_x + 16, card_y + 16, anchor="nw", text=step.get("title", self.title), fill="#111111", font=("Segoe UI", 14, "bold"), width=card_width - 32)
        self.canvas.create_text(card_x + 16, card_y + 52, anchor="nw", text=step.get("text", ""), fill="#111111", font=("Segoe UI", 10), width=card_width - 32)
        if self.index == 0:
            self.canvas.create_text(
                card_x + 16,
                card_y + card_height - 58,
                anchor="w",
                text="Tip: Next, Right arrow, or Space continues. Left arrow goes back. Escape closes.",
                fill="#3a3100",
                font=("Segoe UI", 9),
                width=card_width - 32
            )

        start_x = card_x + card_width // 2
        start_y = card_y + card_height // 2
        self.canvas.create_line(start_x, start_y, target_x, target_y, fill="#ffcc00", width=6, arrow="last", arrowshape=(18, 22, 8))

        self.controls = ttk.Frame(self.window)
        ttk.Button(self.controls, text="Back", command=self.previous_step, state="normal" if self.index else "disabled").pack(side="left", padx=(0, 6))
        ttk.Button(self.controls, text="Next" if self.index < len(self.steps) - 1 else "Done", command=self.next_step).pack(side="left", padx=(0, 6))
        ttk.Button(self.controls, text="Close", command=self.close).pack(side="left")
        self.canvas.create_window(card_x + card_width - 16, card_y + card_height - 16, anchor="se", window=self.controls)
        self.canvas.create_text(card_x + 16, card_y + card_height - 30, anchor="w", text=f"{self.index + 1} of {len(self.steps)}", fill="#111111", font=("Segoe UI", 9))
