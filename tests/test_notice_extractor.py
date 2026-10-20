from __future__ import annotations

import asyncio
from datetime import date

from agent.notice_extractor import NoticeExtractor, _dedupe_additional_information
from agent.schemas import AdditionalInformation, StructuredNoticeExtraction
from agent.vision_llm import _segment_bounds, merge_ocr_texts, truncate_repeated_tail


def test_segment_bounds_cover_image_with_overlap() -> None:
    bounds = _segment_bounds(3028, count=3, overlap_ratio=0.15)

    assert len(bounds) == 3
    assert bounds[0][0] == 0
    assert bounds[-1][1] == 3028
    assert bounds[0][1] > bounds[1][0]
    assert bounds[1][1] > bounds[2][0]


def test_merge_ocr_texts_removes_boundary_duplicates() -> None:
    merged = merge_ocr_texts([
        "모집분야\nSW Engineering\n수행업무",
        "SW Engineering\n수행업무\nAI 기반 서비스 개발\n우대사항",
        "우대사항\nPython 경험\n모집기간",
    ])

    assert merged == (
        "모집분야\nSW Engineering\n수행업무\nAI 기반 서비스 개발\n"
        "우대사항\nPython 경험\n모집기간"
    )


def test_repeated_tail_is_truncated_after_three_equal_lines() -> None:
    text, metadata = truncate_repeated_tail(
        "채용 안내\n개인정보 처리방침\n주소\n개인정보처리방침\n"
        "개인정보 처리방침\n개인정보처리방침\n개인정보처리방침"
    )

    assert text == "채용 안내\n개인정보 처리방침\n주소"
    assert metadata == {
        "repetition_truncated": True,
        "truncated_line_count": 4,
        "repeated_line": "개인정보처리방침",
    }


def test_two_repeated_lines_are_preserved() -> None:
    original = "지원자격\n지원자격\n채용절차"

    text, metadata = truncate_repeated_tail(original)

    assert text == original
    assert metadata["repetition_truncated"] is False
    assert metadata["truncated_line_count"] == 0


def test_additional_information_items_are_deduplicated() -> None:
    sections = [
        AdditionalInformation(
            category="preferred_certification",
            title="우대 자격증",
            items=["정보처리기사", " 정보 처리 기사 ", "CISSP"],
            evidence_text="우대 자격증: 정보처리기사, CISSP",
            confidence=0.8,
            needs_review=True,
        )
    ]

    result = _dedupe_additional_information(sections)

    assert result[0].items == ["정보처리기사", "CISSP"]
    assert result[0].evidence_text == sections[0].evidence_text


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
            return StructuredNoticeExtraction(
                title="공지",
                target=[],
                action_required=[],
                application_method=None,
                cleaned_text="신청 마감: 10월 25일",
                recruitment_positions=[],
                additional_information=[],
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
    assert extraction.cleaned_text == "신청 마감: 10월 25일"
    assert calls == [
        ("ocr", image_path),
        ("structured", "신청 마감: 10월 25일", date(2026, 10, 20)),
    ]
    assert usage["prompt_tokens"] == 30
    assert usage["completion_tokens"] == 13
