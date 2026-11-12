"""Downloads the MediaPipe hand model into clicky/assets so it gets bundled into the exe."""

import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clicky.tracker import MODEL_NAME, MODEL_URL  # noqa: E402

target = Path(__file__).resolve().parents[1] / "clicky" / "assets" / MODEL_NAME
target.parent.mkdir(parents=True, exist_ok=True)
if not target.exists():
    print(f"Downloading {MODEL_URL}")
    urllib.request.urlretrieve(MODEL_URL, target)
print(f"Model: {target} ({target.stat().st_size} bytes)")
