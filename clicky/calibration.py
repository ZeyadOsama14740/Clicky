"""Measures the user's own pinch and swipe to suggest sensitivity settings."""

from .config import LIMITS
from .gestures import finger_states, hand_size, palm_center, pinch_ratio

PHASES = ("open", "pinch", "swipe")
MIN_SAMPLES = 10


def percentile(values, q):
    vals = sorted(values)
    if not vals:
        return 0.0
    k = (len(vals) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (k - lo)


def _clamp(key, value, digits=2):
    lo, hi = LIMITS[key]
    return round(min(max(value, lo), hi), digits)


def propose_pinch(open_ratios, touch_ratios):
    """Thresholds between the user's touching and relaxed thumb-index distance."""
    if len(open_ratios) < MIN_SAMPLES or len(touch_ratios) < MIN_SAMPLES:
        return None, "مفيش صور كفاية للإيد. اتأكد إن إيدك باينة كويس في الكاميرا وعيد الخطوة."
    touch_hi = percentile(touch_ratios, 0.9)
    open_lo = percentile(open_ratios, 0.1)
    gap = open_lo - touch_hi
    if gap < 0.08:
        return (
            None,
            "مش قادر أفرق بين اللمسة والإيد المفتوحة. قرّب من الكاميرا شوية أو نوّر المكان وعيد المعايرة.",
        )
    return {
        "pinch_on": _clamp("pinch_on", touch_hi + 0.35 * gap),
        "pinch_off": _clamp("pinch_off", touch_hi + 0.65 * gap),
    }, None


def find_strokes(samples, min_distance=1.0):
    """Splits (t, x, size) samples into one-directional strokes.

    Returns (distance in hand sizes, duration of the middle 80% of the stroke) per stroke."""
    if len(samples) < 3:
        return []
    xs = [s[1] for s in samples]
    smooth = [sum(xs[max(0, i - 1) : i + 2]) / len(xs[max(0, i - 1) : i + 2]) for i in range(len(xs))]
    strokes, start, direction = [], 0, 0
    for i in range(1, len(smooth)):
        step = smooth[i] - smooth[i - 1]
        jitter = 0.05 * samples[i][2]
        if abs(step) < jitter:
            continue
        d = 1 if step > 0 else -1
        if direction == 0:
            direction = d
        elif d != direction:
            strokes.append((start, i - 1))
            start, direction = i - 1, d
    strokes.append((start, len(smooth) - 1))

    result = []
    for a, b in strokes:
        seg = samples[a : b + 1]
        size = sum(s[2] for s in seg) / len(seg)
        x0, x1 = smooth[a], smooth[b]
        dist = abs(x1 - x0) / size
        if dist < min_distance:
            continue
        t10 = t90 = None
        for k in range(a, b + 1):
            frac = abs(smooth[k] - x0) / abs(x1 - x0)
            if t10 is None and frac >= 0.1:
                t10 = samples[k][0]
            if t90 is None and frac >= 0.9:
                t90 = samples[k][0]
        result.append((dist, max(t90 - t10, 1e-3)))
    return result


def propose_swipe(strokes):
    if len(strokes) < 2:
        return None, "ملقتش سحبات كفاية. اسحب إيدك المفتوحة يمين وشمال 3 مرات على الأقل."
    dist = percentile([s[0] for s in strokes], 0.5)
    dur = percentile([s[1] for s in strokes], 0.5)
    return {
        "swipe_distance": _clamp("swipe_distance", 0.6 * dist, 1),
        "swipe_window": _clamp("swipe_window", max(1.5 * dur, 0.3)),
    }, None


def propose_min_size(sizes):
    if len(sizes) < MIN_SAMPLES:
        return None
    return {"min_hand_size": _clamp("min_hand_size", 0.5 * percentile(sizes, 0.5), 3)}


class Calibrator:
    def __init__(self):
        self.phase = None
        self.samples = {p: [] for p in PHASES}
        self.live = {"hand": False}

    def start(self, phase):
        if phase not in PHASES:
            raise ValueError(phase)
        self.samples[phase] = []
        self.phase = phase

    def stop(self):
        self.phase = None

    def feed(self, hands, t):
        if not hands:
            self.live = {"hand": False}
            return
        obs = max(hands, key=lambda h: hand_size(h.image))
        shape = obs.shape
        ratio = pinch_ratio(shape)
        extended = sum(1 for f in finger_states(shape) if f == 1)
        size = hand_size(obs.image)
        x, y = palm_center(obs.image)
        self.live = {"hand": True, "ratio": round(ratio, 2), "extended": extended, "size": round(size, 3)}
        if self.phase:
            self.samples[self.phase].append((t, ratio, x, y, size, extended))

    def status(self):
        return {
            "phase": self.phase,
            "live": self.live,
            "counts": {p: len(v) for p, v in self.samples.items()},
        }

    def propose(self):
        values, messages = {}, []
        pinch, err = propose_pinch(
            [s[1] for s in self.samples["open"]], [s[1] for s in self.samples["pinch"]]
        )
        if pinch:
            values.update(pinch)
        else:
            messages.append(err)
        swipe, err = propose_swipe(find_strokes([(s[0], s[2], s[4]) for s in self.samples["swipe"]]))
        if swipe:
            values.update(swipe)
        else:
            messages.append(err)
        size = propose_min_size([s[4] for s in self.samples["open"] + self.samples["pinch"]])
        if size:
            values.update(size)
        return {"values": values, "messages": messages}
