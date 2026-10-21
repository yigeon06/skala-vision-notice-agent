"""실제 채용 공고 정답 파일과 평가 지표 계산을 검증한다."""

import json
from pathlib import Path
from agent.schemas import NoticeExtraction
from eval.evaluate_extraction import (
    GROUND_TRUTH,
    TEXT_MATCH_THRESHOLD,
    evaluate_posting,
    load_saved_notices,
    match_items,
    summarize,
)
from notice.repository import NoticeRepository


def _extraction(*, title="채용 공고") -> NoticeExtraction:
    return NoticeExtraction.model_validate(
        {
            "title": title,
            "target": ["지원자"],
            "action_required": ["지원하기"],
            "application_method": "SK Careers",
            "raw_text": "채용 공고 원문",
            "cleaned_text": "학사 이상 학위 보유자\n해외여행에 결격 사유가 없는 분",
            "events": [
                {
                    "event_type": "application_deadline",
                    "date_text": "2026년 10월 8일~10월 21일 18:00",
                    "start_date": "2026-10-08",
                    "end_date": "2026-10-21",
                    "location": None,
                    "evidence_text": "지원 기간과 마감 시간",
                }
            ],
            "recruitment_positions": [
                {
                    "name": "생산",
                    "responsibilities": ["생산설비 운전 점검 및 공정 모니터링"],
                    "preferred_qualifications": ["GMP 생산 업무 경험"],
                }
            ],
            "additional_information": [],
            "confidence": 0.9,
        }
    )


def _expected():
    return {
        "file": "sample.png",
        "title": "채용 공고",
        "application_period": {
            "start_date": "2026-10-08",
            "end_date": "2026-10-21",
            "deadline_time": "18:00",
        },
        "responsibilities": [
            {"group": None, "items": ["생산설비 운전·점검 및 공정 모니터링"]}
        ],
        "qualifications": [
            {"group": None, "items": ["학사 이상 학위 보유자"]}
        ],
        "preferred": [{"group": None, "items": ["GMP 생산 업무 경험"]}],
    }


def test_ground_truth_contains_only_requested_ten_images():
    data = json.loads(Path(GROUND_TRUTH).read_text(encoding="utf-8"))
    assert [item["file"] for item in data["postings"]] == [
        f"sk_job_{number}.png" for number in range(11, 21)
    ]
    assert data["postings"][8]["application_period"]["deadline_time"] is None
    assert data["postings"][9]["application_period"]["deadline_time"] is None


def test_text_matching_ignores_spacing_and_punctuation():
    result = match_items(
        ["생산설비 운전·점검 및 공정 모니터링"],
        ["생산 설비 운전, 점검 및 공정 모니터링"],
        threshold=TEXT_MATCH_THRESHOLD,
    )
    assert result["recall"] == 1.0
    assert result["matches"][0]["score"] == 1.0


def test_evaluate_posting_scores_structured_and_text_fields():
    row = evaluate_posting(
        _expected(),
        _extraction(),
        notice_id=1,
        status="confirmed",
        created_at="2026-10-21T10:00:00+09:00",
    )
    assert row["title_ok"] is True
    assert row["event_type_ok"] is True
    assert row["start_date_ok"] is True
    assert row["end_date_ok"] is True
    assert row["responsibilities"]["recall"] == 1.0
    assert row["qualifications"]["recall"] == 1.0
    assert row["preferred"]["recall"] == 1.0


def test_missing_expected_title_requires_review_and_empty_title():
    expected = _expected()
    expected["title"] = None
    row = evaluate_posting(
        expected,
        _extraction(title=""),
        notice_id=2,
        status="needs_review",
        created_at="2026-10-21T10:00:00+09:00",
    )
    assert row["title_ok"] is True
    assert row["status_ok"] is True
    assert row["expected_status"] == "needs_review"


def test_summary_uses_micro_recall_and_counts_failures():
    row = evaluate_posting(
        _expected(),
        _extraction(),
        notice_id=1,
        status="confirmed",
        created_at="2026-10-21T10:00:00+09:00",
    )
    result = summarize([row, {"file": "failed.png", "extraction": None}])
    assert result["sample_count"] == 2
    assert result["failure_count"] == 1
    assert result["title_accuracy"] == 0.5
    assert result["responsibility_recall"] == 1.0


def test_saved_notices_are_loaded_by_source_hash(tmp_path):
    database = tmp_path / "notices.db"
    repository = NoticeRepository(database)
    repository.save_notice(
        request_id="saved",
        extraction=_extraction(),
        source_image_path="upload.png",
        source_image_hash="image-hash",
        status="confirmed",
    )
    notices = load_saved_notices(database)
    assert notices["image-hash"]["title"] == "채용 공고"
    assert notices["image-hash"]["events"][0]["start_at"] == "2026-10-08T00:00:00+09:00"
    assert notices["image-hash"]["events"][0]["end_at"] == "2026-10-21T23:59:59+09:00"
