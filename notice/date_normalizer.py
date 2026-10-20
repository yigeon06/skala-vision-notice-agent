"""추출된 날짜 표현을 Asia/Seoul ISO 8601 값으로 정규화한다."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from agent.schemas import NoticeEventExtraction, NoticeExtraction


SEOUL = ZoneInfo("Asia/Seoul")
TIME_SUFFIX = (
    r"(?:\s*\([월화수목금토일]\))?"
    r"(?:\s*(?P<ampm>오전|오후)?\s*(?P<hour>\d{1,2})"
    r"\s*(?:시|:)\s*(?P<minute>\d{1,2})?\s*분?)?"
)
KOREAN_DATE = re.compile(
    r"(?:(?P<year>20\d{2})\s*년\s*)?"
    r"(?P<month>\d{1,2})\s*월\s*(?P<day>\d{1,2})\s*일"
    + TIME_SUFFIX
)
DOT_DATE = re.compile(
    r"(?<!\d)(?:(?P<year>20\d{2})\s*[./-]\s*)?"
    r"(?P<month>\d{1,2})\s*[./-]\s*(?P<day>\d{1,2})(?!\d)"
    + TIME_SUFFIX
)
DAY_ONLY = re.compile(
    r"(?<!\d)(?P<day>\d{1,2})\s*일" + TIME_SUFFIX
)


@dataclass(frozen=True)
class _DateToken:
    start: int
    end: int
    year: int | None
    month: int | None
    day: int
    hour: int | None
    minute: int


def _token_from_match(match: re.Match[str]) -> _DateToken:
    hour_text = match.groupdict().get("hour")
    hour = int(hour_text) if hour_text else None
    ampm = match.groupdict().get("ampm")
    if hour is not None and ampm == "오후" and hour < 12:
        hour += 12
    if hour is not None and ampm == "오전" and hour == 12:
        hour = 0
    return _DateToken(
        start=match.start(),
        end=match.end(),
        year=int(match.group("year")) if match.groupdict().get("year") else None,
        month=int(match.group("month")) if match.groupdict().get("month") else None,
        day=int(match.group("day")),
        hour=hour,
        minute=int(match.groupdict().get("minute") or 0),
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


def _normalize_existing(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SEOUL)
    else:
        parsed = parsed.astimezone(SEOUL)
    return parsed.isoformat()


def _to_datetime(
    token: _DateToken,
    reference_date: date,
    *,
    previous: _DateToken | None = None,
    range_end: bool = False,
) -> datetime | None:
    year = token.year or (previous.year if previous else None) or reference_date.year
    month = token.month or (previous.month if previous else None)
    if month is None:
        return None
    if token.hour is None:
        hour, minute, second = (23, 59, 59) if range_end else (0, 0, 0)
    else:
        hour, minute, second = token.hour, token.minute, 0
    try:
        return datetime(year, month, token.day, hour, minute, second, tzinfo=SEOUL)
    except ValueError:
        return None


def _parse_date_values(
    text: str, reference_date: date
) -> tuple[str | None, str | None, bool]:
    tokens = _extract_date_tokens(text)
    if not tokens:
        return None, None, False
    start = _to_datetime(tokens[0], reference_date)
    if start is None:
        return None, None, tokens[0].hour is None
    end = None
    if len(tokens) >= 2:
        end = _to_datetime(
            tokens[1],
            reference_date,
            previous=tokens[0],
            range_end=True,
        )
    return (
        start.isoformat(),
        end.isoformat() if end else None,
        tokens[0].hour is None,
    )


def normalize_extraction(
    extraction: NoticeExtraction, reference_date: date
) -> NoticeExtraction:
    normalized_events: list[NoticeEventExtraction] = []
    for event in extraction.events:
        source_text = f"{event.date_text} {event.evidence_text}"
        parsed_start, parsed_end, parsed_all_day = _parse_date_values(
            source_text, reference_date
        )
        start_at = parsed_start or _normalize_existing(event.start_at)
        end_at = parsed_end or _normalize_existing(event.end_at)
        all_day = parsed_all_day if parsed_start is not None else event.all_day
        date_text = event.date_text.strip() or event.evidence_text.strip()
        normalized_events.append(
            event.model_copy(
                update={
                    "date_text": date_text,
                    "start_at": start_at,
                    "end_at": end_at,
                    "all_day": all_day,
                }
            )
        )
    return extraction.model_copy(update={"events": normalized_events})
