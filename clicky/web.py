import logging
import threading

import cv2
from flask import Flask, Response, jsonify, request, send_from_directory
from werkzeug.serving import make_server

from . import __version__
from .config import ACTIONS, DEFAULTS, GESTURES, LIMITS, MODES

log = logging.getLogger(__name__)


def create_app(clicky):
    app = Flask(__name__, static_folder=None)
    app.json.sort_keys = False
    static_dir = __file__.rsplit("web.py", 1)[0] + "static"

    @app.get("/")
    def index():
        return send_from_directory(static_dir, "settings.html")

    @app.get("/api/meta")
    def meta():
        return jsonify(
            version=__version__,
            actions=ACTIONS,
            gestures=GESTURES,
            limits=LIMITS,
            modes=MODES,
            defaults=DEFAULTS,
        )

    @app.get("/api/config")
    def get_config():
        return jsonify(clicky.store.get())

    @app.post("/api/config")
    def set_config():
        data = request.get_json(silent=True) or {}
        return jsonify(clicky.store.update(data))

    @app.post("/api/config/reset")
    def reset_config():
        return jsonify(clicky.store.reset())

    @app.get("/api/status")
    def status():
        return jsonify(clicky.status())

    @app.post("/api/lock")
    def lock():
        data = request.get_json(silent=True) or {}
        clicky.set_locked(bool(data.get("locked", not clicky.engine.locked)))
        return jsonify(locked=clicky.engine.locked)

    @app.post("/api/test/<action>")
    def test_action(action):
        if action not in ACTIONS:
            return jsonify(error="unknown action"), 404
        return jsonify(sent=clicky.test_action(action))

    @app.get("/api/cameras")
    def cameras():
        current = clicky.cfg["camera_index"]
        found = []
        for idx in range(5):
            if idx == current:
                found.append(idx)
                continue
            cap = cv2.VideoCapture(idx)
            if cap.isOpened():
                found.append(idx)
            cap.release()
        return jsonify(cameras=found, current=current)

    @app.get("/stream.mjpg")
    def stream():
        def frames():
            clicky.viewers += 1
            try:
                last = -1
                while True:
                    last, jpeg = clicky.next_frame(last)
                    if jpeg:
                        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
            finally:
                clicky.viewers -= 1

        return Response(frames(), mimetype="multipart/x-mixed-replace; boundary=frame")

    return app


class WebServer:
    """Settings page server, bound to localhost only."""

    def __init__(self, clicky, port):
        self.port = port
        self.url = f"http://127.0.0.1:{port}/"
        self._server = make_server("127.0.0.1", port, create_app(clicky), threaded=True)
        self._thread = threading.Thread(target=self._server.serve_forever, name="web", daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._server.shutdown()
