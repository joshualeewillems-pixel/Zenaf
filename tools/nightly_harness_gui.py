#!/usr/bin/env python3
"""
Simple desktop UI for the nightly self-exercise harness (stdlib only: tkinter).

Run from repo root:
  python tools/nightly_harness_gui.py

Or double-click: tools/NightlyHarness.bat (Windows)
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNNER = REPO_ROOT / "tools" / "run_nightly_self_exercise.py"
LOG_ROOT = REPO_ROOT / "logs" / "nightly_self_exercise"
LAST_POINTER = LOG_ROOT / "last_completed_run.txt"


def _open_path(path: Path) -> None:
    path = path.resolve()
    if not path.exists():
        return
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


def _latest_report_dir() -> Path | None:
    if LAST_POINTER.is_file():
        try:
            p = Path(LAST_POINTER.read_text(encoding="utf-8").strip())
            if p.is_dir() and (p / "NIGHTLY_REPORT.md").is_file():
                return p
        except OSError:
            pass
    if not LOG_ROOT.is_dir():
        return None
    dirs = [d for d in LOG_ROOT.iterdir() if d.is_dir() and (d / "NIGHTLY_REPORT.md").is_file()]
    if not dirs:
        return None
    return max(dirs, key=lambda d: d.stat().st_mtime)


def main() -> None:
    import tkinter as tk
    from tkinter import ttk, scrolledtext, messagebox

    root = tk.Tk()
    root.title("Zenaf — Nightly harness")
    root.minsize(520, 420)
    root.geometry("720x560")

    proc_holder: list[subprocess.Popen[str] | None] = [None]
    line_queue: queue.Queue[str | None] = queue.Queue()

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill=tk.BOTH, expand=True)

    ttk.Label(
        frm,
        text="Pick a profile and hit Run. API should be up (default http://127.0.0.1:8010). "
        "Set ZENAF_NIGHTLY_EMAIL / ZENAF_NIGHTLY_PASSWORD in your environment for full smoke.",
        wraplength=680,
    ).pack(anchor=tk.W)

    row1 = ttk.Frame(frm)
    row1.pack(fill=tk.X, pady=(8, 4))
    ttk.Label(row1, text="Profile:").pack(side=tk.LEFT)
    profile_var = tk.StringVar(value="standard")
    for p in ("quick", "standard", "full"):
        ttk.Radiobutton(row1, text=p, variable=profile_var, value=p).pack(side=tk.LEFT, padx=(8, 0))

    row2 = ttk.LabelFrame(frm, text="Skips (optional)", padding=6)
    row2.pack(fill=tk.X, pady=6)
    skip_fe = tk.BooleanVar(value=False)
    skip_pt = tk.BooleanVar(value=False)
    skip_sm = tk.BooleanVar(value=False)
    skip_adv = tk.BooleanVar(value=False)
    skip_st = tk.BooleanVar(value=False)
    skip_uf = tk.BooleanVar(value=False)
    intake_poll = tk.BooleanVar(value=False)
    for text, var in [
        ("Skip frontend build", skip_fe),
        ("Skip pytest", skip_pt),
        ("Skip API smoke", skip_sm),
        ("Skip user flows (API scripts)", skip_uf),
        ("Skip adversarial batch", skip_adv),
        ("Skip stress", skip_st),
        ("Intake poll (POST poll)", intake_poll),
    ]:
        ttk.Checkbutton(row2, text=text, variable=var).pack(anchor=tk.W)

    row3 = ttk.Frame(frm)
    row3.pack(fill=tk.X, pady=4)
    ttk.Label(row3, text="Cloud budget USD (0 = local only; sets env for this run only):").pack(side=tk.LEFT)
    budget_var = tk.StringVar(value=os.environ.get("ZENAF_NIGHTLY_CLOUD_BUDGET_USD", "0"))
    ttk.Entry(row3, textvariable=budget_var, width=8).pack(side=tk.LEFT, padx=6)
    ttk.Label(row3, text="(digits only, e.g. 0.5)", foreground="gray").pack(side=tk.LEFT, padx=4)

    out = scrolledtext.ScrolledText(frm, height=16, wrap=tk.WORD, font=("Consolas", 10))
    status = ttk.Label(frm, text="Ready.")

    def append_line(s: str) -> None:
        out.insert(tk.END, s)
        out.see(tk.END)

    def pump_queue() -> None:
        try:
            while True:
                item = line_queue.get_nowait()
                if item is None:
                    on_process_exit()
                    return
                append_line(item)
        except queue.Empty:
            pass
        root.after(80, pump_queue)

    def on_process_exit() -> None:
        p = proc_holder[0]
        proc_holder[0] = None
        run_btn.config(state=tk.NORMAL)
        stop_btn.state(["disabled"])
        if p is not None:
            code = p.poll()
            status.config(text=f"Finished (exit code {code}).")
        else:
            status.config(text="Stopped.")

    def stop_run() -> None:
        p = proc_holder[0]
        if p is None:
            return
        try:
            p.terminate()
        except OSError:
            pass
        status.config(text="Stopping...")

    def run_harness() -> None:
        if proc_holder[0] is not None:
            return
        out.delete("1.0", tk.END)
        b_raw = budget_var.get().strip()
        if b_raw:
            try:
                float(b_raw)
            except ValueError:
                messagebox.showwarning(
                    "Cloud budget",
                    "Cloud budget must be a number (e.g. 0 or 0.5).\n"
                    "Fix the field or clear it — invalid values are ignored for this run.",
                )
                b_raw = ""
        argv = [sys.executable, "-u", str(RUNNER), "--profile", profile_var.get()]
        if skip_fe.get():
            argv.append("--skip-frontend")
        if skip_pt.get():
            argv.append("--skip-pytest")
        if skip_sm.get():
            argv.append("--skip-api-smoke")
        if skip_uf.get():
            argv.append("--skip-user-flows")
        if skip_adv.get():
            argv.append("--skip-adversarial")
        if skip_st.get():
            argv.append("--skip-stress")
        if intake_poll.get():
            argv.append("--intake-poll")

        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        # Match pipe decoding below so progress lines and report dump are UTF-8 on Windows.
        env.setdefault("PYTHONUTF8", "1")
        if b_raw:
            env["ZENAF_NIGHTLY_CLOUD_BUDGET_USD"] = b_raw

        kw: dict = {
            "cwd": str(REPO_ROOT),
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "bufsize": 1,
            "env": env,
        }
        if sys.platform == "win32":
            kw["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

        try:
            proc = subprocess.Popen(argv, **kw)
        except OSError as e:
            messagebox.showerror("Run failed", str(e))
            return

        proc_holder[0] = proc
        run_btn.config(state=tk.DISABLED)
        stop_btn.state(["!disabled"])
        status.config(text="Running...")
        append_line("Starting harness (live lines use [nightly] prefix)...\n")

        def reader() -> None:
            assert proc.stdout is not None
            for line in iter(proc.stdout.readline, ""):
                line_queue.put(line)
            proc.wait()
            line_queue.put(None)

        threading.Thread(target=reader, daemon=True).start()
        pump_queue()

    def _open_report() -> None:
        d = _latest_report_dir()
        if d is None:
            messagebox.showinfo("No report yet", f"No NIGHTLY_REPORT.md found under {LOG_ROOT}")
            return
        _open_path(d / "NIGHTLY_REPORT.md")

    # Above the log so Run is always visible (expandable log used to shove controls off-screen).
    btn_row = ttk.Frame(frm)
    btn_row.pack(fill=tk.X, pady=(10, 6))
    run_btn = tk.Button(
        btn_row,
        text="Run",
        command=run_harness,
        font=("Segoe UI", 11, "bold"),
        padx=18,
        pady=8,
    )
    run_btn.pack(side=tk.LEFT)
    stop_btn = ttk.Button(btn_row, text="Stop", command=stop_run, state="disabled")
    stop_btn.pack(side=tk.LEFT, padx=(10, 0))
    ttk.Button(btn_row, text="Open logs folder", command=lambda: _open_path(LOG_ROOT)).pack(side=tk.LEFT, padx=(18, 0))
    ttk.Button(btn_row, text="Open last report", command=_open_report).pack(side=tk.LEFT, padx=(8, 0))

    out.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
    status.pack(anchor=tk.W)

    ttk.Separator(frm, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)
    ttk.Label(frm, text=f"Repo: {REPO_ROOT}", foreground="gray").pack(anchor=tk.W)

    root.mainloop()


if __name__ == "__main__":
    if not RUNNER.is_file():
        print("Expected", RUNNER, file=sys.stderr)
        sys.exit(1)
    main()
