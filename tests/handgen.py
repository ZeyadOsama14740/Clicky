"""Synthetic MediaPipe-style hand landmarks for engine tests (frame height == 1)."""

MCP = {"index": (0.30, -0.95), "middle": (0.05, -1.0), "ring": (-0.18, -0.93), "pinky": (-0.38, -0.82)}
ORDER = ("index", "middle", "ring", "pinky")


def _finger(mcp, state):
    x, y = mcp
    if state == "extended":
        return [(x, y - 0.45), (x, y - 0.75), (x, y - 1.0)]
    if state == "curled":
        return [(x, y - 0.35), (x, y - 0.15), (x, y + 0.1)]
    raise ValueError(state)


def make_hand(pose="open", cx=0.9, cy=0.75, size=0.15):
    pts = [(0.0, 0.0)] * 21
    pts[0] = (0.0, 0.0)
    # thumb
    if pose in ("open", "other"):
        thumb = [(0.25, -0.2), (0.5, -0.4), (0.7, -0.55), (0.9, -0.7)]
    elif pose == "pinch":
        thumb = [(0.25, -0.2), (0.45, -0.55), (0.55, -0.9), (0.58, -1.22)]
    else:  # fist: thumb tucked across fingers
        thumb = [(0.25, -0.2), (0.35, -0.45), (0.25, -0.65), (0.1, -0.7)]
    pts[1:5] = thumb
    for i, name in enumerate(ORDER):
        base = 5 + i * 4
        pts[base] = MCP[name]
        if pose == "open":
            state = "extended"
        elif pose == "fist":
            state = "curled"
        elif pose == "other":
            state = "curled" if name in ("ring", "pinky") else "extended"
        else:
            state = "extended"
        pts[base + 1 : base + 4] = _finger(MCP[name], state)
    if pose == "pinch":
        pts[6:9] = [(0.4, -1.3), (0.5, -1.4), (0.55, -1.25)]
    return [(cx + x * size, cy + y * size, 0.0) for x, y in pts]
