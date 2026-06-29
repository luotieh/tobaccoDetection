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


class FrameSampler:
    def sample(
        self,
        path: Path,
        sample_fps: float | None = None,
        max_seconds: int | None = None,
    ) -> tuple[list[VideoFrame], float]:
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            raise ValueError("VIDEO_OPEN_FAILED")
        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 25
            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
            duration = frame_count / fps if fps else 0
            limit = min(duration, float(max_seconds or settings.max_video_seconds))
            step = max(1, round(fps / max(sample_fps or settings.video_sample_fps, 0.1)))
            max_frame = int(limit * fps)
            targets = list(range(0, max_frame + 1, step))
            frames = self._seek_sample(cap, targets, fps)
            if not frames and targets:
                # seek 不可靠时回退顺序读取
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                frames = self._sequential_sample(cap, step, limit, fps)
        finally:
            cap.release()
        return frames, round(duration, 3)

    def _seek_sample(self, cap, targets: list[int], fps: float) -> list[VideoFrame]:
        frames: list[VideoFrame] = []
        for idx in targets:
            if not cap.set(cv2.CAP_PROP_POS_FRAMES, idx):
                return []
            ok, frame = cap.read()
            if not ok:
                break
            frames.append(VideoFrame(image=frame, frame_no=idx, timestamp=format_timestamp(idx / fps)))
        return frames

    def _sequential_sample(self, cap, step: int, limit: float, fps: float) -> list[VideoFrame]:
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
        return frames


def sample_video(path: Path, sample_fps: float | None = None, max_seconds: int | None = None) -> tuple[list[VideoFrame], float]:
    return FrameSampler().sample(path, sample_fps=sample_fps, max_seconds=max_seconds)
