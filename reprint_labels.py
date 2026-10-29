"""Reprint DataMatrix labels from a PC, straight to the Honeywell printer.

Created by Jaime.

Sends the same Fingerprint programs the PLCs build, over TCP port 9100, so the labels
come out identical. Label types (see TEMPLATES):
    A  DataMatrix 'P<part> T<YYYYMMDDHHMMSS>', part number, date 'YY/MM/DD-HH:MM:SS'
    B  DataMatrix 'P<part>T<YYYYMMDDHHMMSS>', part number, 'YYYY/MM/DD    HH:MM:SS'
    C  DataMatrix '<part> T<YYYYMMDDHHMMSS>', date, time, Y code, part number at the bottom

Usage:
    python reprint_labels.py                          -> opens the window
    python reprint_labels.py 85066731 3               -> prints 3 labels of type A
    python reprint_labels.py N1WB-E018W18-CF 3 C Y0124069

The printer IP/port can be changed in the window; it is saved in settings.json.
"""
import json
import os
import random
import re
import socket
import sys
import time
from datetime import datetime, timedelta

try:  # pure-Python DataMatrix encoder, only used for the on-screen preview
    from ppf.datamatrix import DataMatrix
except ImportError:
    DataMatrix = None

PRINTER_IP = "10.48.180.143"
PRINTER_PORT = 9100
FONT = '"Univers Condensed Bold"'
DOTS_PER_PT = 1.86  # text height in dots per font point, measured on a printed label


def setup_lines(margin, start, stop, width, length, darkness, speed, lts, auto_peel=False):
    """Printer setup, same as the PLC's LINES[0..21]; the values change per label type."""
    return [
        'INPUT OFF\nVERBOFF\n',
        'INPUT ON\n',
        'SYSVAR(48) = 0\n',
        'SYSVAR(35)=1\n',
        'OPEN "tmp:setup.sys" FOR OUTPUT AS #1\n',
        f'PRINT#1,"Printing,Media,Print Area,Media Margin (X),{margin}"\n'
        'PRINT#1,"Printing,Media,Print Method,Ribbon (TTR)"\n',
        'PRINT#1,"Printing,Print Quality,Media Sensitivity,Very Low"\n',
        f'PRINT#1,"Printing,Media,LTS Sensitivity Level,{5 if auto_peel else 0}"\n',
        '\tPRINT#1,"Printing,Media,Media Type,Media With Gaps"\n',
        f'PRINT#1,"Printing,Media,Start Adjust,{start}"\n',
        f'PRINT#1,"Printing,Media,Stop Adjust,{stop}"\n',
        f'PRINT#1,"Printing,Media,Print Area,Media Width,{width}"\n',
        f'PRINT#1,"Printing,Media,Print Area,Media Length,{length}"\n',
        f'PRINT#1,"Printing,Print Quality,Darkness,{darkness}"\n',
        'PRINT#1,"Printing,Print Quality,Contrast,0"\n',
        f'PRINT#1,"Printing,Print Quality,Print Speed,{speed}"\n',
        'PRINT#1,"Printing,Media,Media Calibration Mode,SLOW"\n',
        'PRINT#1,"Printing,Media,Length (Slow Mode),0"\n',
        'PRINT#1,"Printing,Media,Clip Default,On"\nCLOSE #1\n',
        'SETUP "tmp:setup.sys"\nKILL "tmp:setup.sys"\n',
        f'LTS& {lts}\nCUT OFF\nOPTIMIZE "BATCH" ON\n',
        'ON ERROR GOTO QAAA\n',
    ]


# Same as the PLC's LINES[30..35] (error handler and print).
TAIL = ['PRINT "9999"\n', 'QAAA: \n', 'A%= PRSTAT\n', 'PRINT A%\n', 'RESUME NEXT\n', 'LAYOUT RUN ""\nPF\nDONE']


def side_text(part, option):
    return {1: f"{part[-4:]} L", 2: f"{part[-4:]} R"}.get(option, "")


def gm_side_text(part, option):
    # GM program: iGMPart_LastFour := MID(part, L:=2, P:=13)
    return {1: f"{part[12:14]} L", 2: f"{part[12:14]} R"}.get(option, "")


# --- Label types, copied from the PLC programs -------------------------------------------
# Each type gives: the printer setup, the DataMatrix content, the label lines (exact PLC text),
# and the elements for the on-screen preview: (kind, key, x, y, anchor, size, text) where anchor
# 1 = lower-left (AN1) and 7 = upper-left (AN7), size is the DataMatrix module in dots or the
# font size in points. 'rect' is the label edge in printer dots (x0, x1, y0, y1), approximate.
# pp(key, x, y) returns "PPx,y" moved by that element's own offset (dragged in the preview).

def a_lines(part, when, code, option, pp):
    return [
        f'{pp("dm", 250, 5)}:AN1\n',
        'BARSET "DATAMATRIX",1,1,5,144,0,8\n',
        f'PB "{a_barcode(part, when, code)}"\n',
        f'{pp("part", 385, 70)}:AN1\nNASC 1252\nFT {FONT},14,0,85\nPT "{part}"\n',
        f'{pp("side", 240, 174)}:FT {FONT},18,0,101\nPT "{side_text(part, option)}"\n'
        f'PP162,{158 if option == 0 else 111}:FT {FONT},10,0,101\n',
        'PT ""\n',
        f'{pp("date", 385, 10)}:FT {FONT},11,0,101\n',
        f'PT "{when:%y/%m/%d-%H:%M:%S}"\n',
    ]


def a_barcode(part, when, code):
    return f"P{part} T{when:%Y%m%d%H%M%S}"


def a_preview(part, when, code, option):
    return [("dm", "dm", 250, 5, 1, 6.5, a_barcode(part, when, code)),
            ("text", "part", 385, 70, 1, 14, part),
            ("text", "side", 240, 174, 1, 18, side_text(part, option)),
            ("text", "date", 385, 10, 1, 11, f"{when:%y/%m/%d-%H:%M:%S}")]


def b_lines(part, when, code, option, pp):
    return [
        f'{pp("dm", 50, 130)}:AN7\n',
        'BARSET "DATAMATRIX",1,1,3,144,0,9\n',
        f'PB "{b_barcode(part, when, code)}"\n',
        f'{pp("part", 147, 140)}:NASC 1252\nFT {FONT},14,0,80\nPT "{part}"\n',
        f'{pp("side", 240, 174)}:FT {FONT},18,0,101\nPT "{gm_side_text(part, option)}"\nPP162,111:FT {FONT},10,0,101\n',
        'PT ""\n',
        f'{pp("date", 147, 78)}:FT {FONT},9,0,101\nPT "{when:%Y/%m/%d}    {when:%H:%M:%S}"\n'
        f'PP147,66:FT {FONT},12,0,101\n',
        'PT ""\n',
    ]


def b_barcode(part, when, code):
    return f"P{part}T{when:%Y%m%d%H%M%S}"


def b_preview(part, when, code, option):
    return [("dm", "dm", 50, 130, 7, 3.9, b_barcode(part, when, code)),
            ("text", "part", 147, 140, 7, 14, part),
            ("text", "side", 240, 174, 7, 18, gm_side_text(part, option)),
            ("text", "date", 147, 78, 7, 9, f"{when:%Y/%m/%d}    {when:%H:%M:%S}")]


def c_lines(part, when, code, option, pp):
    # Same as the PLC, except the time is 6 dots lower (PLC: 90) so it does not touch the date,
    # and the part number is 10 dots to the right (PLC: 275).
    return [
        f'{pp("dm", 280, 110)}:AN7\n',
        'BARSET "DATAMATRIX",1,1,3,150,0,8\n',
        f'PB "{c_barcode(part, when, code)}"\n',
        f'{pp("part", 285, 30)}:NASC 1252\nFT {FONT},8,0,101\nPT "{part}"\n',
        f'{pp("time", 360, 84)}:FT {FONT},7,0,101\nPT "{when:%H:%M:%S}"\n',
        'PT ""\n',
        f'{pp("code", 360, 60)}:FT {FONT},8,0,101\nPT "{code}"\n{pp("date", 360, 110)}:FT {FONT},7,0,101\n',
        f'PT "{when:%Y/%m/%d}"\n',
    ]


def c_barcode(part, when, code):
    # The PLC builds CONCAT(In2:=part, In3:=' T', In4:=YYYYMMDDHHMMSS) with no In1.
    return f"{part} T{when:%Y%m%d%H%M%S}"


def c_preview(part, when, code, option):
    return [("dm", "dm", 280, 110, 7, 3.9, c_barcode(part, when, code)),
            ("text", "date", 360, 110, 7, 7, f"{when:%Y/%m/%d}"),
            ("text", "time", 360, 84, 7, 7, f"{when:%H:%M:%S}"),
            ("text", "code", 360, 60, 7, 8, code),
            ("text", "part", 285, 30, 7, 8, part)]


TEMPLATES = {
    "A": dict(name="Part + date (85066731)", lines=a_lines, barcode=a_barcode, preview=a_preview,
              setup=dict(margin=-15, start=-280, stop=-20, width=831, length=190, darkness=65,
                         speed=30, lts="OFF"),
              default_offset={"x": -15, "y": 10},  # tuned on the real printer
              rect=(236, 620, -36, 154), needs_code=False, has_side=True, sample="85066731"),
    "B": dict(name="GM part (P...T...)", lines=b_lines, barcode=b_barcode, preview=b_preview,
              setup=dict(margin=0, start=-100, stop=0, width=400, length=204, darkness=65,
                         speed=50, lts="ON"),
              default_offset={"x": 0, "y": 0},
              rect=(35, 370, 45, 155), needs_code=False, has_side=True, sample="M2DB-17B613-AG"),
    "C": dict(name="Y code, date on top", lines=c_lines, barcode=c_barcode, preview=c_preview,
              setup=dict(margin=0, start=-90, stop=-20, width=731, length=150, darkness=75,
                         speed=50, lts="OFF"),
              default_offset={"x": 0, "y": 0},
              rect=(266, 446, 8, 122), needs_code=True, has_side=False, sample="N1WB-E018W18-CF"),
}
DEFAULT_TEMPLATE = "A"

# Position offset per label type, in dots, added to every PP coordinate.
# Positive X moves right; positive Y moves up.
OFFSETS = {k: dict(t["default_offset"]) for k, t in TEMPLATES.items()}
# Extra offset per element (dm, part, date, time, code, side), set by dragging in the preview.
ELEMENT_OFFSETS = {k: {} for k in TEMPLATES}

# Printer IP/port and offsets are saved in settings.json next to the program
# (next to the .exe when it is built with PyInstaller).
BASE_DIR = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")


# Window color themes. "Normal" keeps the Windows look; the others are retro terminals.
THEMES = {
    "Normal": None,
    "Green terminal": dict(bg="#0a120a", fg="#33ff66", dim="#1f8a3a", field="#0f1f0f", select="#145a28"),
    "Amber terminal": dict(bg="#120b02", fg="#ffb000", dim="#a06a00", field="#1e1405", select="#5a3c00"),
}
THEME = "Normal"


def load_settings():
    global PRINTER_IP, PRINTER_PORT, THEME
    try:
        with open(SETTINGS_FILE) as f:
            data = json.load(f)
        PRINTER_IP = str(data.get("ip", PRINTER_IP))
        PRINTER_PORT = int(data.get("port", PRINTER_PORT))
        if data.get("theme") in THEMES:
            THEME = data["theme"]
        if "x" in data and "y" in data:  # older settings: one offset, for type A
            OFFSETS["A"].update(x=int(data["x"]), y=int(data["y"]))
        for k, off in data.get("offsets", {}).items():
            if k in OFFSETS:
                OFFSETS[k].update(x=int(off["x"]), y=int(off["y"]))
        for k, elems in data.get("element_offsets", {}).items():
            if k in ELEMENT_OFFSETS:
                ELEMENT_OFFSETS[k] = {e: [int(v[0]), int(v[1])] for e, v in elems.items()}
    except (OSError, ValueError, TypeError, KeyError):
        pass


def save_settings():
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump({"ip": PRINTER_IP, "port": PRINTER_PORT, "offsets": OFFSETS,
                       "element_offsets": ELEMENT_OFFSETS, "theme": THEME}, f, indent=2)
    except OSError:
        pass


def shift_positions(text, dx, dy):
    """Add dx/dy to every 'PPx,y' in the Fingerprint program."""
    return re.sub(r"PP(-?\d+),(-?\d+)",
                  lambda m: f"PP{max(0, int(m.group(1)) + dx)},{max(0, int(m.group(2)) + dy)}", text)


def build_job(part, when, option=0, auto_peel=False, template=DEFAULT_TEMPLATE, code=""):
    """Return (Fingerprint text, DataMatrix content). option: 0 none, 1 'L', 2 'R'."""
    t = TEMPLATES[template]
    part, code = part.strip(), code.strip()
    if not t["has_side"]:
        option = 0
    setup = setup_lines(auto_peel=auto_peel, **t["setup"])
    elems = ELEMENT_OFFSETS[template]

    def pp(key, x, y):
        ex, ey = elems.get(key, (0, 0))
        return f"PP{x + ex},{y + ey}"

    label = "".join(t["lines"](part, when, code, option, pp) + TAIL)
    off = OFFSETS[template]
    return "".join(setup) + shift_positions(label, off["x"], off["y"]), t["barcode"](part, when, code)


def send(job, ip=None, port=None):
    with socket.create_connection((ip or PRINTER_IP, port or PRINTER_PORT), timeout=5) as s:
        s.sendall(job.encode("cp1252"))


def print_labels(part, copies=1, option=0, fixed_time=None, log=print,
                 pause=None, stop=None, done_before=0, total=None, template=DEFAULT_TEMPLATE, code=""):
    """Print 'copies' labels, one at a time. Without fixed_time it uses the current time,
    one second apart per label (like the PLC), so every DataMatrix is unique. With
    fixed_time the first label of the whole run gets that time and each next one +1 second.
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
        when = fixed_time + timedelta(seconds=done_before + sent) if fixed_time else datetime.now()
        job, barcode = build_job(part, when, option, template=template, code=code)
        send(job)
        sent += 1
        log(f"Sent {done_before + sent}/{total}: {barcode}")
    return sent


def gui(selftest=False):
    import threading
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title("Reprint labels - Created by Jaime")
    BOOT_SECONDS = 1.8  # "loading" screen when a terminal theme starts
    crt = {"boot_end": 0}
    banner_var = tk.StringVar()
    banner = ttk.Label(root, textvariable=banner_var, style="Banner.TLabel", padding=(12, 8, 12, 0))
    frm = ttk.Frame(root, padding=12)
    frm.grid(row=1, column=0)

    # --- One row of the list ---
    type_names = list(TEMPLATES)
    ttk.Label(frm, text="Label type").grid(row=0, column=0, sticky="w")
    type_var = tk.StringVar(value=type_names[0])
    ttk.Combobox(frm, textvariable=type_var, values=type_names, state="readonly", width=4).grid(
        row=0, column=1, columnspan=2, sticky="w", pady=2)

    def cur():
        return type_var.get()[0]

    ttk.Label(frm, text="Part number").grid(row=1, column=0, sticky="w")
    part_var = tk.StringVar(value=TEMPLATES[DEFAULT_TEMPLATE]["sample"])
    part_entry = ttk.Entry(frm, textvariable=part_var, width=20)
    part_entry.grid(row=1, column=1, sticky="w", pady=2)

    ttk.Label(frm, text="Y code").grid(row=2, column=0, sticky="w")
    code_var = tk.StringVar()
    code_entry = ttk.Entry(frm, textvariable=code_var, width=20)
    code_entry.grid(row=2, column=1, sticky="w", pady=2)

    ttk.Label(frm, text="Quantity").grid(row=3, column=0, sticky="w")
    qty_var = tk.IntVar(value=60)
    ttk.Spinbox(frm, from_=1, to=1000, textvariable=qty_var, width=6).grid(row=3, column=1, sticky="w", pady=2)

    ttk.Label(frm, text="Side").grid(row=4, column=0, sticky="w")
    opt_var = tk.StringVar(value="None")
    side_box = ttk.Combobox(frm, textvariable=opt_var, values=["None", "L", "R"], state="readonly", width=8)
    side_box.grid(row=4, column=1, sticky="w", pady=2)

    def on_type_change(*_):
        t = TEMPLATES[cur()]
        code_entry.config(state="normal" if t["needs_code"] else "disabled")
        side_box.config(state="readonly" if t["has_side"] else "disabled")
        if not t["has_side"]:
            opt_var.set("None")
        part_var.set(t["sample"])
        describe_position()

    # --- Job list ---
    cols = (("type", "Type", 40), ("part", "Part number", 130), ("code", "Y code", 80),
            ("qty", "Qty", 45), ("side", "Side", 45))
    table = ttk.Treeview(frm, columns=[c[0] for c in cols], show="headings", height=6)
    for col, txt, w in cols:
        table.heading(col, text=txt)
        table.column(col, width=w)
    table.grid(row=6, column=0, columnspan=3, pady=(6, 0))
    jobs = {}  # table row id -> (type, part, code, qty, side); kept here so text is never re-parsed

    def add_row():
        t = TEMPLATES[cur()]
        part, code = part_var.get().strip(), code_var.get().strip()
        if not part:
            messagebox.showwarning("Missing data", "Enter the part number.")
            return False
        if t["needs_code"] and not code:
            messagebox.showwarning("Missing data", "Enter the Y code for this label type.")
            return False
        try:
            qty = int(qty_var.get())
        except (tk.TclError, ValueError):
            qty = 0
        if qty < 1:
            messagebox.showwarning("Quantity", "Quantity must be 1 or more.")
            return False
        code = code if t["needs_code"] else ""
        item = table.insert("", "end", values=(cur(), part, code, qty, opt_var.get()))
        jobs[item] = (cur(), part, code, qty, {"None": 0, "L": 1, "R": 2}[opt_var.get()])
        part_var.set("")
        part_entry.focus()
        return True

    def remove_row():
        for item in table.selection():
            table.delete(item)
            jobs.pop(item, None)

    def clear_list():
        for item in table.get_children():
            table.delete(item)
        jobs.clear()

    btns = ttk.Frame(frm)
    btns.grid(row=5, column=0, columnspan=3, sticky="w", pady=(4, 0))
    ttk.Button(btns, text="Add to list", command=add_row).grid(row=0, column=0)
    ttk.Button(btns, text="Remove selected", command=remove_row).grid(row=0, column=1, padx=4)
    ttk.Button(btns, text="Clear list", command=clear_list).grid(row=0, column=2)
    part_entry.bind("<Return>", lambda e: add_row())

    # --- Label position: arrow buttons move everything, drag in the preview moves one item ---
    STEP = 5  # dots per click
    adj = ttk.LabelFrame(frm, text="Label position (for the selected label type)", padding=6)
    adj.grid(row=12, column=0, columnspan=3, sticky="we", pady=(8, 0))
    pos_text = tk.StringVar()
    preview_hooks = []  # redraw callbacks, filled in once the preview exists

    def describe_position():
        def part(value, pos, neg):
            clicks = abs(value) // STEP
            return f"{clicks} {pos if value > 0 else neg}" if clicks else ""
        off, base = OFFSETS[cur()], TEMPLATES[cur()]["default_offset"]
        dx, dy = off["x"] - base["x"], off["y"] - base["y"]
        moves = [m for m in (part(dx, "right", "left"), part(dy, "up", "down")) if m]
        text = "Moved: " + ", ".join(moves) if moves else "Normal position"
        if any(ELEMENT_OFFSETS[cur()].values()):
            text += " (some items dragged)"
        pos_text.set(text)
        for fn in preview_hooks:
            fn()

    def move(dx, dy):
        OFFSETS[cur()]["x"] += dx * STEP
        OFFSETS[cur()]["y"] += dy * STEP
        save_settings()
        describe_position()

    def reset_position():
        OFFSETS[cur()].update(TEMPLATES[cur()]["default_offset"])
        ELEMENT_OFFSETS[cur()] = {}
        save_settings()
        describe_position()

    pad = ttk.Frame(adj)
    pad.grid(row=0, column=0, rowspan=3)
    ttk.Button(pad, text="▲ Up", width=8, command=lambda: move(0, 1)).grid(row=0, column=1)
    ttk.Button(pad, text="◀ Left", width=8, command=lambda: move(-1, 0)).grid(row=1, column=0)
    ttk.Button(pad, text="Reset", width=8, command=reset_position).grid(row=1, column=1)
    ttk.Button(pad, text="Right ▶", width=8, command=lambda: move(1, 0)).grid(row=1, column=2)
    ttk.Button(pad, text="▼ Down", width=8, command=lambda: move(0, -1)).grid(row=2, column=1)
    ttk.Label(adj, textvariable=pos_text).grid(row=0, column=1, sticky="w", padx=(10, 0))

    def read_offset():
        """Validate and save the printer IP/port (the position is saved on every change)."""
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
        t = TEMPLATES[cur()]
        part = part_var.get().strip() or t["sample"]
        if not read_offset():
            return
        try:
            send(build_job(part, datetime.now(), {"None": 0, "L": 1, "R": 2}[opt_var.get()],
                           template=cur(), code=code_var.get())[0])
            status.set(f"Test label sent ({pos_text.get()})")
        except OSError as e:
            messagebox.showerror("Error", f"Could not send to the printer:\n{e}")

    ttk.Button(adj, text="Print 1 test label", command=on_test).grid(row=1, column=1, sticky="w", padx=(10, 0))

    net = ttk.Frame(frm)
    net.grid(row=13, column=0, columnspan=3, sticky="w", pady=(8, 0))
    ttk.Label(net, text="Printer IP").grid(row=0, column=0, sticky="w")
    ip_var = tk.StringVar(value=PRINTER_IP)
    ttk.Entry(net, textvariable=ip_var, width=16).grid(row=0, column=1, sticky="w", padx=4)
    ttk.Label(net, text="Port").grid(row=0, column=2, sticky="w")
    port_var = tk.IntVar(value=PRINTER_PORT)
    ttk.Entry(net, textvariable=port_var, width=6).grid(row=0, column=3, sticky="w", padx=4)

    ttk.Label(net, text="Theme").grid(row=0, column=4, sticky="w", padx=(12, 0))
    theme_var = tk.StringVar(value=THEME)
    ttk.Combobox(net, textvariable=theme_var, values=list(THEMES), state="readonly", width=15).grid(
        row=0, column=5, sticky="w", padx=4)

    ttk.Label(frm, text="Created by Jaime", style="Dim.TLabel").grid(row=14, column=0, columnspan=4, sticky="e",
                                                                   pady=(8, 0))

    fixed_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(frm, text="Use another date/time (YYYY-MM-DD HH:MM:SS), +1 s per label", variable=fixed_var).grid(
        row=7, column=0, columnspan=3, sticky="w", pady=(6, 0))
    date_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    ttk.Entry(frm, textvariable=date_var, width=22).grid(row=8, column=0, columnspan=3, sticky="w")

    # --- Print control ---
    progress = ttk.Progressbar(frm, length=300)
    progress.grid(row=10, column=0, columnspan=3, pady=(8, 0))
    status = tk.StringVar(value=f"Printer {PRINTER_IP}:{PRINTER_PORT}")
    ttk.Label(frm, textvariable=status).grid(row=11, column=0, columnspan=3, sticky="w")

    pause_ev = threading.Event()
    stop_ev = threading.Event()
    ctrl = ttk.Frame(frm)
    ctrl.grid(row=9, column=0, columnspan=3, sticky="w", pady=(8, 0))
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
        total = sum(r[3] for r in rows)
        done = 0
        try:
            for template, part, code, qty, option in rows:
                done += print_labels(
                    part, qty, option, fixed, pause=pause_ev, stop=stop_ev, done_before=done, total=total,
                    template=template, code=code,
                    log=lambda m: ui(lambda m=m: (status.set(m), progress.step(1))))
                if stop_ev.is_set():
                    break
            if stop_ev.is_set():
                ui(status.set, f"Stopped: {done}/{total} sent")
            else:
                ui(status.set, f"Done: {total} labels sent")
                ui(clear_list)  # finished jobs leave the list so they are not printed twice
        except OSError as e:
            ui(messagebox.showerror, "Error", f"Could not send to the printer ({done} sent so far):\n{e}")
            ui(status.set, f"Error after {done} labels")
        finally:
            ui(set_running, False)

    def on_print():
        if not table.get_children():
            if not add_row():
                return
        elif part_var.get().strip():
            # Something is typed above but the list already has rows: don't silently ignore it.
            answer = messagebox.askyesnocancel(
                "Part not in the list",
                f"{part_var.get().strip()} x {qty_var.get()} is typed above but not in the list.\n\n"
                "Yes: add it to the list and print everything\nNo: print only the list")
            if answer is None or (answer and not add_row()):
                return
        rows = [jobs[item] for item in table.get_children()]
        try:
            fixed = datetime.strptime(date_var.get().strip(), "%Y-%m-%d %H:%M:%S") if fixed_var.get() else None
        except ValueError:
            messagebox.showwarning("Date", "Date format: 2026-10-29 10:43:30")
            return
        if not read_offset():
            return
        total = sum(r[3] for r in rows)
        summary = "\n".join(f"{t}   {part}{'  ' + code if code else ''}   x {qty}" for t, part, code, qty, _ in rows)
        if not messagebox.askyesno("Confirm", f"Print {total} labels?\n\n{summary}"):
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
    PAD, VIEW_W = 14, 420  # margin around the label, preview width in pixels
    pv = ttk.LabelFrame(frm, text="Preview", padding=6)
    pv.grid(row=0, column=3, rowspan=14, sticky="n", padx=(12, 0))
    canvas = tk.Canvas(pv, width=VIEW_W + 2 * PAD, height=240, bg="#d9d9d9", highlightthickness=0)
    canvas.grid()
    ttk.Label(pv, text="Drag the date, part number or code to move it.\n"
                       "Approximate: print 1 test label to confirm.").grid(sticky="w")
    view = {}  # scale and label edges for the current type

    def to_px(x, y):
        return PAD + (x - view["x0"]) * view["s"], PAD + (view["y1"] - y) * view["s"]

    def preview_time():
        if fixed_var.get():
            try:
                return datetime.strptime(date_var.get().strip(), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass
        return datetime.now()

    def draw_preview():
        canvas.delete("all")
        crt["draws"] = crt.get("draws", 0) + 1
        look = THEMES[THEME]  # terminal themes draw the label in their own colors
        paper, ink, edge = (look["field"], look["fg"], look["dim"]) if look else ("white", "black", "#888")
        key = cur()
        t = TEMPLATES[key]
        rx0, rx1, ry0, ry1 = t["rect"]
        base = t["default_offset"]  # the label edge sits where the normal position prints
        view.update(x0=rx0 + base["x"], y1=ry1 + base["y"], s=VIEW_W / (rx1 - rx0))
        s = view["s"]
        cw, ch = VIEW_W + 2 * PAD, int((ry1 - ry0) * s) + 2 * PAD
        canvas.config(width=cw, height=ch)
        x0, y0 = to_px(rx0 + base["x"], ry1 + base["y"])
        x1, y1 = to_px(rx1 + base["x"], ry0 + base["y"])
        canvas.create_rectangle(x0, y0, x1, y1, fill=paper, outline=edge)

        part = part_var.get().strip() or t["sample"]
        code = code_var.get().strip() or "Y0000000"
        option = {"None": 0, "L": 1, "R": 2}[opt_var.get()] if t["has_side"] else 0
        off, elems = OFFSETS[key], ELEMENT_OFFSETS[key]
        for kind, name, x, y, anchor, size, content in t["preview"](part, preview_time(), code, option):
            if not content:
                continue
            ex, ey = elems.get(name, (0, 0))
            x, y = x + off["x"] + ex, y + off["y"] + ey
            tag = ("item", name)
            if kind == "dm":
                matrix = DataMatrix(content).matrix if DataMatrix is not None else [[1] * 18] * 18
                side = len(matrix) * size  # symbol size in dots
                left, top = to_px(x, y + side if anchor == 1 else y)
                cell = size * s
                for r, row in enumerate(matrix):
                    for c, bit in enumerate(row):
                        if bit:
                            canvas.create_rectangle(left + c * cell, top + r * cell, left + (c + 1) * cell,
                                                    top + (r + 1) * cell, fill=ink, width=0, tags=tag)
                # transparent box so the whole symbol can be grabbed
                canvas.create_rectangle(left, top, left + side * s, top + side * s, outline="", fill="",
                                        tags=tag)
            else:
                px, py = to_px(x, y)
                canvas.create_text(px, py, text=content, anchor="sw" if anchor == 1 else "nw", fill=ink,
                                   font=("Arial Narrow", -max(6, int(size * DOTS_PER_PT * s)), "bold"),
                                   tags=tag)

        # Hide whatever falls outside the label, like the printer would
        bg = canvas["bg"]
        for rect in ((0, 0, cw, y0), (0, y1, cw, ch), (0, 0, x0, ch), (x1, 0, cw, ch)):
            canvas.create_rectangle(*rect, fill=bg, width=0)
        canvas.create_rectangle(x0, y0, x1, y1, outline=edge)

        if look:  # retro CRT look: "loading" screen while booting, then scanlines
            left = crt["boot_end"] - time.monotonic()
            if left > 0:
                done = 1 - left / BOOT_SECONDS
                canvas.create_rectangle(x0, y0, x1, y1, fill=look["bg"], outline=edge)
                mx, my = (x0 + x1) / 2, (y0 + y1) / 2
                canvas.create_text(mx, my - 14, text="LOADING LABEL DATA...", fill=ink, font=("Consolas", 11, "bold"))
                cells = 20
                bar = "\u2588" * int(done * cells) + "\u2591" * (cells - int(done * cells))
                canvas.create_text(mx, my + 10, text=f"{bar} {int(done * 100):3d}%", fill=ink,
                                   font=("Consolas", 10))
            for line_y in range(0, ch, 3):
                canvas.create_line(0, line_y, cw, line_y, fill=look["bg"])

    # Drag one item: move it on screen while dragging, save the offset on release.
    drag = {}

    def on_press(event):
        hit = canvas.find_withtag("current")
        tags = canvas.gettags(hit[0]) if hit else ()
        if "item" in tags:
            name = [t for t in tags if t not in ("item", "current")][0]
            drag.update(name=name, x=event.x, y=event.y, x0=event.x, y0=event.y)
            canvas.config(cursor="fleur")

    def on_motion(event):
        if drag.get("name"):
            canvas.move(drag["name"], event.x - drag["x"], event.y - drag["y"])
            drag.update(x=event.x, y=event.y)

    def on_release(event):
        name = drag.pop("name", None)
        canvas.config(cursor="")
        if not name:
            return
        dx = round((event.x - drag["x0"]) / view["s"])
        dy = round((drag["y0"] - event.y) / view["s"])  # screen y goes down, printer y goes up
        if dx or dy:
            ex, ey = ELEMENT_OFFSETS[cur()].get(name, (0, 0))
            ELEMENT_OFFSETS[cur()][name] = [ex + dx, ey + dy]
            save_settings()
        describe_position()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_motion)
    canvas.bind("<ButtonRelease-1>", on_release)

    preview_hooks.append(draw_preview)
    for var in (part_var, code_var, opt_var, fixed_var, date_var):
        var.trace_add("write", lambda *_: draw_preview())
    type_var.trace_add("write", on_type_change)
    on_type_change()

    def tick():
        if not fixed_var.get() and not drag.get("name"):
            draw_preview()
        root.after(1000, tick)

    # --- Themes ---
    style = ttk.Style(root)
    normal_theme = style.theme_use()
    style.configure("Dim.TLabel", foreground="#666")

    def apply_theme(*_):
        global THEME
        THEME = theme_var.get()
        c = THEMES[THEME]
        if c is None:
            style.theme_use(normal_theme)
            root.configure(bg=style.lookup("TFrame", "background") or "SystemButtonFace")
            canvas.config(bg="#d9d9d9")
            banner.grid_remove()
        else:
            bg, fg, dim, field, sel = c["bg"], c["fg"], c["dim"], c["field"], c["select"]
            font = ("Consolas", 10)
            style.theme_use("clam")
            style.configure(".", background=bg, foreground=fg, font=font, bordercolor=dim, lightcolor=bg,
                            darkcolor=bg, troughcolor=field, focuscolor=fg, insertcolor=fg,
                            fieldbackground=field, selectbackground=sel, selectforeground=fg, arrowcolor=fg)
            style.map(".", background=[("disabled", bg)], foreground=[("disabled", dim)])
            style.configure("TButton", background=bg, foreground=fg, bordercolor=fg, padding=(6, 2))
            style.map("TButton", background=[("pressed", sel), ("active", sel), ("disabled", bg)],
                      foreground=[("disabled", dim)])
            for w in ("TEntry", "TCombobox", "TSpinbox"):
                style.configure(w, fieldbackground=field, foreground=fg, background=bg)
                style.map(w, fieldbackground=[("readonly", field), ("disabled", bg)],
                          foreground=[("disabled", dim)], selectbackground=[("readonly", sel)])
            style.configure("TCheckbutton", indicatorbackground=field, indicatorforeground=fg)
            style.map("TCheckbutton", background=[("active", bg)])
            style.configure("Treeview", background=field, fieldbackground=field, foreground=fg)
            style.map("Treeview", background=[("selected", sel)], foreground=[("selected", fg)])
            style.configure("Treeview.Heading", background=bg, foreground=fg, font=font)
            style.map("Treeview.Heading", background=[("active", sel)])
            style.configure("TLabelframe.Label", foreground=fg)
            style.configure("Horizontal.TProgressbar", background=fg, troughcolor=field)
            style.configure("Dim.TLabel", foreground=dim)
            style.configure("Banner.TLabel", foreground=fg, font=("Consolas", 12, "bold"))
            root.configure(bg=bg)
            root.option_add("*TCombobox*Listbox.background", field)
            root.option_add("*TCombobox*Listbox.foreground", fg)
            root.option_add("*TCombobox*Listbox.selectBackground", sel)
            canvas.config(bg=bg)
            banner.grid(row=0, column=0, sticky="w")
        save_settings()
        if c is not None:
            start_boot()
        else:
            crt["boot_end"] = 0
            draw_preview()

    BOOT_LINES = ["> INITIALIZING TERMINAL...", "> LOADING LABEL TYPES A / B / C...",
                  "> CONNECTING TO PRINTER...", "> READY."]

    def start_boot():
        crt["boot_end"] = time.monotonic() + BOOT_SECONDS
        boot_step()

    def boot_step():
        left = crt["boot_end"] - time.monotonic()
        if left > 0 and THEMES[THEME]:
            draw_preview()
            root.after(80, boot_step)
        else:
            draw_preview()

    def blink(on=[True]):
        on[0] = not on[0]
        cursor = "_" if on[0] else " "
        left = crt["boot_end"] - time.monotonic()
        if left > 0:
            step = min(len(BOOT_LINES) - 1, int((1 - left / BOOT_SECONDS) * len(BOOT_LINES)))
            banner_var.set(BOOT_LINES[step] + " " + cursor)
        else:
            banner_var.set("> LABEL REPRINT TERMINAL  //  CREATED BY JAIME " + cursor)
        root.after(250 if left > 0 else 500, blink)

    def glitch():
        """Now and then jitter the preview and banner for a moment, like a worn-out monitor."""
        if THEMES[THEME] and not drag.get("name") and crt["boot_end"] < time.monotonic():
            dx, draws = random.choice((-6, -4, 4, 6)), crt.get("draws")
            canvas.move("item", dx, 0)
            text = banner_var.get()
            garbled = "".join(random.choice("#%&@$*") if ch != " " and random.random() < 0.15 else ch
                              for ch in text)
            banner_var.set(garbled)

            def restore():
                if crt.get("draws") == draws:  # not redrawn meanwhile
                    canvas.move("item", -dx, 0)
                if banner_var.get() == garbled:
                    banner_var.set(text)
            root.after(90, restore)
        root.after(random.randint(2500, 7000), glitch)

    theme_var.trace_add("write", apply_theme)
    apply_theme()
    blink()
    root.after(3000, glitch)

    tick()
    if selftest:  # CI check: build the window, try every label type and control, then close
        def fail(*exc):
            import traceback
            traceback.print_exception(*exc)
            os._exit(1)
        root.report_callback_exception = fail

        class Ev:
            def __init__(self, x, y):
                self.x, self.y = x, y

        def fake_drag():
            name = [t for t in canvas.gettags(canvas.find_withtag("item")[-1]) if t != "item"][0]
            drag.update(name=name, x=50, y=50, x0=50, y0=50)  # as if on_press hit that item
            on_motion(Ev(60, 40))
            on_release(Ev(60, 40))
            assert ELEMENT_OFFSETS[cur()].get(name), "drag did not save an offset"

        steps = [lambda: move(1, 0), lambda: move(0, -1), reset_position, lambda: opt_var.set("L"),
                 lambda: fixed_var.set(True), lambda: part_var.set("12345678")]
        for name in type_names:
            steps += [lambda n=name: type_var.set(n), lambda: code_var.set("Y0124069"), fake_drag,
                      reset_position]
        steps += [lambda n=n: theme_var.set(n) for n in list(THEMES)[1:] + list(THEMES)[:1]]
        for i, fn in enumerate(steps):
            root.after(100 + 50 * i, fn)
        root.after(300 + 50 * len(steps), root.destroy)
    root.mainloop()


if __name__ == "__main__":
    load_settings()
    if sys.argv[1:] == ["--selftest"]:
        gui(selftest=True)
    elif len(sys.argv) >= 2:
        args = sys.argv[1:] + [""] * 3
        print_labels(args[0], int(args[1] or 1), template=(args[2] or DEFAULT_TEMPLATE).upper(), code=args[3])
    else:
        gui()
