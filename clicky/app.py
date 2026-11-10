import logging
import sys
import threading
import time
from collections import deque

import cv2

from .actions import KeySender
from .config import ACTIONS, GESTURES, ConfigStore
from .gestures import GestureEngine
from .tracker import HandTracker

log = logging.getLogger(__name__)

HAND_CONNECTIONS = (
    (0, 1),
    (1, 2),
    (2, 3),
    (3, 4),
    (0, 5),
    (5, 6),
    (6, 7),
    (7, 8),
    (5, 9),
    (9, 10),
    (10, 11),
    (11, 12),
    (9, 13),
    (13, 14),
    (14, 15),
    (15, 16),
    (13, 17),
    (0, 17),
    (17, 18),
    (18, 19),
    (19, 20),
)
RESTART_KEYS = (
    "camera_index",
    "camera_width",
    "camera_height",
    "detection_confidence",
    "tracking_confidence",
)
PREVIEW_FPS = 15


class ClickyApp:
    def __init__(self, store: ConfigStore, sender: KeySender):
        self.store = store
        self.sender = sender
        self.cfg = store.get()
        self.engine = GestureEngine(lambda: self.cfg)
        self.events = deque(maxlen=30)
        self.fps = 0.0
        self.camera_ok = False
        self.camera_error = ""
        self.viewers = 0
        self._jpeg = None
        self._frame_id = 0
        self._frame_cond = threading.Condition()
        self._restart = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self.lock_listeners = []
        self.video_path = None  # play a video file instead of the camera (for testing)
        store.on_change(self._on_config_change)

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        self._thread = threading.Thread(target=self._loop, name="camera", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._restart.set()
        if self._thread:
            self._thread.join(timeout=3)

    def wait(self, timeout=None):
        return self._stop.wait(timeout)

    def _on_config_change(self, old, new):
        self.cfg = new
        if any(old[k] != new[k] for k in RESTART_KEYS):
            self._restart.set()

    # ------------------------------------------------------------------ public API
    def set_locked(self, locked: bool):
        self.engine.set_locked(locked)
        self._log_event("lock" if locked else "unlock", "", "")

    def test_action(self, action: str):
        sent = self.sender.send(action)
        if sent:
            self._log_event("manual_test", "", sent)
        return sent

    def status(self):
        return {
            "camera_ok": self.camera_ok,
            "camera_error": self.camera_error,
            "fps": round(self.fps, 1),
            "locked": self.engine.locked,
            "showing": self.sender.showing,
            "hands": self.engine.status(),
            "events": list(self.events)[::-1],
        }

    def next_frame(self, last_id, timeout=1.0):
        with self._frame_cond:
            if self._frame_id == last_id:
                self._frame_cond.wait(timeout)
            return self._frame_id, self._jpeg

    # ------------------------------------------------------------------ camera loop
    def _open_camera(self, cfg):
        if self.video_path:
            return cv2.VideoCapture(self.video_path)
        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        cap = cv2.VideoCapture(cfg["camera_index"], backend)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(cfg["camera_index"])
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg["camera_width"])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg["camera_height"])
        cap.set(cv2.CAP_PROP_FPS, 30)
        return cap

    def _loop(self):
        while not self._stop.is_set():
            self._restart.clear()
            cfg = self.cfg
            cap = self._open_camera(cfg)
            if not cap.isOpened():
                cap.release()
                self.camera_ok = False
                self.camera_error = f"مش قادر أفتح الكاميرا رقم {cfg['camera_index']}"
                self._restart.wait(2.0)
                continue
            try:
                tracker = HandTracker(cfg["detection_confidence"], cfg["tracking_confidence"])
            except Exception as exc:
                log.exception("Failed to load hand tracker")
                cap.release()
                self.camera_ok = False
                self.camera_error = f"فشل تحميل نموذج تتبع اليد: {exc}"
                self._restart.wait(5.0)
                continue
            self.camera_ok, self.camera_error = True, ""
            try:
                self._run(cap, tracker)
            except Exception as exc:
                log.exception("Camera loop crashed")
                self.camera_error = str(exc)
            finally:
                cap.release()
                tracker.close()
                self.engine.reset()
                self.camera_ok = False

    def _run(self, cap, tracker):
        failures = 0
        last_preview = 0.0
        frames, fps_t = 0, time.monotonic()
        while not self._stop.is_set() and not self._restart.is_set():
            ok, frame = cap.read()
            if not ok and self.video_path:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                time.sleep(0.03)
                continue
            if self.video_path:
                time.sleep(1 / 30)
            if not ok:
                failures += 1
                if failures > 30:
                    self.camera_error = "الكاميرا وقفت عن إرسال الصورة"
                    return
                time.sleep(0.05)
                continue
            failures = 0
            t = time.monotonic()
            cfg = self.cfg
            mirror = not cfg["camera_mirrored"]
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            hands = tracker.process(rgb, int(t * 1000), mirror=mirror)
            for event in self.engine.update(hands, t):
                self._handle(event, cfg)

            frames += 1
            if t - fps_t >= 1.0:
                self.fps = frames / (t - fps_t)
                frames, fps_t = 0, t
            if self.viewers > 0 and t - last_preview >= 1.0 / PREVIEW_FPS:
                last_preview = t
                self._publish_preview(frame, hands, mirror)

    def _handle(self, event, cfg):
        if event.gesture in ("lock", "unlock"):
            self._log_event(event.gesture, event.hand, "")
            return
        action = cfg["actions"].get(event.gesture, "none")
        sent = self.sender.send(action)
        self._log_event(event.gesture, event.hand, sent or action)

    def _log_event(self, gesture, hand, action):
        names = {"lock": "قفل التحكم", "unlock": "فتح التحكم", "manual_test": "زرار جرّب", **GESTURES}
        self.events.append(
            {
                "time": time.strftime("%H:%M:%S"),
                "gesture": gesture,
                "gesture_label": names.get(gesture, gesture),
                "hand": hand,
                "action": action,
                "action_label": ACTIONS.get(action, action),
            }
        )
        log.info("gesture=%s hand=%s action=%s", gesture, hand, action)
        if gesture in ("lock", "unlock"):
            for fn in self.lock_listeners:
                fn(gesture == "lock")

    def _publish_preview(self, frame, hands, mirror):
        img = cv2.flip(frame, 1) if mirror else frame.copy()
        h = img.shape[0]
        status = self.engine.status()
        for obs in hands:
            pts = [(int(x * h), int(y * h)) for x, y, _ in obs.image]
            label = obs.label
            if self.cfg["camera_mirrored"]:
                label = "Left" if label == "Right" else "Right"
            color = (80, 200, 255) if label == "Right" else (120, 255, 120)
            for a, b in HAND_CONNECTIONS:
                cv2.line(img, pts[a], pts[b], color, 2)
            for p in pts:
                cv2.circle(img, p, 3, (255, 255, 255), -1)
            info = status.get(label, {})
            text = f"{label}: {info.get('pose', '')}"
            x, y = pts[0]
            cv2.putText(img, text, (x - 40, y + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4)
            cv2.putText(img, text, (x - 40, y + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
        if self.engine.locked:
            cv2.rectangle(img, (0, 0), (img.shape[1] - 1, h - 1), (0, 0, 255), 12)
            cv2.putText(img, "LOCKED", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 255), 3)
        scale = 640 / img.shape[1]
        if scale < 1:
            img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if ok:
            with self._frame_cond:
                self._jpeg = buf.tobytes()
                self._frame_id += 1
                self._frame_cond.notify_all()
