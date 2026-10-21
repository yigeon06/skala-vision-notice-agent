"""추출된 날짜 표현을 YYYY-MM-DD 값으로 정규화한다."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from agent.schemas import NoticeEventExtraction, NoticeExtraction


WEEKDAY_SUFFIX = r"(?:\s*\([월화수목금토일]\))?"
KOREAN_DATE = re.compile(
    r"(?:(?P<year>20\d{2})\s*년\s*)?"
    r"(?P<month>\d{1,2})\s*월\s*(?P<day>\d{1,2})\s*일"
    + WEEKDAY_SUFFIX
)
DOT_DATE = re.compile(
    r"(?<!\d)(?:(?P<year>20\d{2})\s*[./-]\s*)?"
    r"(?P<month>\d{1,2})\s*[./-]\s*(?P<day>\d{1,2})(?!\d)"
    + WEEKDAY_SUFFIX
)
DAY_ONLY = re.compile(
    r"(?<!\d)(?P<day>\d{1,2})\s*일" + WEEKDAY_SUFFIX
)


@dataclass(frozen=True)
class _DateToken:
    start: int
    end: int
    year: int | None
    month: int | None
    day: int


def _token_from_match(match: re.Match[str]) -> _DateToken:
    return _DateToken(
        start=match.start(),
        end=match.end(),
        year=int(match.group("year")) if match.groupdict().get("year") else None,
        month=int(match.group("month")) if match.groupdict().get("month") else None,
        day=int(match.group("day")),
    )


def _extract_date_tokens(text: str) -> list[_DateToken]:
    """긴 형식을 우선해 서로 겹치지 않는 날짜 토큰을 찾는다."""
    candidates = [
        _token_from_match(match)
        for pattern in (KOREAN_DATE, DOT_DATE, DAY_ONLY)
        for match in pattern.finditer(text)
    ]
    candidates.sort(key=lambda token: (token.start, -(token.end - token.start)))
    selected: list[_DateToken] = []
    for token in candidates:
        if any(token.start < item.end and item.start < token.end for item in selected):
            continue
        selected.append(token)
    return sorted(selected, key=lambda token: token.start)


def _to_date(
    token: _DateToken,
    reference_date: date,
    *,
    previous: _DateToken | None = None,
) -> date | None:
    year = token.year or (previous.year if previous else None) or reference_date.year
    month = token.month or (previous.month if previous else None)
    if month is None:
        return None
    try:
        return date(year, month, token.day)
    except ValueError:
        return None


def _parse_date_values(
    text: str, reference_date: date
) -> tuple[str | None, str | None]:
    tokens = _extract_date_tokens(text)
    if not tokens:
        return None, None
    start = _to_date(tokens[0], reference_date)
    if start is None:
        return None, None
    end = None
    if len(tokens) >= 2:
        end = _to_date(
            tokens[1],
            reference_date,
            previous=tokens[0],
        )
    return start.isoformat(), end.isoformat() if end and end != start else None


def has_explicit_date(text: str) -> bool:
    """월·일이 명시된 날짜 표현을 찾고 일만 적힌 표현은 제외한다."""
    return any(token.month is not None for token in _extract_date_tokens(text))


def normalize_extraction(
    extraction: NoticeExtraction, reference_date: date
) -> NoticeExtraction:
    normalized_events: list[NoticeEventExtraction] = []
    for event in extraction.events:
        date_text_tokens = _extract_date_tokens(event.date_text)
        evidence_tokens = _extract_date_tokens(event.evidence_text)
        source_text = (
            event.date_text if len(date_text_tokens) >= len(evidence_tokens)
            else event.evidence_text
        )
        parsed_start, parsed_end = _parse_date_values(source_text, reference_date)
        start_date = parsed_start or event.start_date
        end_date = parsed_end or event.end_date
        date_text = event.date_text.strip() or event.evidence_text.strip()
        normalized_events.append(
            event.model_copy(
                update={
                    "date_text": date_text,
                    "start_date": start_date,
                    "end_date": end_date,
                }
            )
        )
    return extraction.model_copy(update={"events": normalized_events})
