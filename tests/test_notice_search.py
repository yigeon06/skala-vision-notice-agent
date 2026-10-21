"""기간·상태 기반 SQLite 공지 조회를 검증한다."""

from datetime import date
from pathlib import Path

from agent.schemas import NoticeEventExtraction, NoticeExtraction
from agent.search import NoticeSearchFilters, resolve_search_filters
from notice.repository import NoticeRepository


def _event(
    event_type: str,
    date_text: str,
    start_date: str | None,
    end_date: str | None = None,
) -> NoticeEventExtraction:
    return NoticeEventExtraction(
        event_type=event_type,
        date_text=date_text,
        start_date=start_date,
        end_date=end_date,
        location=None,
        evidence_text=date_text,
    )


def _notice(title: str, events: list[NoticeEventExtraction]) -> NoticeExtraction:
    return NoticeExtraction(
        title=title,
        target=["전 임직원"],
        action_required=[],
        application_method=None,
        raw_text=title,
        cleaned_text=title,
        recruitment_positions=[],
        additional_information=[],
        events=events,
        confidence=0.9,
    )


def _repository(tmp_path: Path) -> NoticeRepository:
    repository = NoticeRepository(tmp_path / "notices.db")
    repository.save_notice(
        request_id="deadline",
        extraction=_notice(
            "이번 주 마감",
            [
                _event(
                    "application_deadline",
                    "10월 1일부터 23일까지",
                    "2026-10-01",
                    "2026-10-23",
                )
            ],
        ),
        source_image_path="deadline.png",
        source_image_hash="deadline",
        status="confirmed",
    )
    repository.save_notice(
        request_id="next-week",
        extraction=_notice(
            "다음 주 행사",
            [_event("event", "10월 28일", "2026-10-28")],
        ),
        source_image_path="event.png",
        source_image_hash="event",
        status="confirmed",
    )
    repository.save_notice(
        request_id="review",
        extraction=_notice(
            "검토 필요 공지",
            [_event("other", "날짜 확인 필요", None)],
        ),
        source_image_path="review.png",
        source_image_hash="review",
        status="needs_review",
    )
    return repository


def test_resolve_this_and_next_week_as_monday_to_monday():
    this_week = resolve_search_filters(
        NoticeSearchFilters(period="this_week"), date(2026, 10, 20)
    )
    next_week = resolve_search_filters(
        NoticeSearchFilters(period="next_week"), date(2026, 10, 20)
    )
    assert this_week.start_at == "2026-10-19T00:00:00+09:00"
    assert this_week.end_at == "2026-10-26T00:00:00+09:00"
    assert next_week.start_at == "2026-10-26T00:00:00+09:00"
    assert next_week.end_at == "2026-11-02T00:00:00+09:00"


def test_semantic_search_type_is_kept_separate_from_sql_filters():
    filters = NoticeSearchFilters(search_type="semantic_search")
    assert filters.search_type == "semantic_search"
    assert filters.period == "all"
    assert filters.status == "all"
    assert filters.event_types == []


def test_deadline_search_uses_range_end_as_effective_date(tmp_path):
    repository = _repository(tmp_path)
    results = repository.search_notices(
        start_at="2026-10-19T00:00:00+09:00",
        end_at="2026-10-26T00:00:00+09:00",
        event_types=["application_deadline", "submission_deadline"],
    )
    assert [notice["title"] for notice in results] == ["이번 주 마감"]
    assert results[0]["events"][0]["effective_at"] == (
        "2026-10-23T23:59:59+09:00"
    )


def test_next_week_search_returns_event_by_start_date(tmp_path):
    repository = _repository(tmp_path)
    results = repository.search_notices(
        start_at="2026-10-26T00:00:00+09:00",
        end_at="2026-11-02T00:00:00+09:00",
    )
    assert [notice["title"] for notice in results] == ["다음 주 행사"]


def test_notice_status_search_does_not_require_confirmed_event_date(tmp_path):
    repository = _repository(tmp_path)
    results = repository.search_notices(
        status="needs_review",
        status_scope="notice",
    )
    assert [notice["title"] for notice in results] == ["검토 필요 공지"]
    assert results[0]["events"][0]["status"] == "needs_review"


def test_event_status_search_returns_unresolved_event(tmp_path):
    repository = _repository(tmp_path)
    results = repository.search_notices(
        status="needs_review",
        status_scope="event",
    )
    assert [notice["title"] for notice in results] == ["검토 필요 공지"]
    assert results[0]["events"][0]["effective_at"] is None


def test_search_returns_empty_list_when_no_event_matches(tmp_path):
    repository = _repository(tmp_path)
    assert repository.search_notices(
        start_at="2027-01-01T00:00:00+09:00",
        end_at="2027-01-02T00:00:00+09:00",
    ) == []
