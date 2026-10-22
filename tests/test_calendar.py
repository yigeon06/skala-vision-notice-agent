"""마감일과 월 경계에 걸친 일정의 달력 조회를 검증한다."""

from agent.schemas import NoticeExtraction
from notice.repository import NoticeRepository


def test_calendar_uses_deadline_end_and_includes_spanning_events(tmp_path):
    repository = NoticeRepository(tmp_path / "notices.db")
    common = {
        "title": "달력 공지", "target": [], "action_required": [],
        "application_method": None, "raw_text": "원문", "cleaned_text": "정리문",
        "recruitment_positions": [], "additional_information": [], "confidence": 0.9,
    }
    def event(kind, start, end, text):
        return {
            "event_type": kind, "date_text": text, "start_date": start,
            "end_date": end, "location": None, "evidence_text": text,
        }
    extraction = NoticeExtraction.model_validate({
        **common,
        "events": [
            event("application_deadline", "2026-09-20", "2026-10-03", "10월 3일 마감"),
            event("event", "2026-09-29", "2026-10-02", "월 경계 행사"),
            event("event", "2026-10-31", "2026-11-02", "다음 달까지 행사"),
            event("announcement", None, None, "일정 추후 공지"),
        ],
    })
    notice_id, _ = repository.save_notice(
        request_id="calendar", extraction=extraction,
        source_image_path="sample.png", source_image_hash="hash", status="confirmed",
    )
    october = repository.list_calendar_events("2026-10-01", "2026-11-01")
    assert [row["date_text"] for row in october["items"]] == [
        "월 경계 행사", "10월 3일 마감", "다음 달까지 행사",
    ]
    assert all(row["notice_id"] == notice_id for row in october["items"])
    assert october["undated"][0]["date_text"] == "일정 추후 공지"
    november = repository.list_calendar_events("2026-11-01", "2026-12-01")
    assert [row["date_text"] for row in november["items"]] == ["다음 달까지 행사"]


def test_calendar_includes_deadline_start_in_its_month(tmp_path):
    repository = NoticeRepository(tmp_path / "notices.db")
    extraction = NoticeExtraction.model_validate({
        "title": "공모전", "target": [], "action_required": [],
        "application_method": None, "raw_text": "원문", "cleaned_text": "정리문",
        "recruitment_positions": [], "additional_information": [], "confidence": 0.9,
        "events": [
            {
                "event_type": kind, "date_text": "10월 21일~11월 3일",
                "start_date": "2026-10-21", "end_date": "2026-11-03",
                "location": None, "evidence_text": "10월 21일~11월 3일",
            }
            for kind in ("application_deadline", "submission_deadline")
        ],
    })
    repository.save_notice(
        request_id="cross-month-deadline", extraction=extraction,
        source_image_path="sample.png", source_image_hash="hash", status="confirmed",
    )
    october = repository.list_calendar_events("2026-10-01", "2026-11-01")
    november = repository.list_calendar_events("2026-11-01", "2026-12-01")
    assert {row["event_type"] for row in october["items"]} == {
        "application_deadline", "submission_deadline",
    }
    assert {row["event_type"] for row in november["items"]} == {
        "application_deadline", "submission_deadline",
    }


def test_calendar_only_fetches_period_endpoints_and_includes_notice_action(tmp_path):
    repository = NoticeRepository(tmp_path / "notices.db")
    extraction = NoticeExtraction.model_validate({
        "title": "참여후기 이벤트", "target": [],
        "action_required": ["참여하기"], "application_method": None,
        "raw_text": "이벤트 기간 9월 29일~11월 2일", "cleaned_text": "참여후기",
        "recruitment_positions": [], "additional_information": [],
        "confidence": 0.9,
        "events": [{
            "event_type": "event", "date_text": "이벤트 기간 9월 29일~11월 2일",
            "start_date": "2026-09-29", "end_date": "2026-11-02",
            "location": None, "evidence_text": "이벤트 기간 9월 29일~11월 2일",
        }],
    })
    repository.save_notice(
        request_id="calendar-participation", extraction=extraction,
        source_image_path="sample.png", source_image_hash="hash", status="confirmed",
    )
    september = repository.list_calendar_events("2026-09-01", "2026-10-01")
    october = repository.list_calendar_events("2026-10-01", "2026-11-01")
    november = repository.list_calendar_events("2026-11-01", "2026-12-01")
    assert len(september["items"]) == 1
    assert october["items"] == []
    assert len(november["items"]) == 1
    assert november["items"][0]["action_required"] == ["참여하기"]
