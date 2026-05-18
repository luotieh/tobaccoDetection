from app.config import settings
from app.schemas import OCRText


class OCRService:
    def __init__(self):
        self.enabled = settings.enable_ocr
        self.engine_name = settings.ocr_engine
        self.engine = None
        self.mock = True
        if not self.enabled:
            return
        try:
            if self.engine_name == "rapidocr":
                from rapidocr_onnxruntime import RapidOCR

                self.engine = RapidOCR()
                self.mock = False
            elif self.engine_name == "paddleocr":
                from paddleocr import PaddleOCR

                self.engine = PaddleOCR(use_angle_cls=True, lang="ch")
                self.mock = False
        except Exception:
            self.engine = None
            self.mock = True

    def recognize(self, image) -> list[OCRText]:
        if not self.enabled or self.mock or self.engine is None:
            return []
        try:
            if self.engine_name == "rapidocr":
                result, _ = self.engine(image)
                return [
                    OCRText(text=item[1], confidence=float(item[2]), bbox=[float(v) for point in item[0] for v in point])
                    for item in (result or [])
                ]
            result = self.engine.ocr(image, cls=True)
            rows = result[0] if result else []
            return [
                OCRText(text=row[1][0], confidence=float(row[1][1]), bbox=[float(v) for point in row[0] for v in point])
                for row in rows
            ]
        except Exception:
            return []
