import numpy as np

from app.config import settings
from app.services.detector import TobaccoDetector


def test_predict_batch_mock_maps_timestamps(monkeypatch):
    monkeypatch.setattr(settings, "use_mock_model", True)
    detector = TobaccoDetector()
    images = [np.zeros((40, 60, 3), dtype=np.uint8) for _ in range(3)]
    timestamps = ["00:00:00.000", "00:00:01.000", "00:00:02.000"]
    batch = detector.predict_batch(images, timestamps=timestamps)
    assert len(batch) == 3
    assert all(len(frame_dets) == 1 for frame_dets in batch)
    assert [dets[0].timestamp for dets in batch] == timestamps


def test_predict_image_uses_batch(monkeypatch):
    monkeypatch.setattr(settings, "use_mock_model", True)
    detector = TobaccoDetector()
    dets = detector.predict_image(np.zeros((40, 60, 3), dtype=np.uint8), timestamp="00:00:05.000")
    assert len(dets) == 1
    assert dets[0].timestamp == "00:00:05.000"
    assert dets[0].class_name == "cigarette_pack"
