"""공지 추출 결과 검증 규칙."""

from __future__ import annotations

import time
import re
from datetime import date
from pathlib import Path

from agent.notice_extractor import NoticeExtractor
from agent.schemas import ExtractionValidation, NoticeExtraction
from agent.structured_llm import StructuredOutputError
from notice.date_normalizer import has_explicit_date, normalize_extraction


_APPLICATION_DEADLINE = re.compile(
    r"(?:신청|지원|모집|예약)\s*(?:기간|기한|마감|접수)"
)
_SUBMISSION_DEADLINE = re.compile(
    r"(?:서류|자료|비용|영수증)\s*(?:을|를)?\s*제출\s*(?:기간|기한|마감)"
    r"|(?:제출\s*(?:기간|기한|마감))"
)


def _expected_deadline_type(text: str) -> str | None:
    """명확한 마감 표현이 한 종류일 때만 기대 유형을 반환한다."""
    application = bool(_APPLICATION_DEADLINE.search(text))
    submission = bool(_SUBMISSION_DEADLINE.search(text))
    if application == submission:
        return None
    return "application_deadline" if application else "submission_deadline"


def _event_type_issue(index: int, event) -> str | None:
    expected = _expected_deadline_type(
        f"{event.date_text.strip()} {event.evidence_text.strip()}"
    )
    if expected is None or event.event_type == expected:
        return None
    label = "신청·지원·모집·예약 마감" if expected == "application_deadline" else "서류·자료·비용 제출 마감"
    return (
        f"일정 {index}은 원문상 {label}이지만 "
        f"event_type이 {event.event_type}입니다. {expected}인지 확인해 주세요."
    )


def _has_event_type_conflict(extraction: NoticeExtraction) -> bool:
    return any(
        _event_type_issue(index, event) is not None
        for index, event in enumerate(extraction.events, 1)
    )


def should_retry_structure(extraction: NoticeExtraction) -> bool:
    """원문에서 보완할 가능성이 있는 누락에만 구조화를 재시도한다."""
    if not extraction.raw_text.strip():
        return False
    if not extraction.title.strip():
        return True
    if _has_event_type_conflict(extraction):
        return True
    missing_event_data = not extraction.events or any(
        not event.date_text.strip()
        or not event.evidence_text.strip()
        or event.start_date is None
        for event in extraction.events
    )
    return missing_event_data and has_explicit_date(extraction.raw_text)


async def extract_with_validation(
    extractor: NoticeExtractor, image_path: Path, reference_date: date,
) -> tuple[NoticeExtraction, ExtractionValidation, dict]:
    started = time.perf_counter()
    extraction, original_usage = await extractor.extract_notice(image_path, reference_date)
    extraction = normalize_extraction(extraction, reference_date)
    validation = validate_extraction(extraction)
    usage = {**original_usage, "structure_retry": {"attempted": False}}
    if validation.status == "confirmed" or not should_retry_structure(extraction):
        return extraction, validation, usage

    retry = {"attempted": True, "initial_issues": list(validation.issues)}
    usage["structure_retry"] = retry
    try:
        candidate, retry_usage = await extractor.restructure_notice(
            extraction.raw_text, reference_date, validation.issues,
        )
    except StructuredOutputError:
        retry["status"] = "failed"
        validation = validation.model_copy(update={
            "status": "needs_review",
            "issues": validation.issues + [
                "구조화 재시도에 실패해 최초 추출 결과를 표시합니다. 내용을 확인해 주세요."
            ],
        })
    else:
        extraction = normalize_extraction(candidate, reference_date)
        validation = validate_extraction(extraction)
        retry.update({"status": validation.status, "usage": retry_usage})
        for key in ("prompt_tokens", "completion_tokens"):
            usage[key] = original_usage.get(key, 0) + retry_usage.get(key, 0)
    usage["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    return extraction, validation, usage


def validate_extraction(extraction: NoticeExtraction) -> ExtractionValidation:
    issues: list[str] = []
    if not extraction.title.strip():
        issues.append("제목을 확인할 수 없습니다.")
    if not extraction.raw_text.strip():
        issues.append("공지 원문을 확인할 수 없습니다.")
    if not extraction.events:
        issues.append("등록할 일정을 찾지 못했습니다.")
    for index, event in enumerate(extraction.events, 1):
        if not event.date_text.strip():
            issues.append(f"일정 {index}의 날짜 원문이 없습니다.")
        if not event.evidence_text.strip():
            issues.append(f"일정 {index}의 근거 문장이 없습니다.")
        if event.start_date is None:
            if not any(character.isdigit() for character in event.evidence_text):
                issues.append(
                    f"일정 {index}에 확정 가능한 날짜 표현이 없습니다."
                )
            else:
                issues.append(f"일정 {index}의 날짜를 확정할 수 없습니다.")
        if event.start_date and event.end_date and event.end_date < event.start_date:
            issues.append(f"일정 {index}의 종료 날짜가 시작 날짜보다 빠릅니다.")
        type_issue = _event_type_issue(index, event)
        if type_issue:
            issues.append(type_issue)
    return ExtractionValidation(
        status="needs_review" if issues else "confirmed",
        issues=issues,
    )

