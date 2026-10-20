"""로컬 OCR과 OpenAI 구조화를 연결하는 하이브리드 추출기."""
from __future__ import annotations
import time
from datetime import date
from pathlib import Path
from .schemas import NoticeExtraction
from .structured_llm import OpenAIStructuredLLM
from .vision_llm import OllamaVisionLLM

class NoticeExtractor:
    def __init__(self, vision_llm: OllamaVisionLLM, structured_llm: OpenAIStructuredLLM):
        self.vision_llm, self.structured_llm = vision_llm, structured_llm

    async def extract_notice(self, image_path: Path, reference_date: date) -> tuple[NoticeExtraction, dict]:
        started = time.perf_counter()
        ocr_text, ocr_usage = await self.vision_llm.extract_text(image_path)
        structured, structured_usage = await self.structured_llm.extract_notice(ocr_text, reference_date)
        extraction = NoticeExtraction(raw_text=ocr_text, **structured.model_dump())
        return extraction, {"models": {"vision": ocr_usage["model"], "structured": structured_usage["model"]}, "prompt_tokens": ocr_usage["prompt_tokens"] + structured_usage["prompt_tokens"], "completion_tokens": ocr_usage["completion_tokens"] + structured_usage["completion_tokens"], "elapsed_seconds": round(time.perf_counter() - started, 3), "ocr": ocr_usage, "structured": structured_usage}
