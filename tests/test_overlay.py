from clicky.config import DEFAULTS, validate
from clicky.overlay import overlay_state


def status(**kw):
    base = {"camera_ok": True, "locked": False, "hands": {}}
    base.update(kw)
    return base


def test_overlay_priorities():
    assert overlay_state(status(camera_ok=False, locked=True), None, 0) == ("error", None)
    assert overlay_state(status(locked=True), (0, "next"), 0) == ("locked", "lock")
    assert overlay_state(status(), (10.0, "next"), 10.5) == ("action", "next")
    assert overlay_state(status(), (10.0, "next"), 20.0) == ("none", None)
    hands = {"Left": {"pose": "open"}, "Right": {"pose": "pinch"}}
    assert overlay_state(status(hands=hands), None, 0) == ("pinch", None)
    assert overlay_state(status(hands={"Left": {"pose": "open"}}), None, 0) == ("hand", None)


def test_new_settings_are_validated():
    cfg = validate(
        {
            "control_method": "bogus",
            "overlay_position": "bottom-left",
            "overlay_opacity": 5,
            "overlay_enabled": False,
        },
        DEFAULTS,
    )
    assert cfg["control_method"] == DEFAULTS["control_method"]
    assert cfg["overlay_position"] == "bottom-left"
    assert cfg["overlay_opacity"] <= 1.0
    assert cfg["overlay_enabled"] is False
