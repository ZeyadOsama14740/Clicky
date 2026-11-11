import logging
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor

log = logging.getLogger(__name__)

KEYS = {
    "next": ("right",),
    "prev": ("left",),
    "start_show": ("f5",),
    "start_from_current": ("shift", "f5"),
    "end_show": ("esc",),
    "black": ("b",),
    "white": ("w",),
}

# PpSlideShowState
PP_RUNNING, PP_BLACK, PP_WHITE = 1, 3, 4
STATUS_INTERVAL = 1.0


class KeySender:
    """Sends presentation shortcuts to the focused window (PowerPoint, Google Slides, PDF...)."""

    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.showing = False
        self._lock = threading.Lock()
        self._kb = None

    def _keyboard(self):
        if self._kb is None:
            from pynput.keyboard import Controller

            self._kb = Controller()
        return self._kb

    def _resolve(self, action):
        if action == "toggle_show":
            action = "end_show" if self.showing else "start_show"
        if action in ("start_show", "start_from_current"):
            self.showing = True
        elif action == "end_show":
            self.showing = False
        return action

    def send(self, action: str) -> str | None:
        with self._lock:
            action = self._resolve(action)
            combo = KEYS.get(action)
            if not combo:
                return None
            if self.dry_run:
                return action
            try:
                from pynput.keyboard import Key

                kb = self._keyboard()
                keys = [getattr(Key, k) if len(k) > 1 else k for k in combo]
                for k in keys:
                    kb.press(k)
                for k in reversed(keys):
                    kb.release(k)
            except Exception:
                log.exception("Failed to send %s", action)
                return None
            return action


def _connect_powerpoint():
    if sys.platform != "win32":
        return None
    import win32com.client

    try:
        return win32com.client.GetActiveObject("PowerPoint.Application")
    except Exception:
        return None  # PowerPoint is not running


class PowerPointController:
    """Drives a running PowerPoint through COM, so slides change even if its window isn't focused."""

    NOT_RUNNING = {"running": False, "showing": False, "slide": None, "total": None}

    def __init__(self, connect=_connect_powerpoint):
        self._connect = connect
        self._app = None

    def _call(self, fn):
        try:
            if self._app is None:
                self._app = self._connect()
            if self._app is None:
                return None
            return fn(self._app)
        except Exception as exc:
            log.debug("PowerPoint call failed: %s", exc)
            self._app = None  # PowerPoint was probably closed; reconnect next time
            return None

    def status(self) -> dict:
        def get(app):
            st = {"running": True, "showing": False, "slide": None, "total": None}
            if app.SlideShowWindows.Count > 0:
                win = app.SlideShowWindows(1)
                st.update(
                    showing=True,
                    slide=win.View.CurrentShowPosition,
                    total=win.Presentation.Slides.Count,
                )
            elif app.Presentations.Count > 0:
                try:
                    st["slide"] = app.ActiveWindow.View.Slide.SlideIndex
                    st["total"] = app.ActivePresentation.Slides.Count
                except Exception:
                    pass
            return st

        return self._call(get) or dict(self.NOT_RUNNING)

    def send(self, action: str) -> str | None:
        """Returns the performed action, or None if PowerPoint can't handle it (use the keyboard)."""

        def do(app):
            showing = app.SlideShowWindows.Count > 0
            act = action
            if act == "toggle_show":
                act = "end_show" if showing else "start_show"
            if act in ("start_show", "start_from_current"):
                if showing or app.Presentations.Count == 0:
                    return None
                index = None
                if act == "start_from_current":
                    try:
                        index = app.ActiveWindow.View.Slide.SlideIndex
                    except Exception:
                        index = None
                win = app.ActivePresentation.SlideShowSettings.Run()
                if index:
                    win.View.GotoSlide(index)
                return act
            if not showing:
                return None
            view = app.SlideShowWindows(1).View
            if act in ("next", "prev"):
                if view.State in (PP_BLACK, PP_WHITE):
                    view.State = PP_RUNNING
                view.Next() if act == "next" else view.Previous()
            elif act == "end_show":
                view.Exit()
            elif act in ("black", "white"):
                target = PP_BLACK if act == "black" else PP_WHITE
                view.State = PP_RUNNING if view.State == target else target
            else:
                return None
            return act

        return self._call(do)


def _com_init():
    if sys.platform == "win32":
        import pythoncom

        pythoncom.CoInitialize()


class ActionSender:
    """Runs actions on one background thread: PowerPoint via COM when possible, otherwise keys."""

    def __init__(self, config_getter, dry_run=False, powerpoint=None, keys=None):
        self._cfg = config_getter
        self.dry_run = dry_run
        self.keys = keys or KeySender(dry_run)
        self.powerpoint = powerpoint or PowerPointController()
        self.ppt = dict(PowerPointController.NOT_RUNNING)
        self._pool = ThreadPoolExecutor(1, thread_name_prefix="actions", initializer=_com_init)
        self._last_refresh = 0.0
        self._refreshing = False

    def _use_powerpoint(self):
        return not self.dry_run and self._cfg().get("control_method") == "auto"

    @property
    def showing(self):
        return self.ppt["showing"] if self.ppt["running"] else self.keys.showing

    def _send(self, action):
        if action == "none":
            return None
        if self._use_powerpoint():
            done = self.powerpoint.send(action)
            if done:
                self.ppt = self.powerpoint.status()
                return done, "powerpoint"
        done = self.keys.send(action)
        return (done, "keyboard") if done else None

    def send(self, action: str) -> Future:
        """Returns a future resolving to (action, "powerpoint"|"keyboard") or None."""
        return self._pool.submit(self._send, action)

    def send_wait(self, action: str, timeout=5.0):
        return self.send(action).result(timeout)

    def refresh_status(self):
        """Refreshes the PowerPoint slide status in the background (rate limited)."""
        now = time.monotonic()
        if self._refreshing or now - self._last_refresh < STATUS_INTERVAL:
            return
        self._last_refresh = now
        if not self._use_powerpoint():
            self.ppt = dict(PowerPointController.NOT_RUNNING)
            return
        self._refreshing = True

        def refresh():
            try:
                self.ppt = self.powerpoint.status()
            finally:
                self._refreshing = False

        self._pool.submit(refresh)

    def close(self):
        self._pool.shutdown(wait=False)
