from app.config import settings


def test_video_config_defaults():
    assert settings.video_track_iou == 0.5
    assert settings.video_detect_batch == 8
    assert settings.video_ocr_every_frame is True
