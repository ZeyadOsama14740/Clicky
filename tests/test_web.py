from clicky.app import ClickyApp
from clicky.config import DEFAULTS, ConfigStore
from clicky.web import create_app


def make_client(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    app = ClickyApp(store, dry_run=True)
    return create_app(app).test_client(), app, app.sender


def test_settings_page_and_meta(tmp_path):
    client, _, _ = make_client(tmp_path)
    assert client.get("/").status_code == 200
    meta = client.get("/api/meta").get_json()
    assert list(meta["gestures"])[0] == "right_pinch"


def test_config_update_is_validated_and_saved(tmp_path):
    client, app, _ = make_client(tmp_path)
    cfg = client.post(
        "/api/config",
        json={"mode": "far", "cooldown": 99, "bogus": 1, "actions": {"right_pinch": "black", "x": "next"}},
    ).get_json()
    assert cfg["mode"] == "far"
    assert cfg["cooldown"] == 5.0
    assert "bogus" not in cfg
    assert cfg["actions"]["right_pinch"] == "black"
    assert app.cfg["mode"] == "far"
    assert ConfigStore(tmp_path / "config.json").get()["mode"] == "far"
    assert client.post("/api/config", json={"mode": "nope"}).get_json()["mode"] == "far"
    assert client.post("/api/config/reset").get_json() == DEFAULTS


def test_test_action_and_lock(tmp_path):
    client, app, sender = make_client(tmp_path)
    assert client.post("/api/test/toggle_show").get_json()["sent"] == "start_show"
    assert client.post("/api/test/toggle_show").get_json()["sent"] == "end_show"
    assert client.post("/api/test/nope").status_code == 404
    events = client.get("/api/status").get_json()["events"]
    assert [e["action"] for e in events[:2]] == ["end_show", "start_show"]
    assert events[0]["gesture"] == "manual_test"
    assert events[0]["channel"] == "keyboard"
    assert app.last_action[1] == "end_show"
    assert client.post("/api/lock", json={}).get_json()["locked"] is True
    assert app.engine.locked
    assert client.get("/api/status").get_json()["locked"] is True


def test_calibration_flow(tmp_path):
    from clicky.gestures import HandObservation
    from tests.handgen import make_hand

    client, app, _ = make_client(tmp_path)
    assert client.post("/api/calibration/phase/open").status_code == 400
    client.post("/api/calibration/begin")
    assert client.get("/api/status").get_json()["calibrating"] is True
    t = 0.0
    for phase, pose in (("open", "open"), ("pinch", "pinch")):
        client.post(f"/api/calibration/phase/{phase}")
        for _ in range(30):
            app.calibrator.feed([HandObservation("Right", make_hand(pose))], t)
            t += 1 / 30
        client.post("/api/calibration/stop")
    client.post("/api/calibration/phase/swipe")
    for k in range(90):
        phase_x = (k % 30) / 29
        x = 0.4 + 0.5 * (phase_x if (k // 30) % 2 == 0 else 1 - phase_x)
        app.calibrator.feed([HandObservation("Right", make_hand("open", cx=x))], t)
        t += 1 / 30
    client.post("/api/calibration/stop")
    status = client.get("/api/calibration").get_json()
    assert status["counts"] == {"open": 30, "pinch": 30, "swipe": 90}
    proposal = client.post("/api/calibration/propose").get_json()
    assert proposal["messages"] == []
    assert set(proposal["values"]) == {
        "pinch_on",
        "pinch_off",
        "swipe_distance",
        "swipe_window",
        "min_hand_size",
    }
    assert proposal["values"]["pinch_on"] < proposal["values"]["pinch_off"]
    assert proposal["current"]["pinch_on"] == 0.25
    client.post("/api/calibration/end")
    assert app.calibrator is None
