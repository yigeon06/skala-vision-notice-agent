"""로컬 OCR과 OpenAI 구조화를 연결하는 하이브리드 추출기."""
from __future__ import annotations
import time
from datetime import date
from pathlib import Path
from .schemas import AdditionalInformation, NoticeExtraction
from .structured_llm import OpenAIStructuredLLM
from .vision_llm import OllamaVisionLLM

class NoticeExtractor:
    def __init__(self, vision_llm: OllamaVisionLLM, structured_llm: OpenAIStructuredLLM):
        self.vision_llm, self.structured_llm = vision_llm, structured_llm

    async def extract_notice(self, image_path: Path, reference_date: date) -> tuple[NoticeExtraction, dict]:
        started = time.perf_counter()
        ocr_text, ocr_usage = await self.vision_llm.extract_text(image_path)
        structured, structured_usage = await self.structured_llm.extract_notice(ocr_text, reference_date)
        structured = structured.model_copy(
            update={
                "additional_information": _dedupe_additional_information(
                    structured.additional_information
                )
            }
        )
        extraction = NoticeExtraction(raw_text=ocr_text, **structured.model_dump())
        return extraction, {"models": {"vision": ocr_usage["model"], "structured": structured_usage["model"]}, "prompt_tokens": ocr_usage["prompt_tokens"] + structured_usage["prompt_tokens"], "completion_tokens": ocr_usage["completion_tokens"] + structured_usage["completion_tokens"], "elapsed_seconds": round(time.perf_counter() - started, 3), "ocr": ocr_usage, "structured": structured_usage}

    async def restructure_notice(
        self, ocr_text: str, reference_date: date, validation_issues: list[str],
    ) -> tuple[NoticeExtraction, dict]:
        structured, usage = await self.structured_llm.extract_notice(
            ocr_text, reference_date, validation_issues=validation_issues,
        )
        structured = structured.model_copy(update={
            "additional_information": _dedupe_additional_information(
                structured.additional_information
            ),
        })
        return NoticeExtraction(raw_text=ocr_text, **structured.model_dump()), usage


def _dedupe_additional_information(
    sections: list[AdditionalInformation],
) -> list[AdditionalInformation]:
    """분류별 항목의 공백·대소문자 차이를 무시하고 중복을 제거한다."""
    result: list[AdditionalInformation] = []
    for section in sections:
        seen: set[str] = set()
        items: list[str] = []
        for item in section.items:
            normalized = "".join(item.split()).casefold()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            items.append(item.strip())
        result.append(section.model_copy(update={"items": items}))
    return result
