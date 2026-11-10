from clicky.actions import KeySender
from clicky.app import ClickyApp
from clicky.config import DEFAULTS, ConfigStore
from clicky.web import create_app


def make_client(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    sender = KeySender(dry_run=True)
    app = ClickyApp(store, sender)
    return create_app(app).test_client(), app, sender


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
    assert client.post("/api/lock", json={}).get_json()["locked"] is True
    assert app.engine.locked
    assert client.get("/api/status").get_json()["locked"] is True
