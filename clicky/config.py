import copy
import json
import os
import sys
import threading
from pathlib import Path

ACTIONS = {
    "none": "لا شيء",
    "next": "السلايد اللي بعده",
    "prev": "السلايد اللي قبله",
    "toggle_show": "تشغيل/إنهاء العرض",
    "start_show": "تشغيل العرض من الأول (F5)",
    "start_from_current": "تشغيل العرض من السلايد الحالي (Shift+F5)",
    "end_show": "إنهاء العرض (Esc)",
    "black": "شاشة سودا (B)",
    "white": "شاشة بيضا (W)",
}

GESTURES = {
    "right_pinch": "لمسة إبهام + سبابة (يمين)",
    "left_pinch": "لمسة إبهام + سبابة (شمال)",
    "right_double_pinch": "لمستين ورا بعض (يمين)",
    "left_double_pinch": "لمستين ورا بعض (شمال)",
    "swipe_left": "سحب الإيد ناحية الشمال (وضع بعيد)",
    "swipe_right": "سحب الإيد ناحية اليمين (وضع بعيد)",
    "open_palm_hold": "كف مفتوح ثابت",
}

MODES = ("near", "far", "both")

DEFAULTS = {
    "camera_index": 0,
    "camera_width": 1280,
    "camera_height": 720,
    "camera_mirrored": False,
    "mode": "both",
    "pinch_on": 0.25,
    "pinch_off": 0.40,
    "tap_max": 0.6,
    "double_window": 0.4,
    "cooldown": 0.8,
    "swipe_distance": 2.5,
    "swipe_window": 0.5,
    "swipe_return_block": 1.0,
    "lock_enabled": True,
    "lock_hold": 1.0,
    "palm_hold": 1.5,
    "min_hand_size": 0.04,
    "detection_confidence": 0.6,
    "tracking_confidence": 0.5,
    "web_port": 8765,
    "open_settings_on_start": True,
    "actions": {
        "right_pinch": "next",
        "left_pinch": "prev",
        "right_double_pinch": "toggle_show",
        "left_double_pinch": "toggle_show",
        "swipe_left": "next",
        "swipe_right": "prev",
        "open_palm_hold": "black",
    },
}

# (min, max) for numeric settings; used to validate input from the settings page.
LIMITS = {
    "camera_index": (0, 10),
    "camera_width": (320, 3840),
    "camera_height": (240, 2160),
    "pinch_on": (0.05, 1.0),
    "pinch_off": (0.1, 1.5),
    "tap_max": (0.1, 3.0),
    "double_window": (0.1, 1.5),
    "cooldown": (0.0, 5.0),
    "swipe_distance": (0.5, 10.0),
    "swipe_window": (0.1, 2.0),
    "swipe_return_block": (0.0, 5.0),
    "lock_hold": (0.3, 5.0),
    "palm_hold": (0.3, 5.0),
    "min_hand_size": (0.0, 0.5),
    "detection_confidence": (0.1, 0.95),
    "tracking_confidence": (0.1, 0.95),
    "web_port": (1024, 65535),
}


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "Clicky"


def validate(data: dict, base: dict) -> dict:
    """Merge `data` onto `base`, ignoring unknown keys and coercing/clamping values."""
    result = copy.deepcopy(base)
    for key, value in data.items():
        if key not in DEFAULTS:
            continue
        default = DEFAULTS[key]
        if key == "actions":
            if isinstance(value, dict):
                for g, a in value.items():
                    if g in GESTURES and a in ACTIONS:
                        result["actions"][g] = a
        elif key == "mode":
            if value in MODES:
                result[key] = value
        elif isinstance(default, bool):
            result[key] = bool(value)
        elif isinstance(default, (int, float)):
            try:
                num = type(default)(float(value))
            except (TypeError, ValueError):
                continue
            lo, hi = LIMITS.get(key, (None, None))
            if lo is not None:
                num = type(default)(min(max(num, lo), hi))
            result[key] = num
    if result["pinch_off"] <= result["pinch_on"]:
        result["pinch_off"] = round(result["pinch_on"] + 0.1, 3)
    return result


class ConfigStore:
    def __init__(self, path: Path | None = None):
        self.path = path or config_dir() / "config.json"
        self._lock = threading.Lock()
        self._data = copy.deepcopy(DEFAULTS)
        self._listeners = []
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                self._data = validate(json.load(f), DEFAULTS)
        except (OSError, ValueError):
            self._data = copy.deepcopy(DEFAULTS)

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def get(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data)

    def __getitem__(self, key):
        with self._lock:
            return self._data[key]

    def update(self, data: dict) -> dict:
        with self._lock:
            old = self._data
            self._data = validate(data, old)
            new = copy.deepcopy(self._data)
        self.save()
        for fn in self._listeners:
            fn(old, new)
        return new

    def reset(self) -> dict:
        return self.update(copy.deepcopy(DEFAULTS))

    def on_change(self, fn):
        self._listeners.append(fn)
