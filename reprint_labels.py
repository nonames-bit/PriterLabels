"""Reprint DataMatrix labels from a PC, straight to the Honeywell printer.

Sends the same Fingerprint program the PLC (NX102) builds, over TCP port 9100,
so the label comes out identical: DataMatrix 'P<part> T<YYYYMMDDHHMMSS>',
part number and date 'YY/MM/DD-HH:MM:SS'.

Usage:
    python reprint_labels.py              -> opens the window (list of parts,
                                             quantity, Pause / Resume / Stop)
    python reprint_labels.py 85066731 3   -> prints 3 labels without the window

The printer IP/port can be changed in the window; it is saved in settings.json.
"""
import json
import os
import re
import socket
import sys
import time
from datetime import datetime

try:  # pure-Python DataMatrix encoder, only used for the on-screen preview
    from ppf.datamatrix import DataMatrix
except ImportError:
    DataMatrix = None

PRINTER_IP = "10.48.180.143"
PRINTER_PORT = 9100
FONT = '"Univers Condensed Bold"'

# Position offset in dots, added to every PP coordinate.
# Positive X moves right; positive Y moves up (the date has the smallest Y, which is
# why it sits at the bottom).
DEFAULT_OFFSET = {"x": -15, "y": 10}  # tuned on the real printer
OFFSET = dict(DEFAULT_OFFSET)

# Printer IP/port and offset are saved in settings.json next to the program
# (next to the .exe when it is built with PyInstaller).
BASE_DIR = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")


def load_settings():
    global PRINTER_IP, PRINTER_PORT
    try:
        with open(SETTINGS_FILE) as f:
            data = json.load(f)
        PRINTER_IP = str(data.get("ip", PRINTER_IP))
        PRINTER_PORT = int(data.get("port", PRINTER_PORT))
        OFFSET.update({k: int(data[k]) for k in OFFSET if k in data})
    except (OSError, ValueError, TypeError):
        pass


def save_settings():
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump({"ip": PRINTER_IP, "port": PRINTER_PORT, **OFFSET}, f, indent=2)
    except OSError:
        pass


def shift_positions(text, dx, dy):
    """Add dx/dy to every 'PPx,y' in the Fingerprint program."""
    return re.sub(r"PP(-?\d+),(-?\d+)",
                  lambda m: f"PP{max(0, int(m.group(1)) + dx)},{max(0, int(m.group(2)) + dy)}", text)

# Same as the PLC's LINES[0..21] (printer setup).
SETUP = [
    'INPUT OFF\nVERBOFF\n',
    'INPUT ON\n',
    'SYSVAR(48) = 0\n',
    'SYSVAR(35)=1\n',
    'OPEN "tmp:setup.sys" FOR OUTPUT AS #1\n',
    'PRINT#1,"Printing,Media,Print Area,Media Margin (X),-15"\n'
    'PRINT#1,"Printing,Media,Print Method,Ribbon (TTR)"\n',
    'PRINT#1,"Printing,Print Quality,Media Sensitivity,Very Low"\n',
    None,  # LTS (auto peel), filled in by build_job
    'PRINT#1,"Printing,Media,Media Type,Media With Gaps"\n',
    'PRINT#1,"Printing,Media,Start Adjust,-280"\n',
    'PRINT#1,"Printing,Media,Stop Adjust,-20"\n',
    'PRINT#1,"Printing,Media,Print Area,Media Width,831"\n',
    'PRINT#1,"Printing,Media,Print Area,Media Length,190"\n',
    'PRINT#1,"Printing,Print Quality,Darkness,65"\n',
    'PRINT#1,"Printing,Print Quality,Contrast,0"\n',
    'PRINT#1,"Printing,Print Quality,Print Speed,30"\n',
    'PRINT#1,"Printing,Media,Media Calibration Mode,SLOW"\n',
    'PRINT#1,"Printing,Media,Length (Slow Mode),0"\n',
    'PRINT#1,"Printing,Media,Clip Default,On"\nCLOSE #1\n',
    'SETUP "tmp:setup.sys"\nKILL "tmp:setup.sys"\n',
    'LTS& OFF\nCUT OFF\nOPTIMIZE "BATCH" ON\n',
    'ON ERROR GOTO QAAA\n',
]


def build_job(part, when, option=0, auto_peel=False):
    """Return (Fingerprint text, DataMatrix content). option: 0 none, 1 'L', 2 'R'."""
    part = part.strip()
    barcode = f"P{part} T{when:%Y%m%d%H%M%S}"
    setup = list(SETUP)
    setup[7] = f'PRINT#1,"Printing,Media,LTS Sensitivity Level,{5 if auto_peel else 0}"\n'

    side = {1: f"{part[-4:]} L", 2: f"{part[-4:]} R"}.get(option, "")
    small_y = 158 if option == 0 else 111
    label = [
        'PP250,5:AN1\n',
        'BARSET "DATAMATRIX",1,1,5,144,0,8\n',
        f'PB "{barcode}"\n',
        f'PP385,70:AN1\nNASC 1252\nFT {FONT},14,0,85\nPT "{part}"\n',
        f'PP240,174:FT {FONT},18,0,101\nPT "{side}"\nPP162,{small_y}:FT {FONT},10,0,101\n',
        'PT ""\n',
        f'PP385,10:FT {FONT},11,0,101\n',
        f'PT "{when:%y/%m/%d-%H:%M:%S}"\n',
        'PRINT "9999"\n',
        'QAAA: \n',
        'A%= PRSTAT\n',
        'PRINT A%\n',
        'RESUME NEXT\n',
        'LAYOUT RUN ""\nPF\nDONE',
    ]
    return "".join(setup) + shift_positions("".join(label), OFFSET["x"], OFFSET["y"]), barcode


def send(job, ip=None, port=None):
    with socket.create_connection((ip or PRINTER_IP, port or PRINTER_PORT), timeout=5) as s:
        s.sendall(job.encode("cp1252"))


def print_labels(part, copies=1, option=0, fixed_time=None, log=print,
                 pause=None, stop=None, done_before=0, total=None):
    """Print 'copies' labels, one at a time. Without fixed_time it uses the current time,
    one second apart per label (like the PLC), so every DataMatrix is unique.
    pause/stop are optional threading.Event: while pause is set it waits before the
    next label; when stop is set it stops printing. Returns how many were sent."""
    total = total or copies
    sent = 0
    for i in range(copies):
        if fixed_time is None and i > 0:
            time.sleep(1)
        while pause is not None and pause.is_set() and not (stop and stop.is_set()):
            time.sleep(0.1)
        if stop is not None and stop.is_set():
            break
        when = fixed_time or datetime.now()
        job, barcode = build_job(part, when, option)
        send(job)
        sent += 1
        log(f"Sent {done_before + sent}/{total}: {barcode}")
    return sent


def gui(selftest=False):
    import threading
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title("Reprint labels")
    frm = ttk.Frame(root, padding=12)
    frm.grid()

    # --- One row of the list ---
    ttk.Label(frm, text="Part number").grid(row=0, column=0, sticky="w")
    part_var = tk.StringVar(value="85066731")
    part_entry = ttk.Entry(frm, textvariable=part_var, width=20)
    part_entry.grid(row=0, column=1, sticky="w", pady=2)

    ttk.Label(frm, text="Quantity").grid(row=1, column=0, sticky="w")
    qty_var = tk.IntVar(value=60)
    ttk.Spinbox(frm, from_=1, to=1000, textvariable=qty_var, width=6).grid(row=1, column=1, sticky="w", pady=2)

    ttk.Label(frm, text="Side").grid(row=2, column=0, sticky="w")
    opt_var = tk.StringVar(value="None")
    ttk.Combobox(frm, textvariable=opt_var, values=["None", "L", "R"], state="readonly", width=8).grid(
        row=2, column=1, sticky="w", pady=2)

    # --- Job list ---
    table = ttk.Treeview(frm, columns=("part", "qty", "side"), show="headings", height=6)
    for col, txt, w in (("part", "Part number", 140), ("qty", "Quantity", 70), ("side", "Side", 60)):
        table.heading(col, text=txt)
        table.column(col, width=w)
    table.grid(row=4, column=0, columnspan=3, pady=(6, 0))

    def add_row():
        part = part_var.get().strip()
        if not part:
            messagebox.showwarning("Missing data", "Enter the part number.")
            return
        try:
            qty = int(qty_var.get())
        except (tk.TclError, ValueError):
            qty = 0
        if qty < 1:
            messagebox.showwarning("Quantity", "Quantity must be 1 or more.")
            return
        table.insert("", "end", values=(part, qty, opt_var.get()))
        part_var.set("")
        part_entry.focus()

    def remove_row():
        for item in table.selection():
            table.delete(item)

    btns = ttk.Frame(frm)
    btns.grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
    ttk.Button(btns, text="Add to list", command=add_row).grid(row=0, column=0)
    ttk.Button(btns, text="Remove selected", command=remove_row).grid(row=0, column=1, padx=4)
    part_entry.bind("<Return>", lambda e: add_row())

    # --- Label position: arrow buttons, no numbers to type ---
    STEP = 5  # dots per click (about 0.4 mm at 300 dpi)
    adj = ttk.LabelFrame(frm, text="Label position", padding=6)
    adj.grid(row=10, column=0, columnspan=3, sticky="we", pady=(8, 0))
    pos_text = tk.StringVar()
    preview_hooks = []  # redraw callbacks, filled in once the preview exists

    def describe_position():
        def part(value, pos, neg):
            clicks = abs(value) // STEP
            return f"{clicks} {pos if value > 0 else neg}" if clicks else ""
        dx, dy = OFFSET["x"] - DEFAULT_OFFSET["x"], OFFSET["y"] - DEFAULT_OFFSET["y"]
        moves = [m for m in (part(dx, "right", "left"), part(dy, "up", "down")) if m]
        pos_text.set("Moved: " + ", ".join(moves) if moves else "Normal position")
        for fn in preview_hooks:
            fn()

    def move(dx, dy):
        OFFSET["x"] += dx * STEP
        OFFSET["y"] += dy * STEP
        save_settings()
        describe_position()

    def reset_position():
        OFFSET.update(DEFAULT_OFFSET)
        save_settings()
        describe_position()

    pad = ttk.Frame(adj)
    pad.grid(row=0, column=0, rowspan=3)
    ttk.Button(pad, text="\u25b2 Up", width=8, command=lambda: move(0, 1)).grid(row=0, column=1)
    ttk.Button(pad, text="\u25c0 Left", width=8, command=lambda: move(-1, 0)).grid(row=1, column=0)
    ttk.Button(pad, text="Reset", width=8, command=reset_position).grid(row=1, column=1)
    ttk.Button(pad, text="Right \u25b6", width=8, command=lambda: move(1, 0)).grid(row=1, column=2)
    ttk.Button(pad, text="\u25bc Down", width=8, command=lambda: move(0, -1)).grid(row=2, column=1)
    ttk.Label(adj, textvariable=pos_text).grid(row=0, column=1, sticky="w", padx=(10, 0))
    describe_position()

    def read_offset():
        """Validate and save the printer IP/port (the position is saved on every click)."""
        global PRINTER_IP, PRINTER_PORT
        ip = ip_var.get().strip()
        try:
            port = int(port_var.get())
        except (tk.TclError, ValueError):
            port = 0
        if not ip or not 0 < port < 65536:
            messagebox.showwarning("Printer", "Enter a valid printer IP and port.")
            return False
        PRINTER_IP, PRINTER_PORT = ip, port
        save_settings()
        status.set(f"Printer {PRINTER_IP}:{PRINTER_PORT}")
        return True

    def on_test():
        part = part_var.get().strip() or "85066731"
        if not read_offset():
            return
        try:
            send(build_job(part, datetime.now(), {"None": 0, "L": 1, "R": 2}[opt_var.get()])[0])
            status.set(f"Test label sent ({pos_text.get()})")
        except OSError as e:
            messagebox.showerror("Error", f"Could not send to the printer:\n{e}")

    ttk.Button(adj, text="Print 1 test label", command=on_test).grid(row=1, column=1, sticky="w", padx=(10, 0))

    net = ttk.Frame(frm)
    net.grid(row=11, column=0, columnspan=3, sticky="w", pady=(8, 0))
    ttk.Label(net, text="Printer IP").grid(row=0, column=0, sticky="w")
    ip_var = tk.StringVar(value=PRINTER_IP)
    ttk.Entry(net, textvariable=ip_var, width=16).grid(row=0, column=1, sticky="w", padx=4)
    ttk.Label(net, text="Port").grid(row=0, column=2, sticky="w")
    port_var = tk.IntVar(value=PRINTER_PORT)
    ttk.Entry(net, textvariable=port_var, width=6).grid(row=0, column=3, sticky="w", padx=4)

    fixed_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(frm, text="Use fixed date (YYYY-MM-DD HH:MM:SS)", variable=fixed_var).grid(
        row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))
    date_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    ttk.Entry(frm, textvariable=date_var, width=22).grid(row=6, column=0, columnspan=3, sticky="w")

    # --- Print control ---
    progress = ttk.Progressbar(frm, length=280)
    progress.grid(row=8, column=0, columnspan=3, pady=(8, 0))
    status = tk.StringVar(value=f"Printer {PRINTER_IP}:{PRINTER_PORT}")
    ttk.Label(frm, textvariable=status).grid(row=9, column=0, columnspan=3, sticky="w")

    pause_ev = threading.Event()
    stop_ev = threading.Event()
    ctrl = ttk.Frame(frm)
    ctrl.grid(row=7, column=0, columnspan=3, sticky="w", pady=(8, 0))
    print_btn = ttk.Button(ctrl, text="Print")
    pause_btn = ttk.Button(ctrl, text="Pause", state="disabled")
    stop_btn = ttk.Button(ctrl, text="Stop", state="disabled")
    print_btn.grid(row=0, column=0)
    pause_btn.grid(row=0, column=1, padx=4)
    stop_btn.grid(row=0, column=2)

    def ui(fn, *args):
        root.after(0, fn, *args)  # only touch tkinter from the main thread

    def set_running(running):
        print_btn.config(state="disabled" if running else "normal")
        pause_btn.config(state="normal" if running else "disabled", text="Pause")
        stop_btn.config(state="normal" if running else "disabled")

    def worker(rows, fixed):
        total = sum(q for _, q, _ in rows)
        done = 0
        try:
            for part, qty, option in rows:
                done += print_labels(
                    part, qty, option, fixed, pause=pause_ev, stop=stop_ev, done_before=done, total=total,
                    log=lambda m: ui(lambda m=m: (status.set(m), progress.step(1))))
                if stop_ev.is_set():
                    break
            final = f"Stopped: {done}/{total} sent" if stop_ev.is_set() else f"Done: {total} labels sent"
            ui(status.set, final)
        except OSError as e:
            ui(messagebox.showerror, "Error", f"Could not send to the printer ({done} sent so far):\n{e}")
            ui(status.set, f"Error after {done} labels")
        finally:
            ui(set_running, False)

    def on_print():
        rows = []
        for item in table.get_children():
            part, qty, side = table.item(item, "values")
            rows.append((str(part), int(qty), {"None": 0, "L": 1, "R": 2}[side]))
        if not rows:
            if not part_var.get().strip():
                messagebox.showwarning("Empty list", "Add at least one part number.")
                return
            add_row()
            return on_print()
        try:
            fixed = datetime.strptime(date_var.get().strip(), "%Y-%m-%d %H:%M:%S") if fixed_var.get() else None
        except ValueError:
            messagebox.showwarning("Date", "Date format: 2026-10-29 10:43:30")
            return
        if not read_offset():
            return
        total = sum(q for _, q, _ in rows)
        if not messagebox.askyesno("Confirm", f"Print {total} labels?"):
            return
        pause_ev.clear()
        stop_ev.clear()
        progress.config(maximum=total, value=0)
        set_running(True)
        threading.Thread(target=worker, args=(rows, fixed), daemon=True).start()

    def on_pause():
        if pause_ev.is_set():
            pause_ev.clear()
            pause_btn.config(text="Pause")
            status.set("Resuming...")
        else:
            pause_ev.set()
            pause_btn.config(text="Resume")
            status.set("Paused (1 more label already in the printer may still come out)")

    def on_stop():
        stop_ev.set()
        status.set("Stopping...")

    print_btn.config(command=on_print)
    pause_btn.config(command=on_pause)
    stop_btn.config(command=on_stop)
    # --- Label preview (approximate, drawn from the same coordinates sent to the printer) ---
    # Label edges in printer dots, measured from a PLC-printed label (203 dpi, ~1.9" x 0.94"),
    # shifted by the default offset so "Normal position" looks centered.
    LX0, LX1 = 236 + DEFAULT_OFFSET["x"], 620 + DEFAULT_OFFSET["x"]
    LY0, LY1 = -36 + DEFAULT_OFFSET["y"], 154 + DEFAULT_OFFSET["y"]
    S, PAD = 1.1, 12  # screen pixels per dot, margin around the label
    pv = ttk.LabelFrame(frm, text="Preview", padding=6)
    pv.grid(row=0, column=3, rowspan=12, sticky="n", padx=(12, 0))
    cw, ch = int((LX1 - LX0) * S) + 2 * PAD, int((LY1 - LY0) * S) + 2 * PAD
    canvas = tk.Canvas(pv, width=cw, height=ch, bg="#d9d9d9", highlightthickness=0)
    canvas.grid()
    ttk.Label(pv, text="Approximate. Print 1 test label to confirm.").grid(sticky="w")

    def to_px(x, y):
        return PAD + (x - LX0) * S, PAD + (LY1 - y) * S

    def preview_time():
        if fixed_var.get():
            try:
                return datetime.strptime(date_var.get().strip(), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass
        return datetime.now()

    def draw_preview():
        canvas.delete("all")
        part = part_var.get().strip() or "PART NUMBER"
        when = preview_time()
        option = {"None": 0, "L": 1, "R": 2}[opt_var.get()]
        dx, dy = OFFSET["x"], OFFSET["y"]
        x0, y0 = to_px(LX0, LY1)
        x1, y1 = to_px(LX1, LY0)
        canvas.create_rectangle(x0, y0, x1, y1, fill="white", outline="#888")

        # DataMatrix: lower-left corner at PP250,5, about 120 dots square
        size = 120
        bx, by = to_px(250 + dx, 5 + dy + size)
        content = f"P{part} T{when:%Y%m%d%H%M%S}"
        if DataMatrix is not None:
            rows = DataMatrix(content).matrix
            cell = size * S / len(rows)
            for r, row in enumerate(rows):
                for c, bit in enumerate(row):
                    if bit:
                        canvas.create_rectangle(bx + c * cell, by + r * cell, bx + (c + 1) * cell,
                                                by + (r + 1) * cell, fill="black", width=0)
        else:
            canvas.create_rectangle(bx, by, bx + size * S, by + size * S, fill="#444", width=0)

        def text(x, y, txt, height):
            px, py = to_px(x + dx, y + dy)
            canvas.create_text(px, py, text=txt, anchor="sw", fill="black",
                               font=("Arial Narrow", -max(6, int(height * S)), "bold"))

        text(385, 70, part, 26)
        if option:
            text(240, 174, f"{part[-4:]} {'L' if option == 1 else 'R'}", 32)
        text(385, 10, f"{when:%y/%m/%d-%H:%M:%S}", 20)

        # Hide whatever falls outside the label, like the printer would
        bg = canvas["bg"]
        for rect in ((0, 0, cw, y0), (0, y1, cw, ch), (0, 0, x0, ch), (x1, 0, cw, ch)):
            canvas.create_rectangle(*rect, fill=bg, width=0)
        canvas.create_rectangle(x0, y0, x1, y1, outline="#888")

    preview_hooks.append(draw_preview)
    for var in (part_var, opt_var, fixed_var, date_var):
        var.trace_add("write", lambda *_: draw_preview())

    def tick():
        if not fixed_var.get():
            draw_preview()
        root.after(1000, tick)

    tick()
    if selftest:  # CI check: build the window, click the arrows, then close
        def fail(*exc):
            import traceback
            traceback.print_exception(*exc)
            os._exit(1)
        root.report_callback_exception = fail
        for fn in (lambda: move(1, 0), lambda: move(0, -1), reset_position,
                   lambda: opt_var.set("L"), lambda: fixed_var.set(True), lambda: part_var.set("12345678")):
            root.after(200, fn)
        root.after(1500, root.destroy)
    root.mainloop()


if __name__ == "__main__":
    load_settings()
    if sys.argv[1:] == ["--selftest"]:
        gui(selftest=True)
    elif len(sys.argv) >= 2:
        print_labels(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 1)
    else:
        gui()
