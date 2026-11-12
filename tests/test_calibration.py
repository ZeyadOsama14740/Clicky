from clicky.calibration import find_strokes, propose_min_size, propose_pinch, propose_swipe


def test_propose_pinch_between_touch_and_open():
    values, err = propose_pinch([0.8, 0.9, 1.0] * 5, [0.1, 0.12, 0.15] * 5)
    assert err is None
    assert 0.15 < values["pinch_on"] < values["pinch_off"] < 0.8


def test_propose_pinch_rejects_overlap_and_missing_data():
    assert propose_pinch([0.3] * 20, [0.28] * 20)[0] is None
    assert propose_pinch([0.9] * 3, [0.1] * 3)[0] is None


def make_swipes(n, distance_px=0.5, size=0.1, fps=30, seconds=0.3):
    samples, t, x = [], 0.0, 0.3
    frames = int(seconds * fps)
    for k in range(n):
        direction = 1 if k % 2 == 0 else -1
        for _ in range(frames):
            x += direction * distance_px / frames
            samples.append((t, x, size))
            t += 1 / fps
        for _ in range(5):  # pause at the end of each stroke
            samples.append((t, x, size))
            t += 1 / fps
    return samples


def test_find_strokes_and_propose_swipe():
    strokes = find_strokes(make_swipes(4))
    assert len(strokes) == 4
    for dist, dur in strokes:
        assert 4.0 < dist < 5.5
        assert 0.15 < dur < 0.35
    values, err = propose_swipe(strokes)
    assert err is None
    assert 2.4 <= values["swipe_distance"] <= 3.3
    assert 0.3 <= values["swipe_window"] <= 0.55


def test_jitter_is_not_a_stroke():
    samples = [(i / 30, 0.5 + (0.002 if i % 2 else -0.002), 0.1) for i in range(60)]
    assert find_strokes(samples) == []
    assert propose_swipe([])[0] is None


def test_min_hand_size():
    assert propose_min_size([0.1] * 20) == {"min_hand_size": 0.05}
    assert propose_min_size([0.1]) is None
