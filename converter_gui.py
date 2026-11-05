#!/usr/bin/env python3
"""
Desktop window for the coordinate converter in xyz_to_lla.py.

Pick an input file (CSV with ECEF X/Y/Z in meters, or a CCSDS OEM text file),
choose how epochs are written (original, Gregorian, or MJD), choose comma or
space separated output, pick where to save, and click Convert. The conversion runs in a background thread so the window stays
responsive on large files.

"Check for updates" installs the latest GitHub release, checking each file against
the release's SHA256SUMS (see updater.py).

Run:
    python converter_gui.py
"""

import os
import queue
import re
import subprocess
import sys
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import updater
import xyz_to_lla as conv

APP_TITLE = "Coordinate Converter"
PAD = 8

TIME_FORMAT_LABELS = {
    "original": "As in file",
    "gregorian": "Gregorian (YYYY-MM-DDThh:mm:ss)",
    "mjd": "MJD (Modified Julian Date)",
}

# "Format" choices. comma and space are tables; nairas is a NAIRAS trajectory file.
SEPARATOR_LABELS = {
    "comma": "Comma separated (.csv)",
    "space": "Space separated (.txt)",
    "nairas": "NAIRAS trajectory (.txt, OEM input only)",
}


class ConverterApp:
    def __init__(self, root):
        self.root = root
        self.messages = queue.Queue()  # worker thread -> UI thread
        self.worker = None
        self.last_output = None

        root.title(f"{APP_TITLE} {conv.__version__}")
        root.minsize(560, 0)
        root.columnconfigure(0, weight=1)

        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.input_type = tk.StringVar(value="auto")
        self.time_format = tk.StringVar(value="original")
        self.fast = tk.BooleanVar(value=False)
        self.xcol = tk.StringVar(value="x")
        self.ycol = tk.StringVar(value="y")
        self.zcol = tk.StringVar(value="z")
        self.separator = tk.StringVar(value="comma")
        self.header = tk.BooleanVar(value=True)
        self.step = tk.StringVar(value="0")
        self.status = tk.StringVar(value="Choose an input file to start.")
        self.update_messages = queue.Queue()
        self._update_busy = False
        self._auto_output = True     # Save as still holds a name we suggested
        self._setting_output = False

        self._build_files()
        self._build_options()
        self._build_output_options()
        self._build_actions()

        self.input_path.trace_add("write", lambda *_: self._on_input_changed())
        self.output_path.trace_add("write", lambda *_: self._on_output_edited())
        self.input_type.trace_add("write", lambda *_: self._update_option_states())
        self.separator.trace_add("write", lambda *_: self._on_separator_changed())
        self._update_option_states()

        # Quietly look for a newer version after the window is up
        if updater.is_configured():
            self.root.after(1500, lambda: self._check_for_updates(quiet=True))

    # ------------------------------------------------------------------ layout

    def _build_files(self):
        box = ttk.LabelFrame(self.root, text="Files", padding=PAD)
        box.grid(row=0, column=0, sticky="ew", padx=PAD, pady=(PAD, 0))
        box.columnconfigure(1, weight=1)

        ttk.Label(box, text="Input").grid(row=0, column=0, sticky="w")
        ttk.Entry(box, textvariable=self.input_path).grid(row=0, column=1, sticky="ew", padx=PAD)
        ttk.Button(box, text="Browse...", command=self._browse_input).grid(row=0, column=2)

        ttk.Label(box, text="Save as").grid(row=1, column=0, sticky="w", pady=(PAD, 0))
        ttk.Entry(box, textvariable=self.output_path).grid(row=1, column=1, sticky="ew",
                                                           padx=PAD, pady=(PAD, 0))
        ttk.Button(box, text="Browse...", command=self._browse_output).grid(row=1, column=2,
                                                                         pady=(PAD, 0))

    def _build_options(self):
        box = ttk.LabelFrame(self.root, text="Options", padding=PAD)
        box.grid(row=1, column=0, sticky="ew", padx=PAD, pady=(PAD, 0))
        box.columnconfigure(1, weight=1)

        ttk.Label(box, text="Input type").grid(row=0, column=0, sticky="w")
        types = ttk.Frame(box)
        types.grid(row=0, column=1, sticky="w", padx=PAD)
        for value, text in (("auto", "Auto (.oem = OEM)"), ("oem", "OEM"), ("csv", "CSV")):
            ttk.Radiobutton(types, text=text, value=value,
                            variable=self.input_type).pack(side="left", padx=(0, PAD))

        # OEM options
        self.oem_frame = ttk.Frame(box)
        self.oem_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(PAD, 0))
        ttk.Label(self.oem_frame, text="Epoch format").grid(row=0, column=0, sticky="nw")
        fmt = ttk.Frame(self.oem_frame)
        fmt.grid(row=0, column=1, sticky="w", padx=PAD)
        for value in conv.TIME_FORMATS:
            ttk.Radiobutton(fmt, text=TIME_FORMAT_LABELS[value], value=value,
                            variable=self.time_format).pack(anchor="w")
        ttk.Checkbutton(self.oem_frame, variable=self.fast,
                        text="Fast mode (space-fixed frames, sub-millimeter difference)"
                        ).grid(row=1, column=1, sticky="w", padx=PAD, pady=(PAD // 2, 0))

        # CSV options
        self.csv_frame = ttk.Frame(box)
        self.csv_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(PAD, 0))
        ttk.Label(self.csv_frame, text="Column names").grid(row=0, column=0, sticky="w")
        cols = ttk.Frame(self.csv_frame)
        cols.grid(row=0, column=1, sticky="w", padx=PAD)
        for label, var in (("X", self.xcol), ("Y", self.ycol), ("Z", self.zcol)):
            ttk.Label(cols, text=label).pack(side="left")
            ttk.Entry(cols, textvariable=var, width=10).pack(side="left", padx=(2, PAD))

        self.oem_widgets = _all_children(self.oem_frame)
        self.epoch_widgets = _all_children(fmt)
        self.csv_widgets = _all_children(self.csv_frame)

    def _build_output_options(self):
        box = ttk.LabelFrame(self.root, text="Output", padding=PAD)
        box.grid(row=2, column=0, sticky="ew", padx=PAD, pady=(PAD, 0))
        box.columnconfigure(1, weight=1)

        ttk.Label(box, text="Format").grid(row=0, column=0, sticky="nw")
        seps = ttk.Frame(box)
        seps.grid(row=0, column=1, sticky="w", padx=PAD)
        self.format_buttons = {}
        for value, text in SEPARATOR_LABELS.items():
            b = ttk.Radiobutton(seps, text=text, value=value, variable=self.separator)
            b.pack(anchor="w")
            self.format_buttons[value] = b

        self.step_frame = ttk.Frame(box)
        self.step_frame.grid(row=1, column=1, sticky="w", padx=PAD, pady=(PAD // 2, 0))
        ttk.Label(self.step_frame, text="Keep one point every").pack(side="left")
        ttk.Entry(self.step_frame, textvariable=self.step, width=6).pack(side="left", padx=4)
        ttk.Label(self.step_frame, text="seconds (0 keeps all; NASA's samples use 60)").pack(side="left")
        self.step_frame.grid_remove()

        self.header_button = ttk.Checkbutton(box, variable=self.header,
                                             text="Include column names as the first line")
        self.header_button.grid(row=2, column=1, sticky="w", padx=PAD, pady=(PAD // 2, 0))
        self.space_hint = ttk.Label(
            box, foreground="gray", wraplength=480,
            text="For CCMC uploads, keep the file name to letters, numbers and underscores, "
                 "with no spaces in the folder path.")
        self.space_hint.grid(row=3, column=1, sticky="w", padx=PAD, pady=(PAD // 2, 0))
        self.space_hint.grid_remove()

    def _build_actions(self):
        box = ttk.Frame(self.root, padding=PAD)
        box.grid(row=3, column=0, sticky="ew")
        box.columnconfigure(0, weight=1)

        self.progress = ttk.Progressbar(box, mode="indeterminate")
        self.progress.grid(row=0, column=0, columnspan=4, sticky="ew")
        ttk.Label(box, textvariable=self.status, wraplength=520).grid(
            row=1, column=0, sticky="w", pady=(PAD // 2, 0))

        self.open_button = ttk.Button(box, text="Open folder", command=self._open_folder,
                                      state="disabled")
        self.open_button.grid(row=1, column=2, padx=PAD, pady=(PAD // 2, 0))
        self.update_button = ttk.Button(box, text="Check for updates",
                                        command=self._check_for_updates)
        self.update_button.grid(row=1, column=1, padx=(PAD, 0), pady=(PAD // 2, 0))
        self.convert_button = ttk.Button(box, text="Convert", command=self._start)
        self.convert_button.grid(row=1, column=3, pady=(PAD // 2, 0))
        self.root.bind("<Return>", lambda _e: self._start())

    # ----------------------------------------------------------------- helpers

    def _resolved_type(self):
        kind = self.input_type.get()
        if kind == "auto":
            return "oem" if self.input_path.get().strip().lower().endswith(".oem") else "csv"
        return kind

    def _update_option_states(self):
        is_oem = self._resolved_type() == "oem"
        _set_state(self.oem_widgets, is_oem)
        _set_state(self.csv_widgets, not is_oem)
        # NAIRAS needs the times in an OEM file
        _set_state([self.format_buttons["nairas"]], is_oem)
        if not is_oem and self.separator.get() == "nairas":
            self.separator.set("space")
        if self.separator.get() == "nairas":
            _set_state(self.epoch_widgets, False)   # NAIRAS always uses UTC calendar dates

    def _output_ext(self):
        return ".csv" if self.separator.get() == "comma" else ".txt"

    def _suggested_output(self, in_path):
        stem, _ = os.path.splitext(in_path)
        if self.separator.get() == "nairas":
            folder, name = os.path.split(stem)
            safe = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_") or "trajectory"
            return os.path.join(folder, safe + "_nairas.txt")
        return stem + "_lla" + self._output_ext()

    def _set_output(self, path, auto):
        self._setting_output = True
        try:
            self.output_path.set(path)
        finally:
            self._setting_output = False
        self._auto_output = auto

    def _on_output_edited(self):
        if not self._setting_output:
            self._auto_output = not self.output_path.get().strip()

    def _on_input_changed(self):
        self._update_option_states()
        path = self.input_path.get().strip()
        # Keep updating the suggestion while the user types, until they pick their own name
        if path and self._auto_output:
            self._set_output(self._suggested_output(path), auto=True)

    def _on_separator_changed(self):
        mode = self.separator.get()
        if mode == "comma":
            self.space_hint.grid_remove()
        else:
            self.space_hint.grid()
        if mode == "nairas":
            self.step_frame.grid()
            self.header_button.configure(text="Include # comment lines at the top")
        else:
            self.step_frame.grid_remove()
            self.header_button.configure(text="Include column names as the first line")
        self._update_option_states()
        if mode != "nairas" and self._resolved_type() == "oem":
            _set_state(self.epoch_widgets, True)
        # A name we suggested follows the format; a name the user chose only gets its
        # .csv/.txt ending swapped, and any other ending is left alone
        if self._auto_output and self.input_path.get().strip():
            self._set_output(self._suggested_output(self.input_path.get().strip()), auto=True)
            return
        out = self.output_path.get().strip()
        stem, ext = os.path.splitext(out)
        if out and ext.lower() in (".csv", ".txt") and ext.lower() != self._output_ext():
            self._set_output(stem + self._output_ext(), auto=self._auto_output)

    def _browse_input(self):
        path = filedialog.askopenfilename(
            title="Choose input file",
            filetypes=[("OEM or CSV", "*.oem *.txt *.csv"), ("OEM files", "*.oem *.txt"),
                       ("CSV files", "*.csv"), ("All files", "*.*")])
        if path:
            self._set_output("", auto=True)  # suggest a fresh name next to the new input
            self.input_path.set(path)

    def _browse_output(self):
        start = self.output_path.get().strip() or self.input_path.get().strip()
        ext = self._output_ext()
        types = [("Text files", "*.txt"), ("CSV files", "*.csv")]
        if ext == ".csv":
            types.reverse()
        path = filedialog.asksaveasfilename(
            title="Save output as", defaultextension=ext,
            initialdir=os.path.dirname(start) or None,
            initialfile=os.path.basename(start) if start.lower().endswith((".csv", ".txt")) else None,
            filetypes=types + [("All files", "*.*")])
        if path:
            self._set_output(path, auto=False)

    def _open_folder(self):
        if not self.last_output:
            return
        folder = os.path.dirname(os.path.abspath(self.last_output))
        try:
            if sys.platform.startswith("win"):
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.run(["open", folder], check=False)
            else:
                subprocess.run(["xdg-open", folder], check=False)
        except OSError as e:
            messagebox.showerror(APP_TITLE, f"Could not open the folder:\n{e}")

    # -------------------------------------------------------------- conversion

    def _start(self):
        if self.worker is not None and self.worker.is_alive():
            return
        in_path = self.input_path.get().strip()
        out_path = self.output_path.get().strip()
        if not in_path or not os.path.isfile(in_path):
            messagebox.showwarning(APP_TITLE, "Choose an input file that exists.")
            return
        if not out_path:
            messagebox.showwarning(APP_TITLE, "Choose where to save the output.")
            return
        if os.path.abspath(in_path) == os.path.abspath(out_path):
            messagebox.showwarning(APP_TITLE, "The output file must be different from the input file.")
            return
        if os.path.exists(out_path) and not messagebox.askyesno(
                APP_TITLE, f"{os.path.basename(out_path)} already exists. Replace it?"):
            return

        kind = self._resolved_type()
        mode = self.separator.get()
        out_opts = dict(separator=mode, header=self.header.get())
        if mode == "nairas":
            try:
                step = float(self.step.get().strip() or 0)
                if step < 0:
                    raise ValueError
            except ValueError:
                messagebox.showwarning(APP_TITLE, "The time step must be a number of seconds, "
                                                  "0 or more.")
                return
            fast, header = self.fast.get(), self.header.get()
            job = lambda report: conv.convert_oem_nairas(in_path, out_path, conv.OEM_CHUNKSIZE,
                                                         fast, step, header=header,
                                                         progress=report)
        elif kind == "csv":
            cols = [self.xcol.get().strip(), self.ycol.get().strip(), self.zcol.get().strip()]
            if not all(cols):
                messagebox.showwarning(APP_TITLE, "Fill in the X, Y and Z column names.")
                return
            job = lambda report: conv.convert_csv(in_path, out_path, *cols,
                                                  conv.CSV_CHUNKSIZE, progress=report,
                                                  **out_opts)
        else:
            fast, time_format = self.fast.get(), self.time_format.get()
            job = lambda report: conv.convert_oem(in_path, out_path, conv.OEM_CHUNKSIZE, fast,
                                                  time_format, progress=report, **out_opts)

        self.convert_button.configure(state="disabled")
        self.open_button.configure(state="disabled")
        self.progress.configure(mode="indeterminate", value=0)
        self.progress.start(12)
        self.status.set("Converting...")
        self.worker = threading.Thread(target=self._run, args=(job, out_path), daemon=True)
        self.worker.start()
        self.root.after(100, self._poll)

    def _run(self, job, out_path):
        """Runs in the background thread. Talks to the UI only through the queue."""
        try:
            total = job(lambda msg: self.messages.put(("status", msg)))
            self.messages.put(("done", (total, out_path)))
        except conv.ConverterError as e:
            self.messages.put(("error", str(e)))
        except PermissionError:
            self.messages.put(("error", f"Could not write {os.path.basename(out_path)}.\n"
                                        "If it is open in Excel or another program, close it and try again."))
        except FileNotFoundError:
            self.messages.put(("error", f"The folder for {os.path.basename(out_path)} does not exist."))
        except Exception as e:  # unexpected: show it, and print details for debugging
            traceback.print_exc()
            self.messages.put(("error", f"{type(e).__name__}: {e}"))

    def _poll(self):
        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == "status":
                    self.status.set(payload)
                elif kind == "done":
                    total, out_path = payload
                    self._finish(f"Done. Wrote {total:,} points to {os.path.basename(out_path)}")
                    self.last_output = out_path
                    self.open_button.configure(state="normal")
                    return
                elif kind == "error":
                    self._finish("Conversion failed.")
                    messagebox.showerror(APP_TITLE, payload)
                    return
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _finish(self, message):
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0 if message.startswith("Conversion failed") else 100)
        self.status.set(message)
        self.convert_button.configure(state="normal")


    # ----------------------------------------------------------------- updates

    def _run_update_task(self, task, on_done):
        """Run a network task in a background thread, then call on_done(ok, result) here."""
        self._update_busy = True
        self.update_button.configure(state="disabled")

        def work():
            try:
                self.update_messages.put((True, task()))
            except updater.UpdateError as e:
                self.update_messages.put((False, str(e)))
            except Exception as e:  # unexpected: show it, and print details for debugging
                traceback.print_exc()
                self.update_messages.put((False, f"{type(e).__name__}: {e}"))

        def poll():
            try:
                ok, result = self.update_messages.get_nowait()
            except queue.Empty:
                self.root.after(150, poll)
                return
            self._update_busy = False
            self.update_button.configure(state="normal")
            on_done(ok, result)

        threading.Thread(target=work, daemon=True).start()
        self.root.after(150, poll)

    def _converting(self):
        return self.worker is not None and self.worker.is_alive()

    def _check_for_updates(self, quiet=False):
        if self._update_busy:
            return
        if not updater.is_configured():
            messagebox.showinfo(APP_TITLE, "Updates are not set up yet. Fill in GITHUB_OWNER "
                                           "and GITHUB_REPO at the top of updater.py.")
            return
        current = conv.__version__

        def done(ok, latest):
            if not ok:
                if not quiet:
                    messagebox.showerror(APP_TITLE, latest)
                return
            if latest is None:
                if not quiet:
                    messagebox.showinfo(APP_TITLE, f"You have the newest version ({current}).")
                return
            if quiet:
                if not self._converting():
                    self.status.set(f"Version {latest} is available. "
                                    "Click Check for updates to install it.")
                return
            self._offer_update(current, latest)

        self._run_update_task(lambda: updater.check(current), done)

    def _offer_update(self, current, latest):
        if updater.installed_with_pip():
            self.root.clipboard_clear()
            self.root.clipboard_append(updater.pip_upgrade_command(latest))
            messagebox.showinfo(APP_TITLE, f"Version {latest} is available (you have {current}).\n\n"
                                           "This copy was installed with pip. Close the app and run "
                                           "this (it is copied to your clipboard):\n\n"
                                           f"{updater.pip_upgrade_command(latest)}")
            return
        if self._converting():
            messagebox.showinfo(APP_TITLE, f"Version {latest} is available. Install it after the "
                                           "current conversion finishes.")
            return
        if not messagebox.askyesno(APP_TITLE, f"Version {latest} is available (you have {current}).\n"
                                              "Download and install it now?"):
            return
        self.status.set(f"Downloading version {latest}...")

        def done(ok, result):
            if not ok:
                self.status.set("Update failed.")
                messagebox.showerror(APP_TITLE, result)
                return
            self.status.set(f"Updated to version {result}. Restart to use it.")
            if messagebox.askyesno(APP_TITLE, f"Updated to version {result}.\nRestart the app now?"):
                self.root.destroy()
                updater.restart()

        self._run_update_task(lambda: updater.install(current), done)


def _all_children(widget):
    out = []
    for child in widget.winfo_children():
        out.append(child)
        out.extend(_all_children(child))
    return out


def _set_state(widgets, enabled):
    for w in widgets:
        try:
            w.state(["!disabled"] if enabled else ["disabled"])
        except (AttributeError, tk.TclError):
            pass  # plain frames and labels without a state


def main():
    if sys.platform.startswith("win"):
        try:  # sharp text on high-resolution Windows screens instead of blurry scaling
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    try:
        ttk.Style(root).theme_use("clam" if sys.platform.startswith("linux") else None)
    except tk.TclError:
        pass
    ConverterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
