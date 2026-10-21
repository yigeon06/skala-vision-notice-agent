"""실제 이미지·모델 없이 구조화 재시도 정책과 오류 복구를 검증한다."""

import asyncio
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.notice_extractor import NoticeExtractor
from agent.schemas import StructuredNoticeExtraction
from agent.structured_llm import OpenAIStructuredLLM, StructuredOutputError
from notice.service import extract_with_validation


REFERENCE_DATE = date(2026, 10, 21)
OCR_TEXT = "교육 안내\n신청 마감: 10월 25일"


def _structured(
    *, valid=False, title="교육 안내", event_type="application_deadline",
    date_text="10월 25일", evidence_text="신청 마감: 10월 25일",
):
    return StructuredNoticeExtraction.model_validate({
        "title": title,
        "target": [], "action_required": [], "application_method": None,
        "cleaned_text": OCR_TEXT, "recruitment_positions": [],
        "additional_information": [], "confidence": 0.9,
        "events": [{
            "event_type": event_type, "date_text": date_text,
            "start_date": None, "end_date": None,
            "location": None, "evidence_text": evidence_text,
        }] if valid else [],
    })


def _usage(model):
    return {"model": model, "prompt_tokens": 10, "completion_tokens": 5}


def _run(first, second=None, *, ocr=OCR_TEXT):
    vision = SimpleNamespace(extract_text=AsyncMock(return_value=(ocr, _usage("vision"))))
    responses = [(first, _usage("text"))]
    if second is not None:
        responses.append(second if isinstance(second, Exception) else (second, _usage("text")))
    text = SimpleNamespace(extract_notice=AsyncMock(side_effect=responses))
    result = asyncio.run(extract_with_validation(
        NoticeExtractor(vision, text), Path("unused.png"), REFERENCE_DATE,
    ))
    vision.extract_text.assert_awaited_once()
    return result, text.extract_notice


def test_confirmed_result_skips_retry():
    (extraction, validation, usage), call = _run(_structured(valid=True))
    assert validation.status == "confirmed"
    assert extraction.events[0].start_date == "2026-10-25"
    assert usage["structure_retry"] == {"attempted": False}
    assert call.await_count == 1


def test_missing_event_retries_with_same_ocr_and_validation_feedback():
    (extraction, validation, usage), call = _run(_structured(), _structured(valid=True))
    assert validation.status == "confirmed"
    assert extraction.raw_text == OCR_TEXT
    assert call.await_count == 2
    assert call.await_args.args == (OCR_TEXT, REFERENCE_DATE)
    assert call.await_args.kwargs["validation_issues"] == ["등록할 일정을 찾지 못했습니다."]
    assert usage["prompt_tokens"] == 30
    assert usage["completion_tokens"] == 15
    assert usage["structured"]["model"] == "text"
    assert usage["structure_retry"]["usage"] == _usage("text")


def test_unresolved_retry_stops_after_one_attempt():
    (_, validation, usage), call = _run(_structured(), _structured())
    assert validation.status == "needs_review"
    assert usage["structure_retry"]["status"] == "needs_review"
    assert call.await_count == 2


def test_retry_failure_preserves_first_result_and_reports_review():
    (extraction, validation, usage), call = _run(
        _structured(), StructuredOutputError("모의 API 오류"),
    )
    assert extraction.title == "교육 안내"
    assert extraction.raw_text == OCR_TEXT
    assert extraction.events == []
    assert validation.status == "needs_review"
    assert "최초 추출 결과" in validation.issues[-1]
    assert usage["structure_retry"]["status"] == "failed"
    assert usage["prompt_tokens"] == 20
    assert call.await_count == 2


@pytest.mark.parametrize("ocr", ["", "공지 안내", "일정은 추후 안내", "25일 예정"])
def test_missing_source_or_explicit_date_skips_retry(ocr):
    (_, validation, usage), call = _run(_structured(), ocr=ocr)
    assert validation.status == "needs_review"
    assert usage["structure_retry"]["attempted"] is False
    assert call.await_count == 1


def test_missing_title_retries_even_without_dates():
    (extraction, validation, _), call = _run(
        _structured(title=""), _structured(), ocr="교육 안내. 일정은 추후 안내",
    )
    assert extraction.title == "교육 안내"
    assert validation.status == "needs_review"
    assert call.await_count == 2


@pytest.mark.parametrize("field,value", [
    ("date_text", "추후 안내"), ("evidence_text", ""),
])
def test_event_date_or_evidence_failure_retries(field, value):
    first = _structured(valid=True)
    updates = {field: value}
    if field == "date_text":
        updates["evidence_text"] = "추후 안내"
    first = first.model_copy(update={
        "events": [first.events[0].model_copy(update=updates)],
    })
    (_, validation, _), call = _run(first, _structured(valid=True))
    assert validation.status == "confirmed"
    assert call.await_count == 2


def test_application_deadline_type_conflict_retries_and_recovers():
    wrong = _structured(valid=True, event_type="submission_deadline")
    (extraction, validation, usage), call = _run(wrong, _structured(valid=True))
    assert extraction.events[0].event_type == "application_deadline"
    assert validation.status == "confirmed"
    assert "원문상 신청·지원·모집·예약 마감" in usage["structure_retry"]["initial_issues"][0]
    assert call.await_count == 2


def test_submission_deadline_type_conflict_retries_and_recovers():
    wrong = _structured(
        valid=True,
        event_type="application_deadline",
        evidence_text="영수증 제출 마감: 10월 25일",
    )
    corrected = _structured(
        valid=True,
        event_type="submission_deadline",
        evidence_text="영수증 제출 마감: 10월 25일",
    )
    (extraction, validation, _), call = _run(wrong, corrected)
    assert extraction.events[0].event_type == "submission_deadline"
    assert validation.status == "confirmed"
    assert call.await_count == 2


def test_ambiguous_deadline_language_does_not_force_retry():
    ambiguous = _structured(
        valid=True,
        event_type="other",
        evidence_text="지원 서류 제출 마감 및 신청 마감: 10월 25일",
    )
    (_, validation, usage), call = _run(ambiguous)
    assert validation.status == "confirmed"
    assert usage["structure_retry"]["attempted"] is False
    assert call.await_count == 1


def test_unresolved_type_conflict_stops_as_needs_review():
    wrong = _structured(valid=True, event_type="submission_deadline")
    (_, validation, usage), call = _run(wrong, wrong)
    assert validation.status == "needs_review"
    assert "event_type" in validation.issues[0]
    assert usage["structure_retry"]["status"] == "needs_review"
    assert call.await_count == 2


def test_initial_structure_failure_is_not_swallowed():
    vision = SimpleNamespace(extract_text=AsyncMock(return_value=(OCR_TEXT, _usage("vision"))))
    text = SimpleNamespace(extract_notice=AsyncMock(side_effect=StructuredOutputError("최초 호출 실패")))
    with pytest.raises(StructuredOutputError):
        asyncio.run(extract_with_validation(
            NoticeExtractor(vision, text), Path("unused.png"), REFERENCE_DATE,
        ))
    assert text.extract_notice.await_count == 1


def test_structure_prompt_includes_feedback_and_source():
    parse = AsyncMock(return_value=SimpleNamespace(
        output_parsed=_structured(valid=True), usage=None,
    ))
    llm = OpenAIStructuredLLM(client=SimpleNamespace(responses=SimpleNamespace(parse=parse)))
    asyncio.run(llm.extract_notice(
        OCR_TEXT, REFERENCE_DATE, validation_issues=["일정 근거 누락"],
    ))
    messages = parse.await_args.kwargs["input"]
    assert OCR_TEXT in messages[1]["content"]
    assert "일정 근거 누락" in messages[-1]["content"]
    assert "application_deadline" in messages[-1]["content"]
    assert "submission_deadline" in messages[-1]["content"]
    assert "만들지 말고" in messages[-1]["content"]
