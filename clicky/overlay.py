"""Small always-on-top indicator showing whether Clicky sees your hand and what it just did."""

import logging
import sys
import threading
import time

log = logging.getLogger(__name__)

KEY_COLOR = "#ff00fe"  # made fully transparent on Windows
BG = "#151a2e"
COLORS = {
    "none": "#6b7280",
    "hand": "#3ccf91",
    "pinch": "#ffb547",
    "action": "#4f7cff",
    "locked": "#ff4d5e",
    "error": "#ff4d5e",
}
FLASH_SECONDS = 1.5
WIDTH, HEIGHT, MARGIN = 132, 44, 16


def overlay_state(status, last_action, now):
    """Picks what the indicator shows: (color key, icon name or None)."""
    if not status["camera_ok"]:
        return "error", None
    if status["locked"]:
        return "locked", "lock"
    if last_action and now - last_action[0] < FLASH_SECONDS:
        return "action", last_action[1]
    poses = [h["pose"] for h in status["hands"].values()]
    if "pinch" in poses:
        return "pinch", None
    if poses:
        return "hand", None
    return "none", None


class Overlay:
    def __init__(self, clicky):
        self.clicky = clicky
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="overlay", daemon=True)
        self._last_topmost = 0.0

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=2)

    # Everything below runs on the overlay thread (Tk must stay on one thread).
    def _run(self):
        try:
            import tkinter as tk
        except ImportError:
            log.warning("tkinter not available; on-screen indicator disabled")
            return
        try:
            root = tk.Tk()
        except Exception as exc:
            log.warning("Cannot create on-screen indicator: %s", exc)
            return
        self.root = root
        root.title("Clicky indicator")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        corner = KEY_COLOR if sys.platform == "win32" else BG
        root.configure(bg=corner)
        if sys.platform == "win32":
            root.attributes("-transparentcolor", KEY_COLOR)
        self.scale = max(1.0, root.winfo_fpixels("1i") / 96)
        self.w, self.h = int(WIDTH * self.scale), int(HEIGHT * self.scale)
        self.canvas = tk.Canvas(root, width=self.w, height=self.h, bg=corner, highlightthickness=0)
        self.canvas.pack()
        self._visible = True
        self._geometry = None
        root.update_idletasks()
        if sys.platform == "win32":
            self._make_click_through(root)
        self._tick()
        root.mainloop()

    @staticmethod
    def _make_click_through(root):
        try:
            import ctypes

            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
            GWL_EXSTYLE = -20
            WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x80000, 0x20
            WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80, 0x8000000
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(
                hwnd,
                GWL_EXSTYLE,
                style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
            )
        except Exception:
            log.exception("Could not make the indicator click-through")

    def _tick(self):
        if self._stop.is_set():
            self.root.destroy()
            return
        try:
            self._update()
        except Exception:
            log.exception("Indicator update failed")
        self.root.after(100, self._tick)

    def _update(self):
        root, cfg = self.root, self.clicky.cfg
        if not cfg["overlay_enabled"]:
            if self._visible:
                root.withdraw()
                self._visible = False
            return
        if not self._visible:
            root.deiconify()
            self._visible = True
        m = int(MARGIN * self.scale)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        pos = cfg["overlay_position"]
        x = m if pos.endswith("left") else sw - self.w - m
        y = m if pos.startswith("top") else sh - self.h - m - int(40 * self.scale)  # keep above the taskbar
        geometry = f"{self.w}x{self.h}+{x}+{y}"
        if geometry != self._geometry:
            root.geometry(geometry)
            self._geometry = geometry
        root.attributes("-alpha", cfg["overlay_opacity"])
        now = time.monotonic()
        if now - self._last_topmost > 2:
            self._last_topmost = now
            root.attributes("-topmost", True)
            root.lift()
        status = self.clicky.status()
        color, icon = overlay_state(status, self.clicky.last_action, now)
        self._draw(COLORS[color], icon, status.get("slide"))

    def _draw(self, color, icon, slide):
        c, s, w, h = self.canvas, self.scale, self.w, self.h
        c.delete("all")
        r = h / 2
        c.create_oval(0, 0, h, h, fill=BG, outline=BG)
        c.create_oval(w - h, 0, w, h, fill=BG, outline=BG)
        c.create_rectangle(r, 0, w - r, h, fill=BG, outline=BG)
        cx, cy, dot = r, r, 9 * s
        c.create_oval(cx - dot, cy - dot, cx + dot, cy + dot, fill=color, outline="")
        ix, iy = h + 14 * s, r
        u = 9 * s
        white = "#e8ebff"
        if icon == "next":
            c.create_polygon(ix - u, iy - u, ix + u, iy, ix - u, iy + u, fill=white)
        elif icon == "prev":
            c.create_polygon(ix + u, iy - u, ix - u, iy, ix + u, iy + u, fill=white)
        elif icon in ("start_show", "start_from_current"):
            c.create_polygon(ix - u * 0.8, iy - u, ix + u, iy, ix - u * 0.8, iy + u, outline=white, fill="")
        elif icon == "end_show":
            c.create_rectangle(ix - u * 0.8, iy - u * 0.8, ix + u * 0.8, iy + u * 0.8, fill=white)
        elif icon == "black":
            c.create_rectangle(ix - u, iy - u * 0.7, ix + u, iy + u * 0.7, fill="#000", outline=white)
        elif icon == "white":
            c.create_rectangle(ix - u, iy - u * 0.7, ix + u, iy + u * 0.7, fill=white, outline=white)
        elif icon == "lock":
            c.create_arc(
                ix - u * 0.6,
                iy - u * 1.2,
                ix + u * 0.6,
                iy + u * 0.2,
                start=0,
                extent=180,
                style="arc",
                outline=white,
                width=max(2, int(2 * s)),
            )
            c.create_rectangle(ix - u * 0.9, iy - u * 0.4, ix + u * 0.9, iy + u, fill=white, outline=white)
        if slide and slide.get("slide") and slide.get("total"):
            c.create_text(
                w - 12 * s,
                r,
                text=f"{slide['slide']}/{slide['total']}",
                anchor="e",
                fill=white,
                font=("Segoe UI", 11, "bold"),
            )
