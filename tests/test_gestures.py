import copy

import pytest

from clicky.config import DEFAULTS
from clicky.gestures import GestureEngine, HandObservation, classify
from tests.handgen import make_hand

FPS = 30
DT = 1.0 / FPS


class Sim:
    def __init__(self, **overrides):
        self.cfg = copy.deepcopy(DEFAULTS)
        actions = overrides.pop("actions", {})
        self.cfg.update(overrides)
        self.cfg["actions"].update(actions)
        self.engine = GestureEngine(lambda: self.cfg)
        self.t = 0.0
        self.events = []

    def run(self, seconds, *hands):
        """hands: (label, pose, cx, cy[, cx_end]) tuples, positions interpolated over time."""
        frames = max(1, round(seconds * FPS))
        for i in range(frames):
            obs = []
            for h in hands:
                label, pose, cx, cy = h[:4]
                cx_end = h[4] if len(h) > 4 else cx
                x = cx + (cx_end - cx) * (i / max(1, frames - 1))
                obs.append(HandObservation(label, make_hand(pose, x, cy)))
            self.events += self.engine.update(obs, self.t)
            self.t += DT
        return self

    def idle(self, seconds):
        for _ in range(max(1, round(seconds * FPS))):
            self.events += self.engine.update([], self.t)
            self.t += DT
        return self

    def tap(self, label="Right", hold=0.15):
        self.run(0.2, (label, "other", 0.9, 0.7))
        self.run(hold, (label, "pinch", 0.9, 0.7))
        self.run(0.1, (label, "other", 0.9, 0.7))
        return self

    @property
    def names(self):
        return [e.gesture for e in self.events]


@pytest.mark.parametrize("pose", ["open", "fist", "pinch", "other"])
def test_classify(pose):
    assert classify(make_hand(pose)) == pose


def test_right_tap_is_next_left_tap_is_prev():
    s = Sim(actions={"right_double_pinch": "none", "left_double_pinch": "none"})
    s.tap("Right").run(0.5, ("Right", "other", 0.9, 0.7))
    assert s.names == ["right_pinch"]
    s.tap("Left").run(0.5, ("Left", "other", 0.9, 0.7))
    assert s.names == ["right_pinch", "left_pinch"]


def test_single_tap_waits_for_double_window():
    s = Sim()
    s.tap("Right")
    assert s.names == []
    s.run(0.5, ("Right", "other", 0.9, 0.7))
    assert s.names == ["right_pinch"]


def test_double_tap():
    s = Sim()
    s.tap("Right", hold=0.1)
    s.run(0.1, ("Right", "pinch", 0.9, 0.7)).run(0.6, ("Right", "other", 0.9, 0.7))
    assert s.names == ["right_double_pinch"]


def test_long_pinch_is_ignored():
    s = Sim()
    s.tap("Right", hold=1.5).run(1.0, ("Right", "other", 0.9, 0.7))
    assert s.names == []


def test_moving_hand_around_does_nothing():
    s = Sim()
    s.run(2.0, ("Right", "other", 0.2, 0.7, 0.8))
    s.run(2.0, ("Left", "open", 0.8, 0.6, 0.5))
    s.run(1.0, ("Right", "other", 0.5, 0.5))
    assert s.names == []


def test_pinch_while_moving_fast_is_ignored():
    s = Sim()
    s.run(0.2, ("Right", "other", 0.3, 0.7))
    s.run(0.3, ("Right", "pinch", 0.3, 0.7, 0.8))
    s.run(1.0, ("Right", "other", 0.8, 0.7))
    assert s.names == []


def test_closing_into_fist_is_not_a_tap():
    s = Sim(actions={"right_double_pinch": "none"})
    s.run(0.3, ("Right", "open", 0.9, 0.7))
    s.run(0.07, ("Right", "pinch", 0.9, 0.7))
    s.run(0.05, ("Right", "other", 0.9, 0.7))
    s.run(0.5, ("Right", "fist", 0.9, 0.7))
    assert "right_pinch" not in s.names


def test_fist_toggles_lock():
    s = Sim(actions={"right_double_pinch": "none"})
    s.run(1.2, ("Right", "fist", 0.9, 0.7))
    assert s.names == ["lock"] and s.engine.locked
    s.run(1.0, ("Right", "other", 0.9, 0.7))
    s.tap("Right").run(0.5, ("Right", "other", 0.9, 0.7))
    assert s.names == ["lock"]
    s.run(1.2, ("Right", "fist", 0.9, 0.7)).run(0.5, ("Right", "other", 0.9, 0.7))
    assert s.names == ["lock", "unlock"] and not s.engine.locked
    s.tap("Right").run(0.5, ("Right", "other", 0.9, 0.7))
    assert s.names == ["lock", "unlock", "right_pinch"]


def test_short_fist_does_not_lock():
    s = Sim()
    s.run(0.5, ("Right", "fist", 0.9, 0.7)).run(0.5, ("Right", "other", 0.9, 0.7))
    assert s.names == [] and not s.engine.locked


def test_open_palm_hold():
    s = Sim()
    s.run(2.0, ("Left", "open", 0.5, 0.5))
    assert s.names == ["open_palm_hold"]


def test_swipe_left_and_return_is_blocked():
    s = Sim(mode="far")
    s.run(0.3, ("Right", "open", 0.9, 0.5, 0.4))  # fast move to the left
    assert s.names == ["swipe_left"]
    s.run(0.3, ("Right", "open", 0.4, 0.5, 0.9))  # hand coming back
    assert s.names == ["swipe_left"]
    s.idle(1.5)
    s.run(0.3, ("Right", "open", 0.4, 0.5, 0.9))
    assert s.names == ["swipe_left", "swipe_right"]


def test_slow_movement_is_not_a_swipe():
    s = Sim(mode="far")
    s.run(3.0, ("Right", "open", 0.9, 0.5, 0.4))
    assert "swipe_left" not in s.names


def test_swipe_needs_open_hand():
    s = Sim(mode="far")
    s.run(0.3, ("Right", "fist", 0.9, 0.5, 0.4))
    assert s.names == []


def test_near_mode_ignores_swipes_far_mode_ignores_pinch():
    s = Sim(mode="near")
    s.run(0.3, ("Right", "open", 0.9, 0.5, 0.4)).run(0.5, ("Right", "other", 0.4, 0.5))
    assert s.names == []
    s = Sim(mode="far")
    s.tap("Right").run(1.0, ("Right", "other", 0.9, 0.7))
    assert s.names == []


def test_cooldown():
    s = Sim(actions={"right_double_pinch": "none"}, cooldown=1.0)
    s.tap("Right").tap("Right").run(0.3, ("Right", "other", 0.9, 0.7))
    assert s.names == ["right_pinch"]


def test_small_far_away_hands_ignored():
    s = Sim(min_hand_size=0.2)
    s.run(2.0, ("Left", "open", 0.5, 0.5))
    assert s.names == []


def test_mirrored_camera_swaps_hands():
    s = Sim(camera_mirrored=True, actions={"left_double_pinch": "none"})
    s.tap("Right").run(0.5, ("Right", "other", 0.9, 0.7))
    assert s.names == ["left_pinch"]


def test_hand_disappearing_flushes_pending_tap():
    s = Sim()
    s.tap("Right").idle(1.0)
    assert s.names == ["right_pinch"]


def test_disabled_gesture_emits_nothing():
    s = Sim(actions={"open_palm_hold": "none"})
    s.run(2.0, ("Left", "open", 0.5, 0.5))
    assert s.names == []
