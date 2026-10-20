from __future__ import annotations

import asyncio
from datetime import date

from agent.notice_extractor import NoticeExtractor
from agent.schemas import NoticeExtraction


def test_hybrid_extractor_connects_ocr_and_structured_steps(tmp_path) -> None:
    calls = []

    class FakeVision:
        async def extract_text(self, image_path):
            calls.append(("ocr", image_path))
            return "신청 마감: 10월 25일", {
                "model": "vision",
                "prompt_tokens": 10,
                "completion_tokens": 5,
            }

    class FakeStructured:
        async def extract_notice(self, text, reference_date):
            calls.append(("structured", text, reference_date))
            return NoticeExtraction(
                title="공지",
                target=[],
                action_required=[],
                application_method=None,
                raw_text=text,
                events=[],
                confidence=0.9,
            ), {
                "model": "text",
                "prompt_tokens": 20,
                "completion_tokens": 8,
            }

    image_path = tmp_path / "notice.png"
    extractor = NoticeExtractor(FakeVision(), FakeStructured())
    extraction, usage = asyncio.run(
        extractor.extract_notice(image_path, date(2026, 10, 20))
    )

    assert extraction.raw_text == "신청 마감: 10월 25일"
    assert calls == [
        ("ocr", image_path),
        ("structured", "신청 마감: 10월 25일", date(2026, 10, 20)),
    ]
    assert usage["prompt_tokens"] == 30
    assert usage["completion_tokens"] == 13
