import cv2
import numpy as np

from app.config import settings
from app.services.pipeline import VisionPipeline


def _write_video(path, fps=10, frames=20, size=(64, 48)):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, size)
    assert writer.isOpened()
    for i in range(frames):
        writer.write(np.full((size[1], size[0], 3), i % 256, dtype=np.uint8))
    writer.release()


def test_infer_video_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "use_mock_model", True)
    video = tmp_path / "clip.avi"
    _write_video(video, fps=10, frames=20)
    pipeline = VisionPipeline()
    result = pipeline.infer_video(video, content_id="vid_e2e", sample_fps=1.0)
    assert result.media_type == "video"
    assert result.sampled_frames > 0
    assert result.duration_seconds > 0
    assert result.risk_level in {"high", "medium", "low", "none"}
    # mock 每帧返回相同 bbox 的烟盒 -> 去重为 1
    assert len(result.detected_objects) == 1
