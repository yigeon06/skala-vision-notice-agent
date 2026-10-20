"""공지 추출 결과 검증 규칙."""

from __future__ import annotations

from agent.schemas import ExtractionValidation, NoticeExtraction


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
        if event.start_at is None:
            if not any(character.isdigit() for character in event.evidence_text):
                issues.append(
                    f"일정 {index}에 확정 가능한 날짜 표현이 없습니다."
                )
            else:
                issues.append(f"일정 {index}의 날짜를 확정할 수 없습니다.")
    return ExtractionValidation(
        status="needs_review" if issues else "confirmed",
        issues=issues,
    )

