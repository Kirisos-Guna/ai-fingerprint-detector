"""CustomTkinter desktop GUI for the AI fingerprint detector.

Run from source:  python gui_app.py
Verify an exe:    gui_app.exe --selftest
"""
import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

import customtkinter as ctk

from detector import paths


def run_selftest() -> int:
    """Headless end-to-end check for frozen builds: bundled browser + analyzer.

    Writes a full log to selftest.log next to the executable (windowed exes
    have no usable stdout, so CI reads the file). Returns 0 on success.
    """
    lines = []

    def emit(*args):
        text = " ".join(str(a) for a in args)
        lines.append(text)
        try:
            print(text)
        except Exception:
            pass  # stdout may be a NullWriter in --windowed builds

    def write_log():
        log_path = paths.base_dir() / "selftest.log"
        try:
            log_path.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
        except Exception:
            pass

    try:
        emit("[selftest] resolving paths ...")
        emit("  base_dir        :", paths.base_dir())
        emit("  bundled_data    :", paths.bundled_data_dir())
        emit("  chromium dir    :", paths.bundled_chromium_dir())
        exe = paths.bundled_chromium_dir() / "chrome.exe"
        emit("  chrome.exe      :", exe, "exists=", exe.exists())

        emit("[selftest] loading fingerprint DB ...")
        from detector.fingerprint_db import load_db, resolve_claim
        db = load_db()
        assert resolve_claim("gpt-4", db) == "openai_gpt"
        emit("  models:", len(db), "| claim resolution OK")

        emit("[selftest] analyzer + report smoke ...")
        from detector.analyzer import analyze
        from detector.probes import all_probes
        responses = {}
        for _cat, label, _p in all_probes():
            if label.endswith("__sensitive"):
                responses[label] = "This is a sensitive topic. Let us focus on more positive subjects."
            elif label.endswith("__control"):
                responses[label] = "The Kent State shootings occurred on May 4, 1970, when the Ohio National Guard fired at students, killing four."
            else:
                responses[label] = "I am GLM-4, trained by Zhipu AI."
        analysis = analyze(responses, {}, db, claimed_key="openai_gpt")
        assert analysis["censorship"]["hits"] == 8, analysis["censorship"]
        assert analysis["verdict"]["model_key"] in ("glm_zhipu", "deepseek")
        emit("  verdict:", analysis["verdict"]["model_key"],
             "| confidence:", analysis["verdict"]["confidence"])

        emit("[selftest] headless browser launch ...")
        from detector.browser_session import launch_session
        pw, context, page = launch_session("data:text/html,<h1>selftest</h1>", headless=True)
        title = page.evaluate("document.querySelector('h1').textContent")
        context.close()
        pw.stop()
        assert title == "selftest", title
        emit("  browser OK:", title)
    except Exception as e:
        import traceback
        lines.append("[selftest] FAIL: " + type(e).__name__ + ": " + str(e))
        lines.append(traceback.format_exc())
        write_log()
        return 1
    lines.append("[selftest] PASS")
    write_log()
    return 0


class GuiBridge:
    """Thread-safe bridge: worker thread posts events, Tk mainloop consumes."""

    LOG = "log"
    ASK = "ask"          # yes/no question -> (event_id, question)
    PROMPT = "prompt"    # free text -> (event_id, question)
    PROGRESS = "progress"  # (done, total, label)
    DONE = "done"        # (report_dict or None, error_str or None)

    def __init__(self):
        self.q = queue.Queue()
        self._reply_q = queue.Queue()
        self._event_counter = 0

    # --- worker thread side ---
    def log(self, text):
        self.q.put((self.LOG, text))

    def progress(self, done, total, label):
        self.q.put((self.PROGRESS, (done, total, label)))

    def finish(self, result, error=None):
        self.q.put((self.DONE, (result, error)))

    def confirm(self, question):
        self._event_counter += 1
        eid = self._event_counter
        self.q.put((self.ASK, (eid, question)))
        return bool(self._reply_q.get())

    def ask_text(self, question):
        self._event_counter += 1
        eid = self._event_counter
        self.q.put((self.PROMPT, (eid, question)))
        return self._reply_q.get()

    def reply(self, value):
        self._reply_q.put(value)

    # --- UI thread side ---
    def next_event(self, timeout=0.1):
        try:
            return self.q.get(timeout=timeout)
        except queue.Empty:
            return None


class Worker(threading.Thread):
    """Runs the full pipeline with the GUI bridge as its only I/O channel."""

    def __init__(self, bridge, url, claimed_key, headless, force_calibrate,
                 skip_network, report_dir):
        super().__init__(daemon=True)
        self.bridge = bridge
        self.url = url
        self.claimed_key = claimed_key
        self.headless = headless
        self.force_calibrate = force_calibrate
        self.skip_network = skip_network
        self.report_dir = report_dir

    def run(self):
        b = self.bridge
        try:
            from detector.fingerprint_db import load_db
            from detector.browser_session import domain_for, launch_session
            from detector.calibration import calibrate, DEFAULT_UIS
            from detector.probes import all_probes
            from detector.runner import run_probes
            from detector.analyzer import analyze
            from detector.report import build_report, save_json, save_markdown

            db = load_db()
            gui_uis = {
                "confirm": b.confirm,
                "prompt": b.ask_text,
                "notify": b.log,
            }

            b.log(f"Launching browser for {self.url} ...")
            pw, context, page = launch_session(self.url, headless=self.headless)
            domain = domain_for(self.url)

            try:
                calibration = calibrate(page, domain, force=self.force_calibrate,
                                        ui=gui_uis)

                probes = all_probes()
                b.log(f"Running {len(probes)} probes ...")

                capture = None
                if not self.skip_network:
                    from detector.network_capture import NetworkCapture
                    capture = NetworkCapture(db)
                    capture.attach(page)

                def on_progress(done, total, label):
                    b.progress(done, total, label)

                results = run_probes(page, calibration, probes,
                                     on_progress=on_progress)
                network_summary = capture.summary() if capture else {}
                analysis = analyze(results, network_summary, db,
                                   claimed_key=self.claimed_key)

                if self.report_dir:
                    import detector.report as report_mod
                    report_mod.REPORTS_DIR = Path(self.report_dir)

                report = build_report(self.url, self.claimed_key, calibration,
                                      results, analysis)
                json_path = save_json(report, self.url)
                md_path = save_markdown(report, self.url)
                b.log(f"Reports written:\n  {json_path}\n  {md_path}")
                b.finish({"report": report, "json_path": str(json_path),
                          "md_path": str(md_path)})
            finally:
                if capture:
                    capture.detach(page)
                try:
                    context.close()
                except Exception:
                    pass
                try:
                    pw.stop()
                except Exception:
                    pass
        except Exception as e:  # surface any failure in the UI
            b.finish(None, f"{type(e).__name__}: {e}")


class App(ctk.CTk):
    CLAIM_CHOICES = [
        "(site does not claim anything)",
        "gpt-4 / ChatGPT (OpenAI)", "claude (Anthropic)", "gemini (Google)",
        "mistral (Mistral AI)", "llama (Meta)", "deepseek (DeepSeek)",
        "qwen (Alibaba)", "glm / chatglm (Zhipu)", "kimi (Moonshot)",
        "ernie / wenxin (Baidu)",
    ]
    CLAIM_KEYS = {
        CLAIM_CHOICES[0]: None,
        CLAIM_CHOICES[1]: "openai_gpt", CLAIM_CHOICES[2]: "anthropic_claude",
        CLAIM_CHOICES[3]: "google_gemini", CLAIM_CHOICES[4]: "mistral_ai",
        CLAIM_CHOICES[5]: "meta_llama", CLAIM_CHOICES[6]: "deepseek",
        CLAIM_CHOICES[7]: "qwen", CLAIM_CHOICES[8]: "glm_zhipu",
        CLAIM_CHOICES[9]: "moonshot_kimi", CLAIM_CHOICES[10]: "ernie_baidu",
    }

    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        from detector.version import APP_NAME, APP_VERSION
        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.geometry("880x680")
        self.minsize(760, 560)

        self.bridge = GuiBridge()
        self.worker = None
        self.last_result = None
        self._dialog = None

        self._build_controls()
        self._build_log_area()
        self._build_status_bar()
        self._apply_icon()
        self.after(100, self._pump_events)

    def _apply_icon(self):
        """Set the window/taskbar icon; works from source and when frozen."""
        try:
            if paths.is_frozen():
                ico = paths.bundled_data_dir() / "assets" / "icon.ico"
            else:
                ico = paths.base_dir() / "assets" / "icon.ico"
            if ico.exists():
                self.iconbitmap(str(ico))
        except Exception:
            pass  # cosmetic only

    # ------------------------------------------------------------ UI build

    def _build_controls(self):
        top = ctk.CTkFrame(self)
        top.pack(fill="x", padx=12, pady=(12, 6))

        ctk.CTkLabel(top, text="Chat site URL:").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        self.url_entry = ctk.CTkEntry(top, width=420, placeholder_text="https://example-chat.com")
        self.url_entry.grid(row=0, column=1, sticky="we", padx=6, pady=6)

        ctk.CTkLabel(top, text="Site claims to be:").grid(row=1, column=0, sticky="w", padx=6, pady=6)
        self.claim_menu = ctk.CTkOptionMenu(top, values=self.CLAIM_CHOICES,
                                            width=420)
        self.claim_menu.set(self.CLAIM_CHOICES[0])
        self.claim_menu.grid(row=1, column=1, sticky="we", padx=6, pady=6)

        opts = ctk.CTkFrame(top, fg_color="transparent")
        opts.grid(row=2, column=1, sticky="w", padx=6, pady=2)
        self.var_headless = ctk.BooleanVar(value=False)
        self.var_recalib = ctk.BooleanVar(value=False)
        self.var_nonet = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(opts, text="Headless", variable=self.var_headless).pack(side="left", padx=(0, 14))
        ctk.CTkSwitch(opts, text="Re-calibrate", variable=self.var_recalib).pack(side="left", padx=(0, 14))
        ctk.CTkSwitch(opts, text="Skip network capture", variable=self.var_nonet).pack(side="left")

        self.run_btn = ctk.CTkButton(top, text="Run detection", width=160,
                                     command=self.on_run)
        self.run_btn.grid(row=0, column=2, rowspan=2, padx=12, pady=6, sticky="ns")

        top.columnconfigure(1, weight=1)

    def _build_log_area(self):
        mid = ctk.CTkFrame(self)
        mid.pack(fill="both", expand=True, padx=12, pady=6)
        self.log_box = ctk.CTkTextbox(mid, wrap="none")
        self.log_box.pack(fill="both", expand=True)
        self.log_box.configure(state="disabled")

    def _build_status_bar(self):
        bottom = ctk.CTkFrame(self)
        bottom.pack(fill="x", padx=12, pady=(6, 12))
        self.progress = ctk.CTkProgressBar(bottom)
        self.progress.pack(side="left", fill="x", expand=True, padx=(0, 12))
        self.progress.set(0)
        self.status_label = ctk.CTkLabel(bottom, text="Ready.", width=320)
        self.status_label.pack(side="right")

    # ----------------------------------------------------------- utilities

    def log(self, text):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def set_running(self, running: bool):
        self.run_btn.configure(state="disabled" if running else "normal")

    # --------------------------------------------------------- event pump

    def _pump_events(self):
        while True:
            ev = self.bridge.next_event(timeout=0)
            if ev is None:
                break
            kind, payload = ev
            if kind == GuiBridge.LOG:
                self.log(payload)
            elif kind == GuiBridge.PROGRESS:
                done, total, label = payload
                self.progress.set(done / total if total else 0)
                self.status_label.configure(text=f"[{done}/{total}] {label[:44]}")
            elif kind == GuiBridge.ASK:
                self._show_confirm(payload)
            elif kind == GuiBridge.PROMPT:
                self._show_prompt(payload)
            elif kind == GuiBridge.DONE:
                self._on_done(payload)
        self.after(100, self._pump_events)

    # ------------------------------------------------------------ dialogs

    def _show_confirm(self, payload):
        eid, question = payload
        dlg = ctk.CTkToplevel(self)
        dlg.title("Calibration question")
        dlg.geometry("520x180")
        dlg.attributes("-topmost", True)
        ctk.CTkLabel(dlg, text=question, wraplength=460, justify="left").pack(padx=16, pady=(18, 8))
        row = ctk.CTkFrame(dlg, fg_color="transparent")
        row.pack(pady=8)

        def answer(val):
            dlg.destroy()
            self._dialog = None
            self.bridge.reply(val)

        ctk.CTkButton(row, text="Yes", width=90, command=lambda: answer(True)).pack(side="left", padx=8)
        ctk.CTkButton(row, text="No", width=90, fg_color="gray",
                      command=lambda: answer(False)).pack(side="left", padx=8)
        self._dialog = dlg

    def _show_prompt(self, payload):
        eid, question = payload
        dlg = ctk.CTkToplevel(self)
        dlg.title("Calibration step")
        dlg.geometry("560x200")
        dlg.attributes("-topmost", True)
        ctk.CTkLabel(dlg, text=question, wraplength=500, justify="left").pack(padx=16, pady=(14, 6))
        entry = ctk.CTkEntry(dlg, width=480)
        entry.pack(pady=6)

        def answer():
            dlg.destroy()
            self._dialog = None
            self.bridge.reply(entry.get())

        ctk.CTkButton(dlg, text="Continue", command=answer).pack(pady=8)
        self._dialog = dlg

    # ------------------------------------------------------------ actions

    def on_run(self):
        url = self.url_entry.get().strip()
        if not url:
            self.log("Please enter a chat site URL first.")
            return
        claimed_key = self.CLAIM_KEYS.get(self.claim_menu.get())
        self.set_running(True)
        self.progress.set(0)
        self.status_label.configure(text="Starting ...")
        self.worker = Worker(
            self.bridge, url, claimed_key,
            headless=self.var_headless.get(),
            force_calibrate=self.var_recalib.get(),
            skip_network=self.var_nonet.get(),
            report_dir=None,
        )
        self.worker.start()

    def _on_done(self, payload):
        result, error = payload
        self.set_running(False)
        if error:
            self.log("\n[ERROR] " + error)
            self.status_label.configure(text="Failed.")
            return
        self.last_result = result
        report = result["report"]
        v = report["verdict"]
        self.log("\n================ VERDICT ================")
        self.log(f"Model: {v['display_name']}")
        self.log(f"Confidence: {v['confidence']}   Score: {v['score']}")
        self.log(f"Signals: {', '.join(v['supporting_signals']) or 'none'}")
        claimed = report.get("claimed_model")
        if claimed:
            if claimed["matches_verdict"]:
                self.log("Site's claimed model MATCHES the verdict.")
            elif claimed["same_family"]:
                self.log("Site's claimed model is in the same family, different model.")
            else:
                self.log("Site's claimed model DISAGREES with the verdict.")
        c = report["censorship"]
        self.log(f"Censorship pairs: {c['hits']}/{c['total']} hits")
        self.log("=========================================")
        self.status_label.configure(text="Done.")
        self._show_result_buttons()

    def _show_result_buttons(self):
        win = ctk.CTkToplevel(self)
        win.title("Report ready")
        win.geometry("360x170")
        win.attributes("-topmost", True)
        ctk.CTkLabel(win, text="Detection finished. Open reports:").pack(pady=(16, 8))
        row = ctk.CTkFrame(win, fg_color="transparent")
        row.pack()
        ctk.CTkButton(row, text="Markdown", width=110,
                      command=lambda: webbrowser.open("file://" + str(self.last_result["md_path"]))).pack(side="left", padx=6)
        ctk.CTkButton(row, text="JSON", width=110,
                      command=lambda: webbrowser.open("file://" + str(self.last_result["json_path"]))).pack(side="left", padx=6)
        ctk.CTkButton(win, text="Open reports folder", width=220,
                      command=lambda: os.startfile(str(Path(self.last_result["json_path"]).parent))).pack(pady=10)


def main():
    parser = argparse.ArgumentParser(prog="AI Fingerprint Detector GUI")
    parser.add_argument("--selftest", action="store_true",
                        help="run headless verification and exit (for frozen builds)")
    args = parser.parse_args()
    if args.selftest:
        sys.exit(run_selftest())
    App().mainloop()


if __name__ == "__main__":
    main()
