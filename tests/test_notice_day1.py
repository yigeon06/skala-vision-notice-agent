from __future__ import annotations

from datetime import date
from pathlib import Path

from agent.schemas import NoticeEventExtraction, NoticeExtraction, RecruitmentPosition
from notice.date_normalizer import normalize_extraction
from notice.repository import NoticeRepository
from notice.service import validate_extraction


def _sample_extraction() -> NoticeExtraction:
    return NoticeExtraction(
        title="정보보안 교육",
        target=["전 임직원"],
        action_required=["교육 신청"],
        application_method="사내 교육 포털",
        raw_text="신청 마감은 2026년 10월 23일까지입니다.",
        cleaned_text="신청 마감은 2026년 10월 23일까지입니다.",
        recruitment_positions=[
            RecruitmentPosition(
                name="Security",
                responsibilities=["정보보안 시스템 운영"],
                preferred_qualifications=["정보보안 자격 보유"],
            )
        ],
        confidence=0.9,
        events=[
            NoticeEventExtraction(
                event_type="application_deadline",
                date_text="2026년 10월 23일까지",
                start_at=None,
                end_at=None,
                all_day=True,
                location=None,
                evidence_text="신청 마감은 2026년 10월 23일까지입니다.",
                confidence=0.9,
            )
        ],
    )


def test_normalize_and_validate_notice() -> None:
    extraction = normalize_extraction(_sample_extraction(), date(2026, 10, 20))
    assert extraction.events[0].start_at == "2026-10-23T00:00:00+09:00"
    assert validate_extraction(extraction).status == "confirmed"


def test_normalize_korean_date_range() -> None:
    extraction = _sample_extraction()
    extraction.events[0] = extraction.events[0].model_copy(
        update={
            "date_text": "지원 기간",
            "evidence_text": "2026년 10월 07일(수)~2026년 10월 21일(수)",
        }
    )

    normalized = normalize_extraction(extraction, date(2026, 10, 20))

    assert normalized.events[0].start_at == "2026-10-07T00:00:00+09:00"
    assert normalized.events[0].end_at == "2026-10-21T23:59:59+09:00"


def test_normalize_dot_date_range_with_omitted_end_year() -> None:
    extraction = _sample_extraction()
    extraction.events[0] = extraction.events[0].model_copy(
        update={
            "date_text": "모집기간",
            "evidence_text": "2026.10.9(금) 10:00 ~ 10.22(목) 16:00",
        }
    )

    normalized = normalize_extraction(extraction, date(2026, 10, 20))

    assert normalized.events[0].start_at == "2026-10-09T10:00:00+09:00"
    assert normalized.events[0].end_at == "2026-10-22T16:00:00+09:00"


def test_normalize_range_with_omitted_end_month() -> None:
    extraction = _sample_extraction()
    extraction.events[0] = extraction.events[0].model_copy(
        update={
            "date_text": "지원 기간",
            "evidence_text": "2026년 10월 7일부터 21일까지",
        }
    )

    normalized = normalize_extraction(extraction, date(2026, 10, 20))

    assert normalized.events[0].start_at == "2026-10-07T00:00:00+09:00"
    assert normalized.events[0].end_at == "2026-10-21T23:59:59+09:00"


def test_repository_is_idempotent(tmp_path: Path) -> None:
    repository = NoticeRepository(tmp_path / "notices.db")
    extraction = normalize_extraction(_sample_extraction(), date(2026, 10, 20))
    first_id, first_created = repository.save_notice(
        request_id="request-1",
        extraction=extraction,
        source_image_path="sample.png",
        source_image_hash="abc",
        status="confirmed",
    )
    second_id, second_created = repository.save_notice(
        request_id="request-1",
        extraction=extraction,
        source_image_path="sample.png",
        source_image_hash="abc",
        status="confirmed",
    )
    assert first_created is True
    assert second_created is False
    assert first_id == second_id
    assert len(repository.get_notice(first_id)["events"]) == 1
    positions = repository.get_notice(first_id)["recruitment_positions"]
    assert positions[0]["name"] == "Security"
    assert positions[0]["responsibilities"] == ["정보보안 시스템 운영"]
    notices = repository.list_notices()
    assert len(notices) == 1
    assert notices[0]["title"] == "정보보안 교육"
    assert notices[0]["event_count"] == 1

