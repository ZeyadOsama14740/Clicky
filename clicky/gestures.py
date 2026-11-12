"""Turns per-frame hand landmarks into deliberate gesture events.

Landmarks follow the MediaPipe 21-point hand model. Image landmarks are expected in
units where the frame height is 1.0 (x scaled by width/height) so distances are not
distorted by the aspect ratio.
"""

import math
from collections import deque
from dataclasses import dataclass, field

WRIST = 0
THUMB_TIP = 4
INDEX_TIP = 8
MIDDLE_MCP = 9
# (tip, pip) for index, middle, ring, pinky
FINGERS = ((8, 6), (12, 10), (16, 14), (20, 18))
PALM = (0, 5, 9, 13, 17)

HAND_TIMEOUT = 0.3
SETTLE = 0.15  # wait after a tap to make sure the hand is not closing into a fist
FIST_GUARD = 0.3


def dist(a, b):
    return math.sqrt(sum((p - q) ** 2 for p, q in zip(a, b)))


@dataclass
class HandObservation:
    label: str  # "Right" or "Left" as reported by MediaPipe for an un-mirrored frame
    image: list  # 21 (x, y, z) points in selfie (mirrored) view, frame height == 1.0
    world: list | None = None  # 21 (x, y, z) points in metres, if available
    score: float = 1.0

    @property
    def shape(self):
        return self.world or self.image


def hand_size(lm):
    return dist(lm[WRIST], lm[MIDDLE_MCP]) or 1e-6


def pinch_ratio(lm):
    return dist(lm[THUMB_TIP], lm[INDEX_TIP]) / hand_size(lm)


def finger_states(lm):
    """Per finger (index..pinky): 1 extended, -1 curled, 0 in between."""
    w = lm[WRIST]
    states = []
    for tip, pip in FINGERS:
        dt, dp = dist(lm[tip], w), dist(lm[pip], w)
        if dt > dp * 1.15:
            states.append(1)
        elif dt < dp * 0.95:
            states.append(-1)
        else:
            states.append(0)
    return states


def palm_center(lm):
    n = len(PALM)
    return tuple(sum(lm[i][k] for i in PALM) / n for k in range(2))


def classify(lm, pinching_before=False, pinch_on=0.25, pinch_off=0.4):
    """Returns one of "fist", "pinch", "open", "other"."""
    fingers = finger_states(lm)
    if all(s == -1 for s in fingers):
        return "fist"
    ratio = pinch_ratio(lm)
    if ratio < (pinch_off if pinching_before else pinch_on):
        return "pinch"
    if all(s == 1 for s in fingers):
        return "open"
    return "other"


@dataclass
class Event:
    gesture: str  # a key of config.GESTURES, or "lock" / "unlock"
    hand: str = ""
    t: float = 0.0


@dataclass
class HandState:
    last_seen: float = 0.0
    pose: str = "none"
    pose_since: float = 0.0
    pose_start_pos: tuple = (0.0, 0.0)
    pose_fired: bool = False
    pinch_start: float | None = None
    pinch_start_pos: tuple = (0.0, 0.0)
    pinch_max_move: float = 0.0
    pending_tap: float | None = None
    history: deque = field(default_factory=lambda: deque(maxlen=90))
    size: float = 0.0
    ratio: float = 0.0
    last_fist_t: float = -1e9


class GestureEngine:
    def __init__(self, config_getter):
        self._cfg = config_getter
        self.hands: dict[str, HandState] = {}
        self.locked = False
        self.last_action_t = -1e9
        self.swipe_block: tuple[str, float] = ("", -1e9)

    def set_locked(self, locked: bool):
        self.locked = locked
        for h in self.hands.values():
            h.pending_tap = None

    def reset(self):
        self.hands.clear()

    def status(self):
        return {
            label: {"pose": h.pose, "pinch": round(h.ratio, 2), "size": round(h.size, 3)}
            for label, h in self.hands.items()
        }

    # ------------------------------------------------------------------
    def update(self, observations: list[HandObservation], t: float) -> list[Event]:
        cfg = self._cfg()
        events: list[Event] = []
        seen = set()
        for obs in observations:
            label = obs.label
            if cfg.get("camera_mirrored"):
                label = "Left" if label == "Right" else "Right"
            if label in seen:
                continue
            size = hand_size(obs.image)
            if size < cfg["min_hand_size"]:
                continue
            seen.add(label)
            state = self.hands.setdefault(label, HandState())
            if t - state.last_seen > HAND_TIMEOUT:
                self._reset_hand(state)
            state.last_seen = t
            state.size = size
            self._process_hand(label, state, obs, t, cfg, events)

        for label, state in list(self.hands.items()):
            if label not in seen and t - state.last_seen > HAND_TIMEOUT:
                self._flush_pending(label, state, t, cfg, events, force=True)
                del self.hands[label]
            else:
                self._flush_pending(label, state, t, cfg, events)
        return events

    def _reset_hand(self, s: HandState):
        s.pose = "none"
        s.pending_tap = None
        s.pose_fired = False
        s.pinch_start = None
        s.history.clear()

    def _emit(self, events, gesture, hand, t, cfg, *, bypass_lock=False):
        if not bypass_lock:
            if self.locked:
                return False
            if cfg["actions"].get(gesture, "none") == "none":
                return False
            if t - self.last_action_t < cfg["cooldown"]:
                return False
            self.last_action_t = t
        events.append(Event(gesture, hand, t))
        return True

    def _process_hand(self, label, s: HandState, obs, t, cfg, events):
        shape = obs.shape
        center = palm_center(obs.image)
        size = s.size
        s.ratio = pinch_ratio(shape)
        pose = classify(shape, s.pose == "pinch", cfg["pinch_on"], cfg["pinch_off"])
        mode = cfg["mode"]
        near = mode in ("near", "both")
        far = mode in ("far", "both")

        if pose != s.pose:
            if s.pose == "pinch" and s.pinch_start is not None:
                self._on_pinch_release(label, s, t, cfg, events)
            s.pose = pose
            s.pose_since = t
            s.pose_start_pos = center
            s.pose_fired = False
            if pose == "pinch":
                s.pinch_start = t
                s.pinch_start_pos = center
                s.pinch_max_move = 0.0

        if pose == "fist":
            s.last_fist_t = t
        held = t - s.pose_since
        moved = dist(center, s.pose_start_pos) / size

        if pose == "pinch" and s.pinch_start is not None:
            s.pinch_max_move = max(s.pinch_max_move, dist(center, s.pinch_start_pos) / size)
            if not near:
                s.pinch_start = None

        if pose == "fist" and cfg["lock_enabled"] and not s.pose_fired and held >= cfg["lock_hold"]:
            s.pose_fired = True
            self.set_locked(not self.locked)
            self._emit(events, "lock" if self.locked else "unlock", label, t, cfg, bypass_lock=True)

        if pose == "open":
            if moved > 0.6:
                s.pose_since, s.pose_start_pos = t, center
            elif not s.pose_fired and held >= cfg["palm_hold"]:
                s.pose_fired = True
                self._emit(events, "open_palm_hold", label, t, cfg)

        if far:
            self._detect_swipe(label, s, shape, center, t, cfg, events)

    def _double_enabled(self, label, cfg):
        return cfg["actions"].get(f"{label.lower()}_double_pinch", "none") != "none"

    def _on_pinch_release(self, label, s: HandState, t, cfg, events):
        start, s.pinch_start = s.pinch_start, None
        if t - start > cfg["tap_max"] or s.pinch_max_move > 1.0 or self.locked:
            return
        if start - s.last_fist_t < FIST_GUARD:
            return  # fingers opening out of a fist
        if (
            self._double_enabled(label, cfg)
            and s.pending_tap is not None
            and start - s.pending_tap <= cfg["double_window"]
        ):
            s.pending_tap = None
            self._emit(events, f"{label.lower()}_double_pinch", label, t, cfg)
            return
        s.pending_tap = t

    def _flush_pending(self, label, s: HandState, t, cfg, events, force=False):
        if s.pending_tap is None:
            return
        if s.pose == "fist" or t - s.last_fist_t < FIST_GUARD:
            s.pending_tap = None  # fingers were closing into a fist, not tapping
            return
        double = self._double_enabled(label, cfg)
        wait = max(cfg["double_window"], SETTLE) if double else SETTLE
        if not force and t - s.pending_tap <= wait:
            return
        if not force and double and s.pinch_start is not None:
            return  # second pinch started inside the window; resolved on its release
        s.pending_tap = None
        self._emit(events, f"{label.lower()}_pinch", label, t, cfg)

    def _detect_swipe(self, label, s: HandState, shape, center, t, cfg, events):
        extended = sum(1 for f in finger_states(shape) if f == 1)
        if s.pose in ("pinch", "fist") or extended < 3:
            s.history.clear()
            return
        s.history.append((t, center[0], center[1], s.size))
        window = cfg["swipe_window"]
        while s.history and t - s.history[0][0] > window:
            s.history.popleft()
        if len(s.history) < 3:
            return
        t0, x0, y0, _ = s.history[0]
        mean_size = sum(h[3] for h in s.history) / len(s.history)
        dx, dy = center[0] - x0, center[1] - y0
        if abs(dx) / mean_size < cfg["swipe_distance"] or abs(dx) < 2 * abs(dy):
            return
        gesture = "swipe_left" if dx < 0 else "swipe_right"
        blocked_dir, until = self.swipe_block
        s.history.clear()
        if gesture != blocked_dir and t < until:
            return  # the hand coming back after the previous swipe
        if self._emit(events, gesture, label, t, cfg):
            self.swipe_block = (gesture, t + cfg["swipe_return_block"])
