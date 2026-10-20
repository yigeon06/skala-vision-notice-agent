from __future__ import annotations

from datetime import date
from pathlib import Path

from agent.schemas import NoticeEventExtraction, NoticeExtraction
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
    notices = repository.list_notices()
    assert len(notices) == 1
    assert notices[0]["title"] == "정보보안 교육"
    assert notices[0]["event_count"] == 1

