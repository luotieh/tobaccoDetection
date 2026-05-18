from dataclasses import dataclass
from pathlib import Path

import cv2

from app.config import settings


@dataclass
class VideoFrame:
    image: object
    frame_no: int
    timestamp: str


def format_timestamp(seconds: float) -> str:
    ms = int((seconds - int(seconds)) * 1000)
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def sample_video(path: Path, sample_fps: float | None = None, max_seconds: int | None = None) -> tuple[list[VideoFrame], float]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError("VIDEO_OPEN_FAILED")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    duration = frame_count / fps if fps else 0
    limit = min(duration, float(max_seconds or settings.max_video_seconds))
    step = max(1, int(fps / max(sample_fps or settings.video_sample_fps, 0.1)))
    frames: list[VideoFrame] = []
    frame_no = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        ts_seconds = frame_no / fps
        if ts_seconds > limit:
            break
        if frame_no % step == 0:
            frames.append(VideoFrame(image=frame, frame_no=frame_no, timestamp=format_timestamp(ts_seconds)))
        frame_no += 1
    cap.release()
    return frames, round(duration, 3)
