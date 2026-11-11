import argparse
import logging
import sys
import webbrowser
from pathlib import Path

from .config import ConfigStore, config_dir


def setup_logging(verbose=False):
    handlers = []
    try:
        config_dir().mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(config_dir() / "clicky.log", encoding="utf-8"))
    except OSError:
        pass
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def selftest(image_path: str) -> int:
    """Checks the bundled app can load everything it needs; used by CI on the built exe."""
    log = logging.getLogger("selftest")
    try:
        import cv2

        from .app import ClickyApp
        from .tracker import HandTracker
        from .web import create_app

        frame = cv2.imread(image_path)
        if frame is None:
            raise RuntimeError(f"cannot read {image_path}")
        tracker = HandTracker(video=False)
        hands = tracker.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        tracker.close()
        if not hands:
            raise RuntimeError("no hands detected in test image")
        store = ConfigStore(Path(config_dir() / "selftest-config.json"))
        app = ClickyApp(store, dry_run=True)
        client = create_app(app).test_client()
        if client.get("/").status_code != 200 or client.get("/api/meta").status_code != 200:
            raise RuntimeError("settings page failed")
        if sys.platform == "win32":
            import tkinter  # noqa: F401

            import pystray  # noqa: F401
            import pythoncom  # noqa: F401
            import win32com.client  # noqa: F401
            from pynput.keyboard import Controller  # noqa: F401

        log.info("SELFTEST OK: %d hand(s): %s", len(hands), [h.label for h in hands])
        return 0
    except Exception:
        log.exception("SELFTEST FAILED")
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(prog="clicky", description="Control presentations with hand gestures")
    parser.add_argument("--no-tray", action="store_true", help="run without the system tray icon")
    parser.add_argument("--no-browser", action="store_true", help="don't open the settings page on start")
    parser.add_argument("--no-overlay", action="store_true", help="don't show the on-screen indicator")
    parser.add_argument("--dry-run", action="store_true", help="detect gestures but don't press keys")
    parser.add_argument("--config", type=Path, help="path to config.json")
    parser.add_argument("--selftest", metavar="IMAGE", help="check the installation using a hand photo")
    parser.add_argument("--video", help=argparse.SUPPRESS)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    setup_logging(args.verbose)

    if args.selftest:
        return selftest(args.selftest)

    from .app import ClickyApp
    from .overlay import Overlay
    from .web import WebServer

    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    store = ConfigStore(args.config)
    port = store["web_port"]
    clicky = ClickyApp(store, dry_run=args.dry_run)
    clicky.video_path = args.video
    try:
        server = WebServer(clicky, port)
    except OSError:
        # Most likely Clicky is already running: just show its settings page.
        webbrowser.open(f"http://127.0.0.1:{port}/")
        return 0
    server.start()
    clicky.start()
    overlay = None if args.no_overlay else Overlay(clicky)
    if overlay:
        overlay.start()
    logging.getLogger(__name__).info("Settings page: %s", server.url)
    if store["open_settings_on_start"] and not args.no_browser:
        webbrowser.open(server.url)

    def shutdown():
        if overlay:
            overlay.stop()
        clicky.stop()
        server.stop()

    try:
        if args.no_tray:
            clicky.wait()
        else:
            from .tray import run_tray

            run_tray(clicky, server.url, shutdown)
    except KeyboardInterrupt:
        pass
    finally:
        shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
