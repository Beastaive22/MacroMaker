"""Macro Maker - simple key/mouse macro tool for Windows.
Setup:  pip install pynput
Run:    python macro_maker.py
"""
import ctypes, ctypes.wintypes, json, os, subprocess, threading, time, tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
from pynput import keyboard as pk, mouse as pm

# Settings live in %APPDATA%\MacroMaker, not next to the script: inside an exe build
# that folder is a temp folder Windows deletes when the app closes.
FILE = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "MacroMaker", "macros.json")
os.makedirs(os.path.dirname(FILE), exist_ok=True)
U = 34


def L(s):
    return " ".join(f"{c}:{ord(c):X}" for c in s)


# Keyboard layout. Token = label:hexVirtualKey[:width]   "_n" = gap of n keys
ROWS = [
    "Esc:1B _1 F1:70 F2:71 F3:72 F4:73 _.5 F5:74 F6:75 F7:76 F8:77 _.5 F9:78 F10:79 F11:7A F12:7B _.5 PrtSc:2C ScrLk:91 Pause:13",
    "`:C0 " + L("1234567890") + " -:BD =:BB Bksp:08:2 _.5 Ins:2D Home:24 PgUp:21 _.5 NumLk:90 Num/:6F Num*:6A Num-:6D",
    "Tab:09:1.5 " + L("QWERTYUIOP") + " [:DB ]:DD \\:DC:1.5 _.5 Del:2E End:23 PgDn:22 _.5 Num7:67 Num8:68 Num9:69 Num+:6B",
    "Caps:14:1.75 " + L("ASDFGHJKL") + " ;:BA ':DE Enter:0D:2.25 _.5 _3 _.5 Num4:64 Num5:65 Num6:66",
    "LShift:A0:2.25 " + L("ZXCVBNM") + " ,:BC .:BE /:BF RShift:A1:2.75 _.5 _1 Up:26 _1 _.5 Num1:61 Num2:62 Num3:63",
    "LCtrl:A2:1.25 LWin:5B:1.25 LAlt:A4:1.25 Space:20:6.25 RAlt:A5:1.25 RWin:5C:1.25 Menu:5D:1.25 RCtrl:A3:1.25 _.5 Left:25 Down:28 Right:27 _.5 Num0:60:2 Num.:6E",
]

NAMES = {}
for _r in ROWS:
    for _t in _r.split():
        if _t[0] != "_":
            _p = _t.split(":")
            NAMES[_p[0]] = int(_p[1], 16)
NAMES.update({"VolMute": 0xAD, "VolDown": 0xAE, "VolUp": 0xAF, "NextTrack": 0xB0,
              "PrevTrack": 0xB1, "MediaStop": 0xB2, "PlayPause": 0xB3})
LOWER = {k.lower(): v for k, v in NAMES.items()}
LOWER.update({"ctrl": 0xA2, "shift": 0xA0, "alt": 0xA4, "win": 0x5B})
BTN = {"mouseleft": pm.Button.left, "mouseright": pm.Button.right, "mousemiddle": pm.Button.middle,
       "mouseback": pm.Button.x1, "mouseforward": pm.Button.x2}
MOUSE_NAMES = ["MouseLeft", "MouseRight", "MouseMiddle", "MouseBack", "MouseForward"]
KEYS = list(NAMES) + MOUSE_NAMES



def valid(n):
    n = n.lower()
    return n in LOWER or n in BTN


VKNAME = {v: k for k, v in NAMES.items()}
MB = {0x201: ("left", 1), 0x202: ("left", 0), 0x204: ("right", 1), 0x205: ("right", 0),
      0x207: ("middle", 1), 0x208: ("middle", 0)}


def own_focus():
    """True when this app's own window is in front (we never block input there)."""
    u = ctypes.windll.user32
    pid = ctypes.c_ulong()
    u.GetWindowThreadProcessId(u.GetForegroundWindow(), ctypes.byref(pid))
    return pid.value == os.getpid()


class Recorder:
    """Records real key/mouse presses (and timing) into a list of macro steps."""
    def __init__(s, out, timing, skip=0):
        s.out, s.timing, s.last, s.down, s.skip = out, timing, None, set(), skip
        s.kl = s.ml = None

    def ev(s, n, down):
        if down:
            if n in s.down:
                return
            s.down.add(n)
        else:
            if n not in s.down:
                return
            s.down.discard(n)
        now = time.perf_counter()
        if s.timing and s.last is not None and int((now - s.last) * 1000) >= 10:
            s.out.append({"t": "delay", "v": str(int((now - s.last) * 1000))})
        s.last = now
        s.out.append({"t": "down" if down else "up", "v": n})

    def kf(s, msg, d):
        if not d.flags & 0x10 and msg in (0x100, 0x101, 0x104, 0x105) and d.vkCode in VKNAME:
            s.ev(VKNAME[d.vkCode], msg in (0x100, 0x104))
        return False

    def over(s):
        """True while the mouse is over the Record/Stop button."""
        if not s.skip:
            return False
        u, r, p = ctypes.windll.user32, ctypes.wintypes.RECT(), ctypes.wintypes.POINT()
        u.GetCursorPos(ctypes.byref(p))
        u.GetWindowRect(ctypes.c_void_p(s.skip), ctypes.byref(r))
        return r.left <= p.x < r.right and r.top <= p.y < r.bottom

    def mf(s, msg, d):
        if d.flags & 1:
            return False
        if msg in MB or msg in (0x20B, 0x20C):
            if msg in MB:
                n, down = "Mouse" + MB[msg][0].capitalize(), MB[msg][1]
            else:
                n = "MouseBack" if (d.mouseData >> 16) & 0xFFFF == 1 else "MouseForward"
                down = msg == 0x20B
            if not (down and s.over()):  # releases are always kept so nothing gets stuck
                s.ev(n, down)
        elif msg == 0x20A and not s.over():
            v = (d.mouseData >> 16) & 0xFFFF
            v = v - 0x10000 if v >= 0x8000 else v
            now = time.perf_counter()
            if s.timing and s.last is not None and int((now - s.last) * 1000) >= 10:
                s.out.append({"t": "delay", "v": str(int((now - s.last) * 1000))})
            s.last = now
            s.out.append({"t": "scroll", "v": "up" if v > 0 else "down"})
        return False

    def start(s):
        s.kl = pk.Listener(win32_event_filter=s.kf)
        s.ml = pm.Listener(win32_event_filter=s.mf)
        s.kl.start(); s.ml.start()

    def stop(s):
        for l in (s.kl, s.ml):
            if l:
                l.stop()


class Engine:
    def __init__(s):
        s.b, s.down, s.runs = {}, set(), {}
        s.kb, s.ms = pk.Controller(), pm.Controller()
        s.kl = s.ml = None

    # ---- output ----
    def key(s, name, down):
        n = name.lower()
        if n in BTN:
            (s.ms.press if down else s.ms.release)(BTN[n])
        elif n in LOWER:
            (s.kb.press if down else s.kb.release)(pk.KeyCode.from_vk(LOWER[n]))

    def combo(s, text):
        parts = [p.strip() for p in text.split("+") if p.strip()]
        for p in parts:
            s.key(p, True)
        for p in reversed(parts):
            s.key(p, False)

    def step(s, st, stop, held):
        t, v = st["t"], st["v"]
        if t in ("tap", "click"):
            s.key(v, True); s.key(v, False)
        elif t == "down":
            s.key(v, True); held.add(v)
        elif t == "up":
            s.key(v, False); held.discard(v)
        elif t == "scroll":
            s.ms.scroll(0, 1 if v == "up" else -1)
        elif t == "delay":
            stop.wait(int(v) / 1000)
        elif t == "text":
            s.kb.type(v)
        elif t == "app":
            subprocess.Popen(v, shell=True)

    def run(s, steps, stop, held):
        for st in steps:
            if stop.is_set():
                return
            try:
                s.step(st, stop, held)
            except Exception:
                pass

    def loop(s, steps, stop, held):
        while not stop.is_set():
            if steps:
                s.run(steps, stop, held)
            stop.wait(0.001 if steps else 0.05)

    def macro(s, b, stop):
        held, never, st, m = set(), threading.Event(), b["steps"], b["mode"]
        try:
            if m == "once":
                s.run(st["main"], never, held)
            elif m == "seq":
                s.run(st["press"], never, held)
                s.loop(st["hold"], stop, held)
                s.run(st["release"], never, held)
            else:
                s.loop(st["main"], stop, held)
        finally:
            for n in list(held):
                s.key(n, False)

    # ---- triggers ----
    def press_macro(s, tid, b):
        r = s.runs.get(tid)
        alive = r and r[1].is_alive()
        if b["mode"] == "toggle" and alive:
            r[0].set(); return
        if alive:
            return
        stop = threading.Event()
        th = threading.Thread(target=s.macro, args=(b, stop), daemon=True)
        s.runs[tid] = (stop, th)
        th.start()

    def event(s, tid, down):
        b = s.b[tid]; t = b["type"]
        if down:
            if tid in s.down:
                return  # ignore key auto-repeat
            s.down.add(tid)
            if t == "key":
                s.key(b["v"], True)
            elif t == "command":
                s.combo(b["v"])
            elif t == "macro":
                s.press_macro(tid, b)
        else:
            s.down.discard(tid)
            if t == "key":
                s.key(b["v"], False)
            elif t == "macro" and b["mode"] in ("hold", "seq") and tid in s.runs:
                s.runs[tid][0].set()

    # ---- Windows hooks ----
    def kf(s, msg, d):
        if d.flags & 0x10 or msg not in (0x100, 0x101, 0x104, 0x105):
            return True
        tid = f"k:{d.vkCode}"
        if tid in s.b and (tid in s.down or not own_focus()):
            s.event(tid, msg in (0x100, 0x104))
            s.kl.suppress_event()
        return True

    def mf(s, msg, d):
        if d.flags & 1:
            return True
        if msg in MB:
            n, down = MB[msg]
        elif msg in (0x20B, 0x20C):
            n = "back" if (d.mouseData >> 16) & 0xFFFF == 1 else "forward"
            down = msg == 0x20B
        else:
            return True
        tid = "m:" + n
        if tid in s.b and (tid in s.down or not own_focus()):
            s.event(tid, down)
            s.ml.suppress_event()
        return True

    def start(s):
        s.kl = pk.Listener(win32_event_filter=s.kf)
        s.ml = pm.Listener(win32_event_filter=s.mf)
        s.kl.start(); s.ml.start()

    def stop(s):
        for l in (s.kl, s.ml):
            if l:
                l.stop()
        s.kl = s.ml = None
        for stop, _ in s.runs.values():
            stop.set()
        s.down.clear()


MODE_INFO = [
    ("once", "Run once", "Plays the steps one time each time you press the button."),
    ("hold", "Repeat while holding", "Keeps repeating while you hold the button. Stops when you let go."),
    ("toggle", "Toggle on / off", "Press once to start repeating. Press again to stop."),
    ("seq", "Sequence", "Different steps for pressing, holding, and letting go."),
]
MODE_NAME = {c: t for c, t, _ in MODE_INFO}
SECS = [("main", "Steps"), ("press", "When pressed"), ("hold", "While held (repeats)"), ("release", "When released")]
STEP_INFO = [
    ("tap", "Press & release a key", "Pick a key from the list (or type its name)."),
    ("down", "Hold a key down", "Pick the key to hold. Add a 'Let go of a key' step later to release it."),
    ("up", "Let go of a key", "Pick the key to let go of."),
    ("click", "Click a mouse button", "Pick which mouse button to click."),
    ("scroll", "Scroll the mouse wheel", "Pick up or down."),
    ("delay", "Wait (delay)", "How many milliseconds to wait. 1000 = 1 second."),
    ("text", "Type text", "The text or emojis to type."),
    ("app", "Open a program", "Full path to a program, like C:\\Windows\\notepad.exe"),
]
STEP_LABEL = {c: l for c, l, _ in STEP_INFO}
STEP_CODE = {l: c for c, l, _ in STEP_INFO}
STEP_HINT = {c: h for c, _, h in STEP_INFO}
FRIENDLY = {"m:left": "Left mouse button", "m:right": "Right mouse button",
            "m:middle": "Middle mouse button (wheel click)",
            "m:forward": "Side button: Forward", "m:back": "Side button: Back"}
TIP = "Hover over a key or mouse button to see what it does. Click it to set it up."


def describe(x):
    t, v = x["t"], x["v"]
    return {"tap": f"Press & release   {v}", "down": f"Hold down   {v}", "up": f"Let go of   {v}",
            "click": f"Click   {v}", "scroll": f"Scroll {v}", "delay": f"Wait   {v} ms",
            "text": f"Type text:   {v}", "app": f"Open program:   {v}"}[t]


def tname(tid):
    return FRIENDLY.get(tid) or "Key " + VKNAME.get(int(tid[2:]), tid)


def summary(b):
    if b["type"] == "key":
        return "Acts as " + b["v"]
    if b["type"] == "command":
        return "Shortcut: " + b["v"]
    n = sum(len(v) for v in b["steps"].values())
    return f"Macro: {MODE_NAME[b['mode']]} ({n} steps)"


def clean_tid(tid):
    return isinstance(tid, str) and (tid in FRIENDLY or (tid.startswith("k:") and tid[2:].isdigit()))


def clean_steps(raw):
    out = []
    for x in raw if isinstance(raw, list) else []:
        if not (isinstance(x, dict) and x.get("t") in STEP_LABEL and isinstance(x.get("v"), (str, int))):
            continue
        t, v = x["t"], str(x["v"])
        if t == "delay" and not v.isdigit():
            continue
        if t in ("tap", "down", "up", "click") and not valid(v):
            continue
        out.append({"t": t, "v": v})
    return out


def clean_binding(b):
    """Safe copy of an assignment, or None if it is broken."""
    if not isinstance(b, dict):
        return None
    t, v = b.get("type"), str(b.get("v", "")).strip()
    if t == "key" and valid(v):
        return {"type": "key", "v": v}
    if t == "command" and v and all(valid(p.strip()) for p in v.split("+")):
        return {"type": "command", "v": v}
    if t == "macro" and b.get("mode") in MODE_NAME and isinstance(b.get("steps"), dict):
        return {"type": "macro", "mode": b["mode"], "steps": {k: clean_steps(b["steps"].get(k, [])) for k, _ in SECS}}
    return None


class App:
    def __init__(s, root):
        s.root, s.eng, s.rects, s.on, s.lib = root, Engine(), {}, False, {}
        s.profiles, s.cur_name = {"Default": {}}, "Default"
        try:
            data = json.load(open(FILE))
            if "profiles" in data:
                s.profiles, s.lib = data["profiles"], data.get("library", {})
                s.cur_name = data.get("current") if data.get("current") in s.profiles else next(iter(s.profiles))
            elif "bindings" in data:
                s.profiles["Default"], s.lib = data["bindings"], data.get("library", {})
            else:
                s.profiles["Default"] = data
        except Exception:
            pass
        if not s.profiles or s.cur_name not in s.profiles:
            s.profiles, s.cur_name = {"Default": {}}, "Default"
        s.eng.b = s.profiles[s.cur_name]
        root.title("Macro Maker")
        top = ttk.Frame(root, padding=(12, 10, 12, 4))
        top.grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(top, text="Macro Maker", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(top, text="Step 1: click a key or mouse button.    Step 2: choose what it should do.    "
                  "Step 3: click the green Turn ON button.").pack(anchor="w")
        s.kc = tk.Canvas(root, width=23 * U + 20, height=int(7.05 * U) + 20, bg="#1b1b1b", highlightthickness=0)
        s.kc.grid(row=1, column=0, columnspan=2)
        for r, spec in enumerate(ROWS):
            x, y = 10, 10 + (r * 1.15 + (0.3 if r else 0)) * U
            for t in spec.split():
                if t[0] == "_":
                    x += float(t[1:]) * U; continue
                p = t.split(":"); w = float(p[2]) if len(p) > 2 else 1
                s.cell(s.kc, "k:%d" % int(p[1], 16), p[0], x, y, w * U - 3, U - 3)
                x += w * U
        lg = ttk.Frame(root, padding=(12, 4)); lg.grid(row=2, column=0, columnspan=2, sticky="w")
        tk.Label(lg, text=" Green = assigned ", bg="#2e8b57", fg="white").pack(side="left")
        tk.Label(lg, text=" Gray = empty ", bg="#333", fg="white").pack(side="left", padx=6)
        s.tip = ttk.Label(lg, text=TIP)
        s.tip.pack(side="left", padx=10)

        mf = ttk.Frame(root, padding=(12, 0)); mf.grid(row=3, column=0, sticky="n")
        ttk.Label(mf, text="Mouse", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        mc = tk.Canvas(mf, width=250, height=225, bg="#1b1b1b", highlightthickness=0)
        mc.pack()
        mc.create_oval(30, 4, 240, 222, outline="#555")
        for tid, lab, (x1, y1, x2, y2) in [
                ("m:left", "Left\nclick", (45, 18, 114, 125)), ("m:right", "Right\nclick", (156, 18, 225, 125)),
                ("m:middle", "Wheel", (118, 30, 152, 95)),
                ("m:forward", "Side\nForward", (4, 132, 62, 168)), ("m:back", "Side\nBack", (4, 174, 62, 210))]:
            s.cell(mc, tid, lab, x1, y1, x2 - x1, y2 - y1)

        pf = ttk.Frame(root, padding=(12, 0, 12, 10)); pf.grid(row=3, column=1, sticky="nsew")
        row = ttk.Frame(pf); row.pack(fill="x")
        s.btn = tk.Button(row, text="Turn ON", command=s.toggle, bg="#2e8b57", fg="white",
                          font=("Segoe UI", 12, "bold"), width=12)
        s.btn.pack(side="left")
        s.st = tk.Label(row, text="OFF: your keys and mouse work normally", fg="#777", font=("Segoe UI", 10, "bold"))
        s.st.pack(side="left", padx=12)
        pr = ttk.LabelFrame(pf, text=" Profile ", padding=6)
        pr.pack(fill="x", pady=(8, 0))
        s.pv = tk.StringVar()
        s.pcb = ttk.Combobox(pr, textvariable=s.pv, state="readonly", width=22)
        s.pcb.pack(side="left")
        s.pcb.bind("<<ComboboxSelected>>", lambda e: s.switch(s.pv.get()))
        for text, cmd in [("New", s.new_profile), ("Rename", s.rename_profile), ("Delete", s.delete_profile)]:
            ttk.Button(pr, text=text, command=cmd, width=8).pack(side="left", padx=2)
        sh = ttk.LabelFrame(pf, text=" Share with others  (Export = save a file to send, Import = add a file you got) ", padding=6)
        sh.pack(fill="x", pady=4)
        for text, ex, im in [("Whole profile (buttons + macros):", s.export_profile, s.import_profile),
                             ("Only my saved macros:", s.export_macros, s.import_macros)]:
            r = ttk.Frame(sh); r.pack(fill="x", pady=1)
            ttk.Label(r, text=text, width=32).pack(side="left")
            ttk.Button(r, text="Export", command=ex, width=9).pack(side="left", padx=2)
            ttk.Button(r, text="Import", command=im, width=9).pack(side="left", padx=2)
        ttk.Label(pf, text="Assignments in this profile (double-click one to change it):").pack(anchor="w", pady=(6, 2))
        s.tree = ttk.Treeview(pf, columns=("b", "w"), show="headings", height=5)
        s.tree.heading("b", text="Button"); s.tree.heading("w", text="What it does")
        s.tree.column("b", width=210); s.tree.column("w", width=300)
        s.tree.pack(fill="both")
        s.tree.bind("<Double-1>", s.tree_edit)
        root.protocol("WM_DELETE_WINDOW", s.close)
        s.refresh()

    def tree_edit(s, e):
        i = s.tree.identify_row(e.y)
        if i:
            s.edit(i)

    def cell(s, cv, tid, label, x, y, w, h):
        r = cv.create_rectangle(x, y, x + w, y + h, outline="#666", tags=tid)
        cv.create_text(x + w / 2, y + h / 2, text=label, fill="white", justify="center",
                       font=("Segoe UI", 8 if w > 30 else 7), tags=tid)
        s.rects[tid] = (cv, r)
        cv.tag_bind(tid, "<Button-1>", lambda e: s.edit(tid))
        cv.tag_bind(tid, "<Enter>", lambda e: s.hover(tid))
        cv.tag_bind(tid, "<Leave>", lambda e: s.hover(None))

    def hover(s, tid):
        if tid is None:
            s.tip["text"] = TIP
        else:
            b = s.eng.b.get(tid)
            s.tip["text"] = f"{tname(tid)}:  " + (summary(b) if b else "nothing assigned yet (click to set up)")

    def refresh(s):
        s.pcb["values"] = sorted(s.profiles); s.pv.set(s.cur_name)
        s.root.title("Macro Maker - " + s.cur_name)
        for tid, (cv, r) in s.rects.items():
            cv.itemconfig(r, fill="#2e8b57" if tid in s.eng.b else "#333")
        s.tree.delete(*s.tree.get_children())
        for tid in sorted(s.eng.b, key=tname):
            s.tree.insert("", "end", iid=tid, values=(tname(tid), summary(s.eng.b[tid])))

    def commit(s):
        with open(FILE, "w") as fh:
            json.dump({"profiles": s.profiles, "current": s.cur_name, "library": s.lib}, fh, indent=1)
        s.refresh()

    def toggle(s):
        s.eng.stop() if s.on else s.eng.start()
        s.on = not s.on
        s.btn.config(text="Turn OFF" if s.on else "Turn ON", bg="#c0392b" if s.on else "#2e8b57")
        s.st.config(text="ON: your macros are active (this window is never blocked)" if s.on
                    else "OFF: your keys and mouse work normally", fg="#2e8b57" if s.on else "#777")

    def close(s):
        s.eng.stop(); s.root.destroy()

    # ------------------------------------------------------------- profiles
    def switch(s, name):
        for stop, _ in s.eng.runs.values():
            stop.set()
        s.eng.down.clear()
        s.cur_name, s.eng.b = name, s.profiles[name]
        s.commit()

    def ask_name(s, title, first=""):
        n = simpledialog.askstring(title, "Profile name:", initialvalue=first, parent=s.root)
        n = (n or "").strip()[:30]
        if n and n != first and n in s.profiles:
            messagebox.showerror("Name taken", f"A profile called '{n}' already exists.")
            return ""
        return n

    def new_profile(s):
        n = s.ask_name("New profile")
        if n:
            s.profiles[n] = {}; s.switch(n)

    def rename_profile(s):
        n = s.ask_name("Rename profile", s.cur_name)
        if n and n != s.cur_name:
            s.profiles = {(n if k == s.cur_name else k): v for k, v in s.profiles.items()}
            s.cur_name = n; s.commit()

    def delete_profile(s):
        if len(s.profiles) < 2:
            return messagebox.showinfo("Can't delete", "You need at least one profile.")
        if messagebox.askyesno("Delete profile", f"Delete the profile '{s.cur_name}' and all its assignments?"):
            del s.profiles[s.cur_name]
            s.switch(next(iter(s.profiles)))

    # ------------------------------------------------------------- sharing
    def save_file(s, kind, name, payload, what):
        safe = "".join(c for c in name if c.isalnum() or c in " -_") or "macros"
        p = filedialog.asksaveasfilename(title="Save " + what, defaultextension=".json",
                                         initialfile=f"{safe}.{kind}.json", filetypes=[("Macro Maker file", "*.json")])
        if p:
            with open(p, "w", encoding="utf-8") as fh:
                json.dump({"app": "Macro Maker", "type": kind, **payload}, fh, indent=1)
            messagebox.showinfo("Saved", f"Saved {what} to:\n{p}\n\nSend this file to anyone. They can use Import.")

    def export_profile(s):
        s.save_file("profile", s.cur_name, {"name": s.cur_name, "bindings": s.eng.b, "library": s.lib}, "your profile")

    def export_macros(s):
        if not s.lib:
            return messagebox.showinfo("No saved macros", "You have no saved macros yet.\n"
                                       "Open a macro and use 'Save this macro for later as'.")
        s.save_file("macros", "macros", {"library": s.lib}, "your saved macros")

    def load_file(s, kind):
        p = filedialog.askopenfilename(title="Choose a Macro Maker file",
                                       filetypes=[("Macro Maker file", "*.json"), ("All files", "*.*")])
        if not p:
            return None
        try:
            with open(p, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            data = None
        if not isinstance(data, dict) or data.get("app") != "Macro Maker":
            messagebox.showerror("Not a Macro Maker file", "That file isn't a Macro Maker profile or macro pack.")
        elif data.get("type") != kind:
            other = ("macro pack. Use Import next to 'Only my saved macros'." if data.get("type") == "macros"
                     else "profile. Use Import next to 'Whole profile'.")
            messagebox.showerror("Wrong kind of file", "This file is a " + other)
        else:
            return data
        return None

    def vet(s, bindings, library):
        """Clean imported data and ask before keeping any 'Open a program' steps."""
        cb, cl = {}, {}
        for t, b in (bindings if isinstance(bindings, dict) else {}).items():
            c = clean_binding(b)
            if c and clean_tid(t):
                cb[t] = c
        for n, m in (library if isinstance(library, dict) else {}).items():
            c = clean_binding({"type": "macro", **m}) if isinstance(m, dict) else None
            if c:
                cl[str(n)[:40]] = {"mode": c["mode"], "steps": c["steps"]}
        lists = [c["steps"] for c in cb.values() if c["type"] == "macro"] + [m["steps"] for m in cl.values()]
        apps = [x["v"] for st in lists for part in st.values() for x in part if x["t"] == "app"]
        if apps:
            shown = "\n".join("  " + a[:80] for a in sorted(set(apps))[:8])
            r = messagebox.askyesnocancel(
                "Programs inside this file",
                f"This file has {len(apps)} 'Open a program' step(s):\n\n{shown}\n\n"
                "These would start programs on your computer. Only keep them if you trust whoever sent this file.\n\n"
                "Yes = keep them\nNo = remove those steps\nCancel = don't import")
            if r is None:
                return None
            if r is False:
                for st in lists:
                    for k in st:
                        st[k] = [x for x in st[k] if x["t"] != "app"]
        return cb, cl

    def merge_lib(s, cl):
        n = 0
        for name, m in cl.items():
            if s.lib.get(name) == m:
                continue
            new, i = name, 2
            while new in s.lib:
                new = f"{name} ({i})"; i += 1
            s.lib[new] = m; n += 1
        return n

    def import_profile(s):
        data = s.load_file("profile")
        v = data and s.vet(data.get("bindings"), data.get("library"))
        if v:
            cb, cl = v
            base = str(data.get("name") or "Imported")[:30]
            name, i = base, 2
            while name in s.profiles:
                name = f"{base} ({i})"; i += 1
            s.profiles[name] = cb
            n = s.merge_lib(cl)
            s.switch(name)
            messagebox.showinfo("Profile imported", f"Added the profile '{name}' with {len(cb)} assignment(s) "
                                f"and {n} saved macro(s).\nIt is now selected.")

    def import_macros(s):
        data = s.load_file("macros")
        v = data and s.vet(None, data.get("library"))
        if v:
            n = s.merge_lib(v[1]); s.commit()
            messagebox.showinfo("Macros imported", f"Added {n} saved macro(s).\n"
                                "Find them under 'Use a saved macro' in the macro editor.")

    # ------------------------------------------------------------------ editor
    def edit(s, tid):
        name, b = tname(tid), s.eng.b.get(tid, {})
        d = tk.Toplevel(s.root); d.title("Set up: " + name); d.grab_set(); d.resizable(False, False)
        st = {k: [dict(x) for x in v] for k, v in b.get("steps", {}).items()}
        for k, _ in SECS:
            st.setdefault(k, [])
        cat = tk.StringVar(value=b.get("type", "key"))
        mode = tk.StringVar(value=b.get("mode", "once"))
        sec = tk.StringVar(value="press" if b.get("mode") == "seq" else "main")
        tim = tk.BooleanVar(value=True)
        rec = {"r": None}

        ttk.Label(d, text=name, font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=12, pady=(10, 2))
        ttk.Label(d, text="What should this button do?").pack(anchor="w", padx=12)
        box = ttk.Frame(d); box.pack(fill="x", padx=12, pady=4)
        for val, title, desc in [
                ("key", "Act as another key or mouse button", "Example: make this button work like the letter E."),
                ("command", "Press a shortcut", "Example: ctrl+c (copy) or ctrl+shift+s."),
                ("macro", "Run a macro (a list of steps)", "Example: auto-click, type a message, key combos with waits.")]:
            f = ttk.Frame(box); f.pack(fill="x")
            ttk.Radiobutton(f, text=title, value=val, variable=cat, width=34).pack(side="left")
            ttk.Label(f, text=desc, foreground="#666").pack(side="left")
        ttk.Separator(d).pack(fill="x", padx=12, pady=6)
        body = ttk.Frame(d); body.pack(fill="x", padx=12)

        # --- Key ---
        fk = ttk.Frame(body)
        kv = tk.StringVar(value=b.get("v", "") if b.get("type") == "key" else "")
        ttk.Label(fk, text="Send this key or mouse button instead (pick from the list):").pack(anchor="w")
        ttk.Combobox(fk, textvariable=kv, values=KEYS, width=26).pack(anchor="w", pady=4)

        # --- Command ---
        fc = ttk.Frame(body)
        cv = tk.StringVar(value=b.get("v", "") if b.get("type") == "command" else "")
        ttk.Label(fc, text="Type the shortcut. Join keys with +   Examples: ctrl+c   ctrl+shift+s   alt+Tab   win+d",
                  ).pack(anchor="w")
        ttk.Entry(fc, textvariable=cv, width=34).pack(anchor="w", pady=4)

        # --- Macro ---
        fm = ttk.Frame(body)
        libv, nm = tk.StringVar(), tk.StringVar()
        lf = ttk.LabelFrame(fm, text=" Saved macros ", padding=6); lf.pack(fill="x")
        r = ttk.Frame(lf); r.pack(fill="x")
        ttk.Label(r, text="Use a saved macro:").pack(side="left")
        lcb = ttk.Combobox(r, textvariable=libv, values=sorted(s.lib), state="readonly", width=20)
        lcb.pack(side="left", padx=6)
        ttk.Button(r, text="Delete it", command=lambda: ldel()).pack(side="left")
        r = ttk.Frame(lf); r.pack(fill="x", pady=(4, 0))
        ttk.Label(r, text="Save this macro for later as:").pack(side="left")
        ttk.Entry(r, textvariable=nm, width=20).pack(side="left", padx=6)
        ttk.Button(r, text="Save to list", command=lambda: lsave()).pack(side="left")

        wf = ttk.LabelFrame(fm, text=" When should it run? ", padding=6); wf.pack(fill="x", pady=4)
        for code, title, desc in MODE_INFO:
            f = ttk.Frame(wf); f.pack(fill="x")
            ttk.Radiobutton(f, text=title, value=code, variable=mode, width=22).pack(side="left")
            ttk.Label(f, text=desc, foreground="#666").pack(side="left")
        slot = ttk.Frame(fm); slot.pack(fill="x")
        rs = ttk.Frame(slot)
        ttk.Label(rs, text="Which part are you editing?").pack(side="left")
        for code, lab in SECS[1:]:
            ttk.Radiobutton(rs, text=lab, value=code, variable=sec).pack(side="left", padx=6)

        sf = ttk.LabelFrame(fm, text=" Steps ", padding=6); sf.pack(fill="x", pady=4)
        ttk.Label(sf, justify="left", text="Steps run from top to bottom. Double-click a Wait step to change its time.\n"
                  "Record: click Record, use any other program, then click Stop recording. Turn the app OFF first.").pack(anchor="w")
        row = ttk.Frame(sf); row.pack(fill="x", pady=4)
        tree = ttk.Treeview(row, columns=("n", "w"), show="headings", height=6, selectmode="browse")
        tree.heading("n", text="#"); tree.heading("w", text="Step")
        tree.column("n", width=34, anchor="center"); tree.column("w", width=400)
        tree.pack(side="left")
        bt = ttk.Frame(row); bt.pack(side="left", padx=8, anchor="n")
        for text, cmd in [("Move up", lambda: move(-1)), ("Move down", lambda: move(1)),
                          ("Delete step", lambda: remove()), ("Clear all", lambda: clear())]:
            ttk.Button(bt, text=text, command=cmd, width=14).pack(pady=1)
        rb = ttk.Button(bt, text="● Record", command=lambda: torec(), width=14); rb.pack(pady=(8, 1))
        ttk.Checkbutton(bt, text="Record waiting time", variable=tim).pack()
        empty = ttk.Label(sf, text="No steps yet. Add one below, or press Record.", foreground="#a33")

        af = ttk.LabelFrame(fm, text=" Add or change a step ", padding=6); af.pack(fill="x", pady=4)
        typ, val = tk.StringVar(value=STEP_LABEL["tap"]), tk.StringVar()
        r = ttk.Frame(af); r.pack(fill="x")
        ttk.Label(r, text="Action:").pack(side="left")
        tcb = ttk.Combobox(r, textvariable=typ, values=[l for _, l, _ in STEP_INFO], state="readonly", width=24)
        tcb.pack(side="left", padx=6)
        ttk.Label(r, text="Value:").pack(side="left")
        vc = ttk.Combobox(r, textvariable=val, width=26); vc.pack(side="left", padx=6)
        hint = ttk.Label(af, foreground="#666"); hint.pack(anchor="w", pady=2)
        r = ttk.Frame(af); r.pack(fill="x")
        ttk.Button(r, text="Add as new step", command=lambda: add()).pack(side="left")
        ttk.Button(r, text="Update the selected step", command=lambda: update()).pack(side="left", padx=6)
        ttk.Label(r, text="(new steps go after the selected one, or at the end)", foreground="#666").pack(side="left")
        r = ttk.Frame(af); r.pack(fill="x", pady=(6, 0))
        alld = tk.StringVar(value="100")
        ttk.Label(r, text="Make every Wait in this list").pack(side="left")
        ttk.Entry(r, textvariable=alld, width=7).pack(side="left", padx=4)
        ttk.Label(r, text="ms").pack(side="left")
        ttk.Button(r, text="Apply", command=lambda: setall()).pack(side="left", padx=6)

        # ---- logic ----
        def cur():
            return st[sec.get()]

        def fill(sel=None):
            sf.config(text=" " + dict(SECS)[sec.get()] + " ")
            tree.delete(*tree.get_children())
            for i, x in enumerate(cur()):
                tree.insert("", "end", iid=str(i), values=(i + 1, describe(x)))
            if cur():
                empty.pack_forget()
            else:
                empty.pack(anchor="w")
            if sel is not None and 0 <= sel < len(cur()):
                tree.selection_set(str(sel)); tree.see(str(sel))

        def on_mode(*_):
            if mode.get() == "seq":
                rs.pack(anchor="w", pady=2)
                if sec.get() == "main":
                    sec.set("press")
            else:
                rs.pack_forget(); sec.set("main")
            fill()

        def on_type(keep=False):
            t = STEP_CODE[typ.get()]
            vals = {"tap": KEYS, "down": KEYS, "up": KEYS, "click": MOUSE_NAMES, "scroll": ["up", "down"],
                    "delay": ["50", "100", "250", "500", "1000"]}.get(t, [])
            vc["values"] = vals; hint["text"] = STEP_HINT[t]
            if not keep:
                val.set({"click": "MouseLeft", "scroll": "up", "delay": "100"}.get(t, ""))

        def pick(*_):
            sel = tree.selection()
            if sel:
                x = cur()[int(sel[0])]
                typ.set(STEP_LABEL[x["t"]]); on_type(True); val.set(x["v"])

        def dbl(e):
            i = tree.identify_row(e.y)
            if i and cur()[int(i)]["t"] == "delay":
                x = cur()[int(i)]
                n = simpledialog.askinteger("Change wait time", "Wait how many milliseconds?  (1000 = 1 second)",
                                            initialvalue=int(x["v"]), minvalue=0, maxvalue=600000, parent=d)
                if n is not None:
                    x["v"] = str(n); fill(int(i))

        def read():
            t, v = STEP_CODE[typ.get()], val.get().strip()
            if not v:
                messagebox.showerror("Missing value", "Fill in the Value box first.", parent=d); return None
            if t == "delay" and not v.isdigit():
                messagebox.showerror("Not a number", "Wait time must be a whole number of milliseconds.", parent=d); return None
            if t in ("tap", "down", "up", "click") and not valid(v):
                messagebox.showerror("Unknown key", f"'{v}' is not a known key. Pick one from the list.", parent=d); return None
            return {"t": t, "v": v}

        def add():
            x = read()
            if x:
                sel = tree.selection()
                i = int(sel[0]) + 1 if sel else len(cur())
                cur().insert(i, x); fill(i)

        def update():
            sel = tree.selection()
            if not sel:
                return messagebox.showinfo("Pick a step", "Click a step in the list first, change it, then press Update.", parent=d)
            x = read()
            if x:
                cur()[int(sel[0])] = x; fill(int(sel[0]))

        def remove():
            sel = tree.selection()
            if sel:
                i = int(sel[0]); del cur()[i]; fill(min(i, len(cur()) - 1))

        def move(dx):
            sel = tree.selection()
            if sel and 0 <= int(sel[0]) + dx < len(cur()):
                i, j, a = int(sel[0]), int(sel[0]) + dx, cur()
                a[i], a[j] = a[j], a[i]; fill(j)

        def clear():
            if cur() and messagebox.askyesno("Clear all", "Delete every step in this list?", parent=d):
                cur().clear(); fill()

        def setall():
            v = alld.get().strip()
            if not v.isdigit():
                return messagebox.showerror("Not a number", "Type a whole number of milliseconds.", parent=d)
            for x in cur():
                if x["t"] == "delay":
                    x["v"] = v
            fill()

        def stop_rec():
            r = rec["r"]
            if r:
                r.stop(); rec["r"] = None; rb["text"] = "● Record"; fill()

        def torec():
            if rec["r"]:
                return stop_rec()
            if s.on:
                return messagebox.showerror("Turn OFF first", "Click Turn OFF in the main window, then record.", parent=d)
            rec["r"] = Recorder(cur(), tim.get(), rb.winfo_id()); rec["r"].start(); rb["text"] = "■ Stop recording"

        def lload(*_):
            m = s.lib.get(libv.get())
            if not m:
                return
            st.clear(); st.update(json.loads(json.dumps(m["steps"])))
            for k, _ in SECS:
                st.setdefault(k, [])
            sec.set("press" if m["mode"] == "seq" else "main"); mode.set(m["mode"]); on_mode()

        def lsave():
            n = nm.get().strip()
            if not n:
                return messagebox.showerror("Name needed", "Type a name for this macro first.", parent=d)
            s.lib[n] = {"mode": mode.get(), "steps": json.loads(json.dumps(st))}
            s.commit(); lcb["values"] = sorted(s.lib); libv.set(n)

        def ldel():
            if s.lib.pop(libv.get(), None) is not None:
                s.commit(); lcb["values"] = sorted(s.lib); libv.set("")

        def show(*_):
            for f in (fk, fc, fm):
                f.pack_forget()
            {"key": fk, "command": fc, "macro": fm}[cat.get()].pack(fill="x")

        def close():
            stop_rec(); d.destroy()

        def save():
            c = cat.get()
            if c == "key":
                v = kv.get().strip()
                if not valid(v):
                    return messagebox.showerror("Pick a key", "Pick a key or mouse button from the list.", parent=d)
                nb = {"type": "key", "v": v}
            elif c == "command":
                v = cv.get().strip()
                if not v or not all(valid(p.strip()) for p in v.split("+")):
                    return messagebox.showerror("Unknown key", "The shortcut has a key name I don't know.\nExample: ctrl+shift+s", parent=d)
                nb = {"type": "command", "v": v}
            else:
                if not any(st.values()):
                    return messagebox.showerror("No steps", "Add at least one step first.", parent=d)
                nb = {"type": "macro", "mode": mode.get(), "steps": st}
            s.eng.b[tid] = nb; s.commit(); close()

        def unassign():
            s.eng.b.pop(tid, None); s.commit(); close()

        cat.trace_add("write", show); mode.trace_add("write", on_mode); sec.trace_add("write", lambda *_: fill())
        tree.bind("<<TreeviewSelect>>", pick); tree.bind("<Double-1>", dbl)
        tcb.bind("<<ComboboxSelected>>", lambda e: on_type()); lcb.bind("<<ComboboxSelected>>", lload)
        d.protocol("WM_DELETE_WINDOW", close)
        bar = ttk.Frame(d); bar.pack(fill="x", padx=12, pady=10)
        ttk.Button(bar, text="Save", command=save).pack(side="left")
        ttk.Button(bar, text="Remove this assignment", command=unassign).pack(side="left", padx=8)
        ttk.Button(bar, text="Cancel", command=close).pack(side="left")
        show(); on_mode(); on_type()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
