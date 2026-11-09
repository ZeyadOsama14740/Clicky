import logging
import threading

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


class KeySender:
    """Sends presentation shortcuts to the focused window (PowerPoint, Google Slides, PDF...)."""

    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.showing = False
        self._lock = threading.Lock()
        self._kb = None
        self.sent: list[str] = []

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
            self.sent.append(action)
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
