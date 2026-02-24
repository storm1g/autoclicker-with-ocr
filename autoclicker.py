"""
=============================================================
  AUTOCLICKER - Prefix/Suffix Automation Tool
  Requirements: pip install pyautogui pillow easyocr opencv-python keyboard
  No external system installs needed — EasyOCR is pure Python.
  (EasyOCR downloads its models ~100 MB on first use)
=============================================================
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import time
import json
import os
import ctypes
from ctypes import wintypes

try:
    import pyautogui
    PYAUTOGUI_OK = True
except ImportError:
    PYAUTOGUI_OK = False

try:
    from PIL import Image, ImageGrab, ImageDraw
    PIL_OK = True
except ImportError:
    PIL_OK = False

try:
    import easyocr
    EASYOCR_OK = True
except ImportError:
    EASYOCR_OK = False

# EasyOCR reader is expensive to initialise — create once, lazily
_easyocr_reader = None

def get_ocr_reader():
    global _easyocr_reader
    if _easyocr_reader is None:
        _easyocr_reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    return _easyocr_reader

try:
    import numpy as np
    NUMPY_OK = True
except ImportError:
    NUMPY_OK = False

CONFIG_FILE = "autoclicker_config.json"

DEFAULT_CONFIG = {
    "click_points": [],          # list of {x, y, delay_after, label}
    "text_region": None,          # {x, y, w, h} — screen region to OCR
    "target_words": [],           # strings that must ALL appear (AND)
    "or_words": [],               # at least ONE must appear (OR)
    "forbidden_words": [],        # strings that must NOT appear
    "color_check": None,          # {x, y, r, g, b, tolerance} optional color check
    "loop_delay": 0.5,            # seconds between attempts
    "max_attempts": 500,
    "stop_key": "F8",
    "hotkey_start": "F6",
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def grab_region(region):
    """region = (x, y, w, h)"""
    x, y, w, h = region
    return ImageGrab.grab(bbox=(x, y, x + w, y + h))


def ocr_region(region):
    img = grab_region(region)
    # Upscale for better accuracy on small game text
    img = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)
    img_np = np.array(img)
    reader = get_ocr_reader()
    results = reader.readtext(img_np, detail=0)
    return " ".join(results).strip()


def pixel_color(x, y):
    img = ImageGrab.grab(bbox=(x, y, x + 1, y + 1))
    return img.getpixel((0, 0))[:3]


def color_matches(x, y, target_rgb, tolerance=15):
    r, g, b = pixel_color(x, y)
    tr, tg, tb = target_rgb
    return (abs(r - tr) + abs(g - tg) + abs(b - tb)) / 3 <= tolerance


# Hardware click
def hardware_click(x, y, double=False):
    """Sends a hardware-level mouse click via SendInput."""
    screen_w = ctypes.windll.user32.GetSystemMetrics(0)
    screen_h = ctypes.windll.user32.GetSystemMetrics(1)
    nx = int(x * 65535 / screen_w)
    ny = int(y * 65535 / screen_h)

    MOUSEEVENTF_MOVE      = 0x0001
    MOUSEEVENTF_LEFTDOWN  = 0x0002
    MOUSEEVENTF_LEFTUP    = 0x0004
    MOUSEEVENTF_ABSOLUTE  = 0x8000

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                    ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]

    class INPUT(ctypes.Structure):
        class _INPUT(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT)]
        _anonymous_ = ("_input",)
        _fields_ = [("type", wintypes.DWORD), ("_input", _INPUT)]

    def send(flags, dx=0, dy=0):
        inp = INPUT(type=0)
        inp.mi.dwFlags = flags
        inp.mi.dx = dx
        inp.mi.dy = dy
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

    send(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, nx, ny)
    time.sleep(0.02)
    send(MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE, nx, ny)
    time.sleep(0.02)
    send(MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE, nx, ny)
    if double:
        time.sleep(0.05)
        send(MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE, nx, ny)
        time.sleep(0.02)
        send(MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE, nx, ny)

# ── Macro engine ─────────────────────────────────────────────────────────────

class MacroEngine:
    def __init__(self, cfg, log_fn):
        self.cfg = cfg
        self.log = log_fn
        self.running = False
        self.attempt = 0

    def stop(self):
        self.running = False

    def check_success(self):
        """Returns True if the desired prefix/suffix is found."""
    def check_success(self):
        """Returns True if the desired prefix/suffix is found."""
        region   = self.cfg.get("text_region")
        color    = self.cfg.get("color_check")
        targets  = [w.strip().lower() for w in self.cfg.get("target_words", [])  if w.strip()]
        or_words = [w.strip().lower() for w in self.cfg.get("or_words", [])       if w.strip()]
        forbidden= [w.strip().lower() for w in self.cfg.get("forbidden_words", []) if w.strip()]

        # If nothing is configured to check, never auto-stop — run until max_attempts
        has_ocr_check   = bool(region and (targets or or_words))
        has_color_check = bool(color)
        if not has_ocr_check and not has_color_check:
            return False

        # ── Color check ──
        if color:
            cx, cy = color["x"], color["y"]
            rgb = (color["r"], color["g"], color["b"])
            tol = color.get("tolerance", 15)
            if not color_matches(cx, cy, rgb, tol):
                return False

        # ── OCR check ──
        if region and (targets or or_words):
            try:
                text = ocr_region(
                    (region["x"], region["y"], region["w"], region["h"])
                ).lower()
                self.log(f"  OCR: {repr(text[:80])}")
                # Forbidden — any match = fail
                for word in forbidden:
                    if word in text:
                        return False
                # AND — all must be present
                for word in targets:
                    if word not in text:
                        return False
                # OR — at least one must be present (skip check if list is empty)
                if or_words and not any(word in text for word in or_words):
                    return False
            except Exception as e:
                self.log(f"  OCR error: {e}")
                return False

        return True

    def run(self):
        self.running = True
        self.attempt = 0
        max_att = self.cfg.get("max_attempts", 500)
        delay   = self.cfg.get("loop_delay", 0.5)
        clicks  = self.cfg.get("click_points", [])

        limit_str = str(self.cfg['max_attempts']) if self.cfg['max_attempts'] < 10_000_000 else "∞"
        self.log(f"▶  Macro started — {limit_str} attempt(s). Move mouse to top-left corner to emergency-stop.")

        while self.running and self.attempt < max_att:
            self.attempt += 1
            self.log(f"── Attempt {self.attempt} ──")

            # Perform all clicks
            for cp in clicks:
                if not self.running:
                    break
                hardware_click(cp["x"], cp["y"], double=cp.get("double_click", False))
                self.log(f"  {'Double-c' if cp.get('double_click') else 'C'}licked '{cp.get('label','?')}' @ ({cp['x']},{cp['y']})")
                after = cp.get("delay_after", 0.15)
                time.sleep(max(after, 0.05))

            time.sleep(delay)

            if not self.running:
                break

            if self.check_success():
                self.log(f"✅  SUCCESS on attempt {self.attempt}!")
                self.running = False
                return

        if self.attempt >= max_att:
            self.log(f"⚠️  Reached max attempts ({max_att}) without success.")
        else:
            self.log("⏹  Macro stopped by user.")


# ── GUI ───────────────────────────────────────────────────────────────────────

DARK = "#1a1a2e"
PANEL = "#16213e"
ACCENT = "#e94560"
ACCENT2 = "#0f3460"
TEXT = "#eaeaea"
MUTED = "#888"
GREEN = "#2ecc71"
FONT_MAIN = ("Courier New", 10)
FONT_HEAD = ("Courier New", 12, "bold")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("⚔ AutoClicker")
        self.configure(bg=DARK)
        self.resizable(True, True)
        self.geometry("820x700")
        self.cfg = load_config()
        self._engine = None
        self._thread = None
        self._picking = None  # what coordinate we're picking

        self._build_ui()
        self._refresh_click_list()

    # ── UI build ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=6, pady=6)
        self._style_notebook(nb)

        self._tab_clicks  = self._make_tab(nb, "🖱 Clicks")
        self._tab_detect  = self._make_tab(nb, "🔍 Detection")
        self._tab_options = self._make_tab(nb, "⚙ Options")
        self._tab_log     = self._make_tab(nb, "📋 Log")

        self._build_clicks_tab()
        self._build_detect_tab()
        self._build_options_tab()
        self._build_log_tab()
        self._build_bottom_bar()

    def _style_notebook(self, nb):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TNotebook", background=DARK, borderwidth=0)
        s.configure("TNotebook.Tab", background=PANEL, foreground=TEXT,
                    font=FONT_MAIN, padding=[12, 5])
        s.map("TNotebook.Tab", background=[("selected", ACCENT2)],
              foreground=[("selected", ACCENT)])

    def _make_tab(self, nb, label):
        f = tk.Frame(nb, bg=DARK)
        nb.add(f, text=label)
        return f

    # ── Clicks tab ────────────────────────────────────────────────────────────

    def _build_clicks_tab(self):
        f = self._tab_clicks
        self._lbl(f, "CLICK SEQUENCE", FONT_HEAD).pack(anchor="w", padx=10, pady=(10,2))
        self._lbl(f, "These clicks are performed in order on every attempt.", MUTED).pack(anchor="w", padx=10)

        # List
        lf = tk.Frame(f, bg=PANEL, relief="flat")
        lf.pack(fill="both", expand=True, padx=10, pady=6)

        cols = ("label", "x", "y", "delay_after", "double_click")
        self._click_tree = ttk.Treeview(lf, columns=cols, show="headings", height=10)
        for c, w, h in zip(cols, [170, 70, 70, 90, 90], ["Label","X","Y","Delay(s)","Double"]):
            self._click_tree.heading(c, text=h)
            self._click_tree.column(c, width=w, anchor="center")
        self._style_tree(self._click_tree)
        self._click_tree.pack(fill="both", expand=True, padx=4, pady=4)

        # Buttons
        bf = tk.Frame(f, bg=DARK)
        bf.pack(fill="x", padx=10, pady=4)
        for txt, cmd in [("➕ Add Click", self._add_click),
                         ("✏ Edit", self._edit_click),
                         ("📋 Duplicate", self._duplicate_click),
                         ("🗑 Remove", self._remove_click),
                         ("⬆ Up", self._move_up),
                         ("⬇ Down", self._move_down)]:
            self._btn(bf, txt, cmd).pack(side="left", padx=3)

    def _add_click(self):
        self._click_dialog()

    def _edit_click(self):
        sel = self._click_tree.selection()
        if not sel:
            return
        idx = self._click_tree.index(sel[0])
        self._click_dialog(idx)

    def _click_dialog(self, idx=None):
        cp = self.cfg["click_points"][idx] if idx is not None else {"label":"","x":0,"y":0,"delay_after":0.15,"double_click":False}
        dlg = tk.Toplevel(self, bg=DARK)
        dlg.title("Click Point")
        dlg.geometry("340x300")
        dlg.grab_set()

        vars_ = {}
        for row, (key, label, val) in enumerate([
            ("label","Label",cp.get("label","")),
            ("x","X",cp.get("x",0)),
            ("y","Y",cp.get("y",0)),
            ("delay_after","Delay after (s)",cp.get("delay_after",0.15)),
        ]):
            tk.Label(dlg, text=label, bg=DARK, fg=TEXT, font=FONT_MAIN).grid(row=row, column=0, padx=10, pady=6, sticky="w")
            v = tk.StringVar(value=str(val))
            vars_[key] = v
            e = tk.Entry(dlg, textvariable=v, bg=PANEL, fg=TEXT, font=FONT_MAIN, insertbackground=TEXT, width=18)
            e.grid(row=row, column=1, padx=10, pady=6)

        # Double-click checkbox
        double_var = tk.BooleanVar(value=cp.get("double_click", False))
        tk.Label(dlg, text="Double click", bg=DARK, fg=TEXT, font=FONT_MAIN).grid(row=4, column=0, padx=10, pady=6, sticky="w")
        tk.Checkbutton(dlg, variable=double_var, bg=DARK, fg=TEXT, activebackground=DARK,
                       selectcolor=PANEL, font=FONT_MAIN).grid(row=4, column=1, sticky="w", padx=10)

        def pick_coord():
            dlg.iconify()
            self._lbl_status.config(text="Move mouse to target & press F9 ...")
            def wait():
                import keyboard
                keyboard.wait("F9")
                x, y = pyautogui.position()
                vars_["x"].set(str(x))
                vars_["y"].set(str(y))
                dlg.deiconify()
                self._lbl_status.config(text="Coordinate captured.")
            threading.Thread(target=wait, daemon=True).start()

        btn_row = tk.Frame(dlg, bg=DARK)
        btn_row.grid(row=6, column=0, columnspan=2, pady=8)
        self._btn(btn_row, "📍 Pick (F9)", pick_coord).pack(side="left", padx=4)

        def save():
            new = {k: (int(v.get()) if k in ("x","y") else
                       float(v.get()) if k=="delay_after" else v.get())
                   for k, v in vars_.items()}
            new["double_click"] = double_var.get()
            if idx is not None:
                self.cfg["click_points"][idx] = new
            else:
                self.cfg["click_points"].append(new)
            save_config(self.cfg)
            self._refresh_click_list()
            dlg.destroy()

        self._btn(btn_row, "💾 Save", save).pack(side="left", padx=4)

    def _duplicate_click(self):
        sel = self._click_tree.selection()
        if not sel:
            return
        idx = self._click_tree.index(sel[0])
        import copy
        original = self.cfg["click_points"][idx]
        dupe = copy.deepcopy(original)
        dupe["label"] = dupe.get("label", "") + " (copy)"
        self.cfg["click_points"].insert(idx + 1, dupe)
        save_config(self.cfg)
        self._refresh_click_list()

    def _remove_click(self):
        sel = self._click_tree.selection()
        if not sel:
            return
        idx = self._click_tree.index(sel[0])
        del self.cfg["click_points"][idx]
        save_config(self.cfg)
        self._refresh_click_list()

    def _move_up(self):
        sel = self._click_tree.selection()
        if not sel:
            return
        idx = self._click_tree.index(sel[0])
        if idx > 0:
            cps = self.cfg["click_points"]
            cps[idx-1], cps[idx] = cps[idx], cps[idx-1]
            save_config(self.cfg)
            self._refresh_click_list()

    def _move_down(self):
        sel = self._click_tree.selection()
        if not sel:
            return
        idx = self._click_tree.index(sel[0])
        cps = self.cfg["click_points"]
        if idx < len(cps) - 1:
            cps[idx], cps[idx+1] = cps[idx+1], cps[idx]
            save_config(self.cfg)
            self._refresh_click_list()

    def _refresh_click_list(self):
        for item in self._click_tree.get_children():
            self._click_tree.delete(item)
        for cp in self.cfg.get("click_points", []):
            self._click_tree.insert("", "end", values=(
                cp.get("label",""), cp.get("x",0), cp.get("y",0),
                cp.get("delay_after",0.15), "✔" if cp.get("double_click") else ""
            ))

    # ── Detection tab ─────────────────────────────────────────────────────────

    def _build_detect_tab(self):
        f = self._tab_detect

        # OCR region
        self._lbl(f, "OCR TEXT REGION", FONT_HEAD).pack(anchor="w", padx=10, pady=(10,2))
        self._lbl(f, "Define the screen area where the item name appears.", MUTED).pack(anchor="w", padx=10)

        reg_f = tk.Frame(f, bg=PANEL)
        reg_f.pack(fill="x", padx=10, pady=6)

        self._reg_vars = {}
        for i, (k, label) in enumerate([("x","X"),("y","Y"),("w","Width"),("h","Height")]):
            r = self.cfg.get("text_region") or {}
            v = tk.StringVar(value=str(r.get(k, 0)))
            self._reg_vars[k] = v
            tk.Label(reg_f, text=label, bg=PANEL, fg=TEXT, font=FONT_MAIN).grid(row=0, column=i*2, padx=(10,2), pady=8)
            tk.Entry(reg_f, textvariable=v, bg=DARK, fg=TEXT, font=FONT_MAIN,
                     insertbackground=TEXT, width=7).grid(row=0, column=i*2+1, padx=(0,8))

        bf = tk.Frame(f, bg=DARK)
        bf.pack(fill="x", padx=10)
        self._btn(bf, "📐 Select Region (drag)", self._pick_region).pack(side="left", padx=3)
        self._btn(bf, "💾 Save Region", self._save_region).pack(side="left", padx=3)
        self._btn(bf, "👁 Preview OCR", self._preview_ocr).pack(side="left", padx=3)

        ttk.Separator(f, orient="horizontal").pack(fill="x", padx=10, pady=10)

        # Target / forbidden words
        self._lbl(f, "SUCCESS CONDITIONS", FONT_HEAD).pack(anchor="w", padx=10, pady=(0,2))
        self._lbl(f, "All AND words must match. At least one OR word must match (leave empty to skip).", MUTED).pack(anchor="w", padx=10)

        row2 = tk.Frame(f, bg=DARK)
        row2.pack(fill="x", padx=10)

        lf1 = tk.LabelFrame(row2, text=" ✅ Must ALL be present (AND) ", bg=DARK, fg=GREEN,
                             font=FONT_MAIN, labelanchor="nw")
        lf1.pack(side="left", fill="both", expand=True, padx=(0,4))
        self._txt_targets = tk.Text(lf1, height=5, bg=PANEL, fg=GREEN, font=FONT_MAIN,
                                    insertbackground=TEXT, wrap="word")
        self._txt_targets.pack(fill="both", expand=True, padx=4, pady=4)
        self._txt_targets.insert("1.0", "\n".join(self.cfg.get("target_words", [])))

        lf_or = tk.LabelFrame(row2, text=" 🔀 Must contain ONE OF (OR) ", bg=DARK, fg="#f0a500",
                               font=FONT_MAIN, labelanchor="nw")
        lf_or.pack(side="left", fill="both", expand=True, padx=(0,4))
        self._txt_or = tk.Text(lf_or, height=5, bg=PANEL, fg="#f0a500", font=FONT_MAIN,
                               insertbackground=TEXT, wrap="word")
        self._txt_or.pack(fill="both", expand=True, padx=4, pady=4)
        self._txt_or.insert("1.0", "\n".join(self.cfg.get("or_words", [])))

        lf2 = tk.LabelFrame(row2, text=" ❌ Must NOT contain ", bg=DARK, fg=ACCENT,
                             font=FONT_MAIN, labelanchor="nw")
        lf2.pack(side="left", fill="both", expand=True)
        self._txt_forbidden = tk.Text(lf2, height=5, bg=PANEL, fg=ACCENT, font=FONT_MAIN,
                                      insertbackground=TEXT, wrap="word")
        self._txt_forbidden.pack(fill="both", expand=True, padx=4, pady=4)
        self._txt_forbidden.insert("1.0", "\n".join(self.cfg.get("forbidden_words", [])))

        self._btn(f, "💾 Save Words", self._save_words).pack(anchor="w", padx=10, pady=4)

        ttk.Separator(f, orient="horizontal").pack(fill="x", padx=10, pady=6)

        # Color check
        self._lbl(f, "PIXEL COLOR CHECK (optional)", FONT_HEAD).pack(anchor="w", padx=10, pady=(0,2))
        self._lbl(f, "Check a specific pixel color as extra confirmation.", MUTED).pack(anchor="w", padx=10)

        cf = tk.Frame(f, bg=PANEL)
        cf.pack(fill="x", padx=10, pady=4)
        self._color_vars = {}
        clr = self.cfg.get("color_check") or {}
        for i, (k, label, default) in enumerate([("x","X",0),("y","Y",0),
                                                  ("r","R",0),("g","G",255),("b","B",0),
                                                  ("tolerance","Tol",15)]):
            v = tk.StringVar(value=str(clr.get(k, default)))
            self._color_vars[k] = v
            tk.Label(cf, text=label, bg=PANEL, fg=TEXT, font=FONT_MAIN).grid(row=0, column=i*2, padx=(8,2), pady=6)
            tk.Entry(cf, textvariable=v, bg=DARK, fg=TEXT, font=FONT_MAIN,
                     insertbackground=TEXT, width=5).grid(row=0, column=i*2+1, padx=(0,4))

        cf2 = tk.Frame(f, bg=DARK)
        cf2.pack(fill="x", padx=10)
        self._btn(cf2, "🎨 Pick Color from Screen", self._pick_color_pixel).pack(side="left", padx=3)
        self._btn(cf2, "💾 Save Color Check", self._save_color).pack(side="left", padx=3)
        self._btn(cf2, "🗑 Disable Color Check", self._disable_color).pack(side="left", padx=3)

    def _pick_region(self):
        messagebox.showinfo("Pick Region",
            "A transparent overlay will appear.\nClick and drag to select the item name region.\n\nMinimize this window first if needed.")
        self.iconify()
        time.sleep(0.4)
        _RegionSelector(self)

    def _save_region(self):
        try:
            r = {k: int(v.get()) for k, v in self._reg_vars.items()}
            self.cfg["text_region"] = r
            save_config(self.cfg)
            self._lbl_status.config(text="Region saved.")
        except ValueError:
            messagebox.showerror("Error", "Region values must be integers.")

    def _preview_ocr(self):
        self._save_region()
        region = self.cfg.get("text_region")
        if not region:
            messagebox.showerror("Error","No region defined.")
            return
        if not EASYOCR_OK:
            messagebox.showerror("Error","easyocr not installed.\nRun: pip install easyocr")
            return
        self._lbl_status.config(text="Running OCR (first run downloads models, may take a moment)…")
        self.update()
        try:
            text = ocr_region(
                (region["x"],region["y"],region["w"],region["h"])
            )
            messagebox.showinfo("OCR Preview", f"Detected text:\n\n{text}")
        except Exception as e:
            messagebox.showerror("OCR Error", str(e))
        self._lbl_status.config(text="Ready.")

    def _save_words(self):
        self.cfg["target_words"]   = [l for l in self._txt_targets.get("1.0","end").splitlines() if l.strip()]
        self.cfg["or_words"]       = [l for l in self._txt_or.get("1.0","end").splitlines() if l.strip()]
        self.cfg["forbidden_words"]= [l for l in self._txt_forbidden.get("1.0","end").splitlines() if l.strip()]
        save_config(self.cfg)
        self._lbl_status.config(text="Words saved.")

    def _pick_color_pixel(self):
        messagebox.showinfo("Pick Color","Minimize this window, hover over the target pixel, then press F9.")
        def wait():
            try:
                import keyboard
                keyboard.wait("F9")
                x, y = pyautogui.position()
                r, g, b = pixel_color(x, y)
                self._color_vars["x"].set(str(x))
                self._color_vars["y"].set(str(y))
                self._color_vars["r"].set(str(r))
                self._color_vars["g"].set(str(g))
                self._color_vars["b"].set(str(b))
                self._lbl_status.config(text=f"Color picked: rgb({r},{g},{b}) @ ({x},{y})")
            except Exception as e:
                self._lbl_status.config(text=f"Color pick error: {e}")
        threading.Thread(target=wait, daemon=True).start()

    def _save_color(self):
        try:
            c = {k: int(v.get()) for k, v in self._color_vars.items()}
            self.cfg["color_check"] = c
            save_config(self.cfg)
            self._lbl_status.config(text="Color check saved.")
        except ValueError:
            messagebox.showerror("Error","Color values must be integers.")

    def _disable_color(self):
        self.cfg["color_check"] = None
        save_config(self.cfg)
        self._lbl_status.config(text="Color check disabled.")

    # ── Options tab ───────────────────────────────────────────────────────────

    def _build_options_tab(self):
        f = self._tab_options
        self._lbl(f, "OPTIONS", FONT_HEAD).pack(anchor="w", padx=10, pady=(10,4))

        opts = [
            ("loop_delay", "Delay between attempts (s)"),
            ("max_attempts","Max attempts"),
        ]
        self._opt_vars = {}
        for key, label in opts:
            row = tk.Frame(f, bg=DARK)
            row.pack(fill="x", padx=14, pady=5)
            tk.Label(row, text=label, bg=DARK, fg=TEXT, font=FONT_MAIN, width=28, anchor="w").pack(side="left")
            v = tk.StringVar(value=str(self.cfg.get(key,"")))
            self._opt_vars[key] = v
            tk.Entry(row, textvariable=v, bg=PANEL, fg=TEXT, font=FONT_MAIN,
                     insertbackground=TEXT, width=40).pack(side="left", padx=6)

        self._btn(f, "💾 Save Options", self._save_options).pack(anchor="w", padx=14, pady=10)

        ttk.Separator(f, orient="horizontal").pack(fill="x", padx=10, pady=10)
        self._lbl(f, "DEPENDENCY STATUS", FONT_HEAD).pack(anchor="w", padx=10, pady=(0,4))
        deps = [
            ("pyautogui (coord picker)", PYAUTOGUI_OK),
            ("Pillow (PIL)", PIL_OK),
            ("easyocr", EASYOCR_OK),
            ("numpy", NUMPY_OK),
        ]
        for name, ok in deps:
            color = GREEN if ok else ACCENT
            status = "✅ installed" if ok else "❌ missing — pip install " + name.split()[0].lower()
            tk.Label(f, text=f"  {name}: {status}", bg=DARK, fg=color, font=FONT_MAIN, anchor="w").pack(fill="x", padx=14)

        install_cmd = "pip install pyautogui pillow easyocr opencv-python keyboard"
        tk.Label(f, text=f"\nInstall all: {install_cmd}", bg=DARK, fg=MUTED, font=FONT_MAIN).pack(anchor="w", padx=14)
        tk.Label(f, text="  (EasyOCR downloads ~100 MB of models on first use — no extra system installs needed)",
                 bg=DARK, fg=MUTED, font=("Courier New", 9)).pack(anchor="w", padx=14)

    def _save_options(self):
        for key, v in self._opt_vars.items():
            val = v.get().strip()
            if key == "loop_delay":
                self.cfg[key] = float(val)
            elif key == "max_attempts":
                self.cfg[key] = int(val)
            else:
                self.cfg[key] = val
        save_config(self.cfg)
        self._lbl_status.config(text="Options saved.")

    # ── Log tab ───────────────────────────────────────────────────────────────

    def _build_log_tab(self):
        f = self._tab_log
        self._log_box = scrolledtext.ScrolledText(f, bg="#0d0d1a", fg=TEXT, font=("Courier New",9),
                                                   state="disabled", wrap="word")
        self._log_box.pack(fill="both", expand=True, padx=6, pady=6)
        self._log_box.tag_config("success", foreground=GREEN)
        self._log_box.tag_config("error",   foreground=ACCENT)
        self._btn(f, "🗑 Clear Log", self._clear_log).pack(anchor="e", padx=8, pady=4)

    def _clear_log(self):
        self._log_box.config(state="normal")
        self._log_box.delete("1.0","end")
        self._log_box.config(state="disabled")

    def log(self, msg):
        tag = "success" if "SUCCESS" in msg else ("error" if "error" in msg.lower() or "⚠" in msg else "")
        self._log_box.config(state="normal")
        self._log_box.insert("end", msg + "\n", tag)
        self._log_box.see("end")
        self._log_box.config(state="disabled")

    # ── Bottom bar ────────────────────────────────────────────────────────────

    def _build_bottom_bar(self):
        bar = tk.Frame(self, bg=PANEL, height=44)
        bar.pack(fill="x", side="bottom")

        self._lbl_status = tk.Label(bar, text="Ready.", bg=PANEL, fg=MUTED, font=FONT_MAIN)
        self._lbl_status.pack(side="left", padx=12)

        self._btn_stop  = self._btn(bar, "⏹ Stop (F8)", self._stop_macro, bg="#3d0000", state="disabled")
        self._btn_stop.pack(side="right", padx=6, pady=4)

        self._btn_start = self._btn(bar, "▶ Start Macro (F6)", self._start_macro, bg="#003d1a")
        self._btn_start.pack(side="right", padx=6, pady=4)

        # Attempts control — right next to start button so it's always visible
        # Pack right-to-left, so last packed = leftmost on screen
        tk.Label(bar, text="(0=∞)", bg=PANEL, fg=MUTED, font=("Courier New", 9)).pack(side="right", padx=(0, 10))
        self._attempts_var = tk.StringVar(value=str(self.cfg.get("max_attempts", 100)))
        attempts_entry = tk.Entry(bar, textvariable=self._attempts_var, bg=DARK, fg=TEXT,
                                  font=FONT_MAIN, insertbackground=TEXT, width=6,
                                  justify="center")
        attempts_entry.pack(side="right", pady=4)
        tk.Label(bar, text="Attempts:", bg=PANEL, fg=TEXT, font=FONT_MAIN).pack(side="right", padx=(12, 2))

        # Hotkey bindings
        self.bind_all("<F6>", lambda e: self._start_macro())
        self.bind_all("<F8>", lambda e: self._stop_macro())

    def _start_macro(self):
        if self._thread and self._thread.is_alive():
            return
        self._save_words()

        # Read attempts from the bottom bar field and sync to config
        try:
            attempts = int(self._attempts_var.get())
        except ValueError:
            attempts = 100
            self._attempts_var.set("100")
        self.cfg["max_attempts"] = attempts if attempts > 0 else 10_000_000

        self._engine = MacroEngine(self.cfg, self.log)
        self._thread = threading.Thread(target=self._engine.run, daemon=True)
        self._thread.start()
        self._btn_start.config(state="disabled")
        self._btn_stop.config(state="normal")
        self._lbl_status.config(text="Running…")

        def watch():
            self._thread.join()
            self._btn_start.config(state="normal")
            self._btn_stop.config(state="disabled")
            self._lbl_status.config(text="Stopped.")
        threading.Thread(target=watch, daemon=True).start()

    def _stop_macro(self):
        if self._engine:
            self._engine.stop()

    # ── Widget helpers ────────────────────────────────────────────────────────

    def _lbl(self, parent, text, font=None, fg=None):
        return tk.Label(parent, text=text, bg=DARK, fg=fg or TEXT,
                        font=font or FONT_MAIN, anchor="w")

    def _btn(self, parent, text, cmd, bg=ACCENT2, state="normal"):
        return tk.Button(parent, text=text, command=cmd, bg=bg, fg=TEXT,
                         font=FONT_MAIN, relief="flat", padx=8, pady=4,
                         activebackground=ACCENT, activeforeground=TEXT,
                         cursor="hand2", state=state)

    def _style_tree(self, tree):
        s = ttk.Style()
        s.configure("Treeview", background=PANEL, foreground=TEXT,
                    fieldbackground=PANEL, font=FONT_MAIN, rowheight=24)
        s.configure("Treeview.Heading", background=ACCENT2, foreground=TEXT, font=FONT_MAIN)
        s.map("Treeview", background=[("selected", ACCENT2)])
        tree.configure(style="Treeview")


# ── Region Selector overlay ───────────────────────────────────────────────────

class _RegionSelector(tk.Toplevel):
    """Full-screen semi-transparent overlay for drag-to-select a region."""
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.attributes("-fullscreen", True)
        self.attributes("-alpha", 0.3)
        self.configure(bg="black")
        self.attributes("-topmost", True)
        self.overrideredirect(True)

        self.canvas = tk.Canvas(self, cursor="crosshair", bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.start = None
        self.rect = None

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Escape>", lambda e: self.destroy())

    def _on_press(self, e):
        self.start = (e.x, e.y)
        if self.rect:
            self.canvas.delete(self.rect)

    def _on_drag(self, e):
        if self.rect:
            self.canvas.delete(self.rect)
        x0, y0 = self.start
        self.rect = self.canvas.create_rectangle(x0, y0, e.x, e.y,
                                                  outline="#e94560", width=2, fill="")

    def _on_release(self, e):
        if not self.start:
            return
        x0, y0 = self.start
        x1, y1 = e.x, e.y
        x, y = min(x0,x1), min(y0,y1)
        w, h = abs(x1-x0), abs(y1-y0)
        self.destroy()
        self.app.deiconify()
        # Update the region vars
        self.app._reg_vars["x"].set(str(x))
        self.app._reg_vars["y"].set(str(y))
        self.app._reg_vars["w"].set(str(w))
        self.app._reg_vars["h"].set(str(h))
        self.app._save_region()
        self.app._lbl_status.config(text=f"Region selected: ({x},{y}) {w}×{h}")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()