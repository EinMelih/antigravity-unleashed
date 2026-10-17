"""Always-on-top self-healing progress window (separate process, survives app restarts)."""

from __future__ import annotations

import os
import sys
import time
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))
import selfheal  # noqa: E402

BG = "#0f1115"
CARD = "#171a21"
FG = "#f4f4f5"
MUTED = "#9aa0aa"
BLUE = "#3b82f6"
GREEN = "#22c55e"
RED = "#ef4444"
AMBER = "#f59e0b"
POLL_MS = 500
AUTOCLOSE_SECONDS = 25

ICONS = {"pending": "○", "running": "●", "done": "✓", "failed": "✕"}


def _enable_dpi_awareness() -> None:
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


class ProgressWindow:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Anti-Gravity Selbstheilung")
        self.root.configure(bg=BG)
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        width, height = 520, 650
        x = self.root.winfo_screenwidth() - width - 32
        y = 48
        self.root.geometry(f"{width}x{height}+{x}+{y}")

        style = ttk.Style(self.root)
        style.theme_use("clam")
        self.set_bar_color(BLUE)

        self.title_var = tk.StringVar(value="Anti-Gravity wird repariert …")
        self.sub_var = tk.StringVar(value="")
        self.percent_var = tk.StringVar(value="0 %")
        self.message_var = tk.StringVar(value="")

        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=22, pady=(20, 6))
        tk.Label(header, textvariable=self.title_var, bg=BG, fg=FG, font=("Segoe UI Semibold", 14), anchor="w", wraplength=476, justify="left").pack(fill="x")
        tk.Label(header, textvariable=self.sub_var, bg=BG, fg=MUTED, font=("Segoe UI", 9), anchor="w").pack(fill="x", pady=(2, 0))

        bar_row = tk.Frame(self.root, bg=BG)
        bar_row.pack(fill="x", padx=22, pady=(10, 4))
        self.bar = ttk.Progressbar(bar_row, style="AG.Horizontal.TProgressbar", orient="horizontal", mode="determinate", maximum=100)
        self.bar.pack(side="left", fill="x", expand=True)
        tk.Label(bar_row, textvariable=self.percent_var, bg=BG, fg=FG, font=("Segoe UI Semibold", 10), width=6, anchor="e").pack(side="right", padx=(10, 0))

        card = tk.Frame(self.root, bg=CARD, highlightthickness=1, highlightbackground="#262a33")
        card.pack(fill="both", expand=True, padx=22, pady=(10, 8))
        self.step_labels: dict[str, tuple[tk.Label, tk.Label, tk.Label]] = {}
        for step_id, label, _weight in selfheal.STEPS:
            row = tk.Frame(card, bg=CARD)
            row.pack(fill="x", padx=14, pady=5)
            icon = tk.Label(row, text="○", bg=CARD, fg=MUTED, font=("Segoe UI Symbol", 11), width=2)
            icon.pack(side="left")
            text = tk.Label(row, text=label, bg=CARD, fg=MUTED, font=("Segoe UI", 10), anchor="w")
            text.pack(side="left", fill="x", expand=True)
            timing = tk.Label(row, text="", bg=CARD, fg=MUTED, font=("Segoe UI", 9))
            timing.pack(side="right")
            self.step_labels[step_id] = (icon, text, timing)

        tk.Label(self.root, textvariable=self.message_var, bg=BG, fg=MUTED, font=("Segoe UI", 9), wraplength=476, justify="left", anchor="w").pack(fill="x", padx=22, pady=(0, 6))

        self.buttons = tk.Frame(self.root, bg=BG)
        self.buttons.pack(fill="x", padx=22, pady=(0, 18))
        self.retry_btn = self.make_button("Agent erneut versuchen", BLUE, self.on_retry)
        self.close_btn = self.make_button("Schließen", "#2a2f3a", self.on_close)
        self.auto_close_at: float | None = None
        self.retrying = False

        selfheal.SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
        (selfheal.SCRATCH_DIR / "selfheal_window.pid").write_text(str(os.getpid()), encoding="utf-8")
        self.tick()

    def make_button(self, text: str, color: str, command) -> tk.Button:
        return tk.Button(
            self.buttons, text=text, command=command, bg=color, fg="#ffffff", activebackground=color,
            activeforeground="#ffffff", relief="flat", bd=0, padx=14, pady=7, font=("Segoe UI Semibold", 9), cursor="hand2",
        )

    def set_bar_color(self, color: str) -> None:
        style = ttk.Style(self.root)
        style.configure("AG.Horizontal.TProgressbar", troughcolor="#22262f", background=color, bordercolor="#22262f",
                        lightcolor=color, darkcolor=color, thickness=12)

    @staticmethod
    def fmt_duration(entry: dict) -> str:
        started = entry.get("started_at")
        if not started:
            return ""
        finished = entry.get("finished_at") or time.time()
        seconds = max(0, int(finished - started))
        return f"{seconds // 60}:{seconds % 60:02d}" if seconds >= 60 else f"{seconds} s"

    def render_buttons(self, failed: bool, finished_ok: bool) -> None:
        for button in (self.retry_btn, self.close_btn):
            button.pack_forget()
        if failed:
            self.retry_btn.pack(side="left")
            self.close_btn.pack(side="right")
        elif finished_ok:
            self.close_btn.configure(text="Fertig")
            self.close_btn.pack(side="right")
        else:
            self.close_btn.configure(text="Ausblenden")
            self.close_btn.pack(side="right")

    def tick(self) -> None:
        state = selfheal.read_state()
        if not state:
            self.title_var.set("Keine aktive Selbstheilung")
            self.sub_var.set("Dieses Fenster schließt sich gleich.")
            self.auto_close_at = self.auto_close_at or time.time() + 5
        else:
            result = state.get("result", "running")
            percent = int(state.get("percent", 0))
            self.bar["value"] = percent
            self.percent_var.set(f"{percent} %")
            if state.get("from_version") and state.get("to_version"):
                subtitle = f"Version {state['from_version']} → {state['to_version']}"
            else:
                subtitle = "Injector wird neu installiert"
            self.sub_var.set(
                subtitle
                + (f"  ·  Versuch {state['attempt']}" if state.get("attempt", 1) > 1 else "")
            )
            self.message_var.set(state.get("message", ""))
            for step_id, (icon, text, timing) in self.step_labels.items():
                entry = state.get("steps", {}).get(step_id, {})
                status = entry.get("status", "pending")
                color = {"pending": MUTED, "running": BLUE, "done": GREEN, "failed": RED}[status]
                icon.configure(text=ICONS[status], fg=color)
                text.configure(fg=FG if status in ("running", "done", "failed") else MUTED)
                timing.configure(text=self.fmt_duration(entry) if status != "pending" else "")
            if result == "success":
                self.title_var.set("Anti-Gravity ist repariert und verifiziert")
                self.set_bar_color(GREEN)
                self.render_buttons(False, True)
                self.auto_close_at = self.auto_close_at or time.time() + AUTOCLOSE_SECONDS
            elif result == "failed":
                self.title_var.set("Selbstheilung fehlgeschlagen")
                self.set_bar_color(RED)
                self.render_buttons(True, False)
                self.auto_close_at = None
            else:
                self.title_var.set("Anti-Gravity wird repariert …")
                self.set_bar_color(BLUE)
                self.render_buttons(False, False)
                self.auto_close_at = None
        if self.auto_close_at and time.time() >= self.auto_close_at:
            self.on_close()
            return
        self.root.after(POLL_MS, self.tick)

    def on_retry(self) -> None:
        if self.retrying:
            return
        self.retrying = True
        self.retry_btn.configure(state="disabled", text="Wird gesendet …")
        threading.Thread(target=self._retry_worker, daemon=True).start()

    def _retry_worker(self) -> None:
        try:
            old = selfheal.read_state()
            attempt = int(old.get("attempt", 1)) + 1
            from_version = old.get("from_version", "")
            to_version = old.get("to_version", "")
            selfheal.begin(from_version, to_version, attempt=attempt)
            for finding in old.get("findings", []):
                selfheal.add_finding(finding)
            import notification_popup

            user_data_dir = Path(os.environ.get("APPDATA", "")) / "Antigravity"
            prompt = selfheal.build_repair_prompt(to_version, from_version or "unbekannt", attempt)
            if not notification_popup.dispatch_prompt_to_antigravity(prompt, user_data_dir):
                selfheal.set_step("analysis", "failed", "Auftrag konnte nicht an Anti-Gravity gesendet werden. Bitte die App öffnen und erneut versuchen.")
        except Exception as error:
            selfheal.set_step("analysis", "failed", f"Erneuter Versuch fehlgeschlagen: {error}")
        finally:
            self.retrying = False
            self.root.after(0, lambda: self.retry_btn.configure(state="normal", text="Agent erneut versuchen"))

    def on_close(self) -> None:
        try:
            (selfheal.SCRATCH_DIR / "selfheal_window.pid").unlink(missing_ok=True)
        except OSError:
            pass
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    if os.name != "nt":
        return 1
    _enable_dpi_awareness()
    ProgressWindow().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
