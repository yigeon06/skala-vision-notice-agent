"""Vision이 추출한 날짜를 Asia/Seoul ISO 8601 값으로 정규화한다."""

from __future__ import annotations

import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from agent.schemas import NoticeEventExtraction, NoticeExtraction


SEOUL = ZoneInfo("Asia/Seoul")
KOREAN_DATE = re.compile(
    r"(?:(?P<year>20\d{2})\s*년\s*)?"
    r"(?P<month>\d{1,2})\s*월\s*(?P<day>\d{1,2})\s*일"
    r"(?:\s*(?P<ampm>오전|오후)?\s*(?P<hour>\d{1,2})\s*(?:시|:)"
    r"(?:\s*(?P<minute>\d{1,2})\s*분?)?)?"
)


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


def _parse_korean_date(text: str, reference_date: date) -> tuple[str | None, bool]:
    match = KOREAN_DATE.search(text)
    if not match:
        return None, False
    year = int(match.group("year") or reference_date.year)
    month = int(match.group("month"))
    day = int(match.group("day"))
    hour_text = match.group("hour")
    minute = int(match.group("minute") or 0)
    all_day = hour_text is None
    hour = int(hour_text or 0)
    if match.group("ampm") == "오후" and hour < 12:
        hour += 12
    if match.group("ampm") == "오전" and hour == 12:
        hour = 0
    try:
        parsed = datetime(year, month, day, hour, minute, tzinfo=SEOUL)
    except ValueError:
        return None, all_day
    return parsed.isoformat(), all_day


def normalize_extraction(
    extraction: NoticeExtraction, reference_date: date
) -> NoticeExtraction:
    normalized_events: list[NoticeEventExtraction] = []
    for event in extraction.events:
        start_at = _normalize_existing(event.start_at)
        all_day = event.all_day
        parsed_start, parsed_all_day = _parse_korean_date(
            f"{event.date_text} {event.evidence_text}", reference_date
        )
        if parsed_start is not None:
            start_at, all_day = parsed_start, parsed_all_day
        end_at = _normalize_existing(event.end_at)
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

