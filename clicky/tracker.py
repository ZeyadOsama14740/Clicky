import logging
import sys
import urllib.request
from pathlib import Path

from .config import config_dir
from .gestures import HandObservation

log = logging.getLogger(__name__)

MODEL_NAME = "hand_landmarker.task"
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)


def model_bytes() -> bytes:
    """Load the hand model bundled with the app, downloading it on first run if missing."""
    candidates = [Path(__file__).parent / "assets" / MODEL_NAME, config_dir() / MODEL_NAME]
    if getattr(sys, "_MEIPASS", None):
        candidates.insert(0, Path(sys._MEIPASS) / "clicky" / "assets" / MODEL_NAME)
    for path in candidates:
        if path.is_file():
            return path.read_bytes()
    target = candidates[-1]
    log.info("Downloading hand model to %s", target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(MODEL_URL, timeout=60) as resp:
        data = resp.read()
    target.write_bytes(data)
    return data


class HandTracker:
    def __init__(self, detection_confidence=0.6, tracking_confidence=0.5, video=True):
        from mediapipe.tasks.python import BaseOptions, vision

        self._video = video
        options = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_buffer=model_bytes()),
            running_mode=vision.RunningMode.VIDEO if video else vision.RunningMode.IMAGE,
            num_hands=2,
            min_hand_detection_confidence=detection_confidence,
            min_hand_presence_confidence=detection_confidence,
            min_tracking_confidence=tracking_confidence,
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)
        self._last_ts = -1

    def process(self, rgb, timestamp_ms: int | None = None, mirror=True) -> list[HandObservation]:
        """`rgb` is the camera frame as an HxWx3 uint8 array, as delivered by the camera.

        MediaPipe reports handedness correctly for an un-mirrored camera frame. With
        `mirror` the returned image coordinates are flipped horizontally into selfie view,
        so "left" on screen is the user's left."""
        import mediapipe as mp

        h, w = rgb.shape[:2]
        aspect = w / h
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        if self._video:
            ts = max(int(timestamp_ms), self._last_ts + 1)
            self._last_ts = ts
            result = self._landmarker.detect_for_video(image, ts)
        else:
            result = self._landmarker.detect(image)
        hands = []
        for i, lms in enumerate(result.hand_landmarks):
            category = result.handedness[i][0]
            world = None
            if result.hand_world_landmarks:
                world = [(p.x, p.y, p.z) for p in result.hand_world_landmarks[i]]
            hands.append(
                HandObservation(
                    label=category.category_name,
                    image=[((1.0 - p.x if mirror else p.x) * aspect, p.y, p.z * aspect) for p in lms],
                    world=world,
                    score=category.score,
                )
            )
        return hands

    def close(self):
        self._landmarker.close()
