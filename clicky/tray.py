import webbrowser

from PIL import Image, ImageDraw


def make_icon(locked=False):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, 62, 62), fill=(200, 60, 60) if locked else (40, 110, 230))
    # two touching fingertips
    d.ellipse((16, 20, 34, 38), fill="white")
    d.ellipse((30, 26, 48, 44), fill="white")
    return img


def run_tray(clicky, url, on_quit):
    import pystray

    def toggle(icon, item):
        clicky.set_locked(not clicky.engine.locked)

    def quit_(icon, item):
        icon.stop()
        on_quit()

    menu = pystray.Menu(
        pystray.MenuItem("الإعدادات / Settings", lambda i, it: webbrowser.open(url), default=True),
        pystray.MenuItem("إيقاف مؤقت / Pause", toggle, checked=lambda item: clicky.engine.locked),
        pystray.MenuItem("خروج / Quit", quit_),
    )
    icon = pystray.Icon("Clicky", make_icon(), "Clicky", menu)
    clicky.lock_listeners.append(lambda locked: setattr(icon, "icon", make_icon(locked)))
    icon.run()
