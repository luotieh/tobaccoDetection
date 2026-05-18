import numpy as np
from PIL import Image


def bytes_to_bgr_image(data: bytes) -> np.ndarray:
    import cv2

    image = Image.open(__import__("io").BytesIO(data)).convert("RGB")
    rgb = np.array(image)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def bgr_to_jpeg_bytes(image: np.ndarray) -> bytes:
    import cv2

    ok, encoded = cv2.imencode(".jpg", image)
    if not ok:
        raise ValueError("failed to encode image")
    return encoded.tobytes()
