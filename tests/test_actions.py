from clicky.actions import PP_BLACK, PP_RUNNING, ActionSender, KeySender, PowerPointController


class FakeView:
    def __init__(self, slides, position=1):
        self.slides, self.CurrentShowPosition, self.State = slides, position, PP_RUNNING
        self.exited = False

    def Next(self):
        self.CurrentShowPosition = min(self.CurrentShowPosition + 1, self.slides)

    def Previous(self):
        self.CurrentShowPosition = max(self.CurrentShowPosition - 1, 1)

    def GotoSlide(self, i):
        self.CurrentShowPosition = i

    def Exit(self):
        self.exited = True


class Collection:
    def __init__(self, items):
        self.items = items

    @property
    def Count(self):
        return len(self.items)

    def __call__(self, i):
        return self.items[i - 1]


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class FakePowerPoint:
    def __init__(self, slides=10, current=3):
        self.pres = Obj(Slides=Obj(Count=slides))
        self.pres.SlideShowSettings = Obj(Run=self._run)
        self.Presentations = Collection([self.pres])
        self.ActivePresentation = self.pres
        self.ActiveWindow = Obj(View=Obj(Slide=Obj(SlideIndex=current)))
        self.SlideShowWindows = Collection([])

    def _run(self):
        view = FakeView(self.pres.Slides.Count)
        win = Obj(View=view, Presentation=self.pres)
        orig_exit = view.Exit

        def exit_():
            orig_exit()
            self.SlideShowWindows.items.clear()

        view.Exit = exit_
        self.SlideShowWindows.items.append(win)
        return win


def test_powerpoint_controller_drives_slideshow():
    app = FakePowerPoint()
    ppt = PowerPointController(connect=lambda: app)
    assert ppt.status() == {"running": True, "showing": False, "slide": 3, "total": 10}
    assert ppt.send("next") is None  # not in a slideshow: caller falls back to keys
    assert ppt.send("start_from_current") == "start_from_current"
    assert ppt.status() == {"running": True, "showing": True, "slide": 3, "total": 10}
    assert ppt.send("next") == "next"
    assert ppt.status()["slide"] == 4
    assert ppt.send("black") == "black"
    view = app.SlideShowWindows(1).View
    assert view.State == PP_BLACK
    assert ppt.send("prev") == "prev"  # leaves the black screen and goes back
    assert view.State == PP_RUNNING and view.CurrentShowPosition == 3
    assert ppt.send("toggle_show") == "end_show"
    assert ppt.status()["showing"] is False
    assert ppt.send("toggle_show") == "start_show"
    assert ppt.status()["slide"] == 1


def test_powerpoint_not_running_or_crashing():
    assert PowerPointController(connect=lambda: None).status()["running"] is False
    calls = []

    def connect():
        calls.append(1)
        raise OSError("RPC server unavailable")

    ppt = PowerPointController(connect=connect)
    assert ppt.send("next") is None
    assert ppt.send("next") is None
    assert len(calls) == 2  # reconnects each time after a failure


def test_action_sender_prefers_powerpoint_and_falls_back_to_keys():
    cfg = {"control_method": "auto"}
    app = FakePowerPoint()
    keys = KeySender(dry_run=True)
    sender = ActionSender(lambda: cfg, powerpoint=PowerPointController(connect=lambda: app), keys=keys)
    assert sender.send_wait("next") == ("next", "keyboard")  # no slideshow yet
    assert sender.send_wait("start_show") == ("start_show", "powerpoint")
    assert sender.showing is True
    assert sender.send_wait("next") == ("next", "powerpoint")
    assert sender.ppt["slide"] == 2
    cfg["control_method"] = "keyboard"
    assert sender.send_wait("next") == ("next", "keyboard")
    assert sender.send_wait("none") is None
    sender.close()
