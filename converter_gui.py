#!/usr/bin/env python3
"""
Desktop window for the coordinate converter in xyz_to_lla.py.

Pick an input file (CSV with ECEF X/Y/Z in meters, or a CCSDS OEM text file),
choose how epochs are written (original, Gregorian, or MJD), pick where to save,
and click Convert. The conversion runs in a background thread so the window stays
responsive on large files.

Run:
    python converter_gui.py
"""

import os
import queue
import subprocess
import sys
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import xyz_to_lla as conv

APP_TITLE = "Coordinate Converter"
PAD = 8

TIME_FORMAT_LABELS = {
    "original": "As in file",
    "gregorian": "Gregorian (YYYY-MM-DDThh:mm:ss)",
    "mjd": "MJD (Modified Julian Date)",
}


class ConverterApp:
    def __init__(self, root):
        self.root = root
        self.messages = queue.Queue()  # worker thread -> UI thread
        self.worker = None
        self.last_output = None

        root.title(APP_TITLE)
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
        self.status = tk.StringVar(value="Choose an input file to start.")

        self._build_files()
        self._build_options()
        self._build_actions()

        self.input_path.trace_add("write", lambda *_: self._on_input_changed())
        self.input_type.trace_add("write", lambda *_: self._update_option_states())
        self._update_option_states()

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
        self.csv_widgets = _all_children(self.csv_frame)

    def _build_actions(self):
        box = ttk.Frame(self.root, padding=PAD)
        box.grid(row=2, column=0, sticky="ew")
        box.columnconfigure(0, weight=1)

        self.progress = ttk.Progressbar(box, mode="indeterminate")
        self.progress.grid(row=0, column=0, columnspan=3, sticky="ew")
        ttk.Label(box, textvariable=self.status, wraplength=520).grid(
            row=1, column=0, sticky="w", pady=(PAD // 2, 0))

        self.open_button = ttk.Button(box, text="Open folder", command=self._open_folder,
                                      state="disabled")
        self.open_button.grid(row=1, column=1, padx=PAD, pady=(PAD // 2, 0))
        self.convert_button = ttk.Button(box, text="Convert", command=self._start)
        self.convert_button.grid(row=1, column=2, pady=(PAD // 2, 0))
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

    def _on_input_changed(self):
        self._update_option_states()
        path = self.input_path.get().strip()
        if path and not self.output_path.get().strip():
            stem, _ = os.path.splitext(path)
            self.output_path.set(stem + "_lla.csv")

    def _browse_input(self):
        path = filedialog.askopenfilename(
            title="Choose input file",
            filetypes=[("OEM or CSV", "*.oem *.txt *.csv"), ("OEM files", "*.oem *.txt"),
                       ("CSV files", "*.csv"), ("All files", "*.*")])
        if path:
            self.output_path.set("")  # suggest a fresh name next to the new input
            self.input_path.set(path)

    def _browse_output(self):
        start = self.output_path.get().strip() or self.input_path.get().strip()
        path = filedialog.asksaveasfilename(
            title="Save output as", defaultextension=".csv",
            initialdir=os.path.dirname(start) or None,
            initialfile=os.path.basename(start) if start.endswith(".csv") else None,
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if path:
            self.output_path.set(path)

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
        if kind == "csv":
            cols = [self.xcol.get().strip(), self.ycol.get().strip(), self.zcol.get().strip()]
            if not all(cols):
                messagebox.showwarning(APP_TITLE, "Fill in the X, Y and Z column names.")
                return
            job = lambda report: conv.convert_csv(in_path, out_path, *cols,
                                                  conv.CSV_CHUNKSIZE, progress=report)
        else:
            fast, time_format = self.fast.get(), self.time_format.get()
            job = lambda report: conv.convert_oem(in_path, out_path, conv.OEM_CHUNKSIZE, fast,
                                                  time_format, progress=report)

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
    root = tk.Tk()
    try:
        ttk.Style(root).theme_use("clam" if sys.platform.startswith("linux") else None)
    except tk.TclError:
        pass
    ConverterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
