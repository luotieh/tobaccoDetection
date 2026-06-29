import cv2
import numpy as np
import pytest

from app.services.video import FrameSampler, VideoFrame


def _write_video(path, fps=10, frames=30, size=(64, 48)):
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    writer = cv2.VideoWriter(str(path), fourcc, fps, size)
    assert writer.isOpened()
    for i in range(frames):
        img = np.full((size[1], size[0], 3), i % 256, dtype=np.uint8)
        writer.write(img)
    writer.release()


def test_sample_step_and_timestamps(tmp_path):
    video = tmp_path / "clip.avi"
    _write_video(video, fps=10, frames=30)
    frames, duration = FrameSampler().sample(video, sample_fps=1.0, max_seconds=180)
    assert all(isinstance(f, VideoFrame) for f in frames)
    # 10fps, 1fps 采样 -> step=10, 帧号 0,10,20（idx30 越界）
    assert [f.frame_no for f in frames] == [0, 10, 20]
    assert [f.timestamp for f in frames] == ["00:00:00.000", "00:00:01.000", "00:00:02.000"]
    assert duration == pytest.approx(3.0, abs=0.2)


def test_max_seconds_limits_frames(tmp_path):
    video = tmp_path / "clip.avi"
    _write_video(video, fps=10, frames=30)
    frames, _ = FrameSampler().sample(video, sample_fps=1.0, max_seconds=1)
    # limit=1s -> max_frame=10 -> 帧号 0,10
    assert [f.frame_no for f in frames] == [0, 10]


def test_open_failure_raises(tmp_path):
    with pytest.raises(ValueError, match="VIDEO_OPEN_FAILED"):
        FrameSampler().sample(tmp_path / "nope.avi")
