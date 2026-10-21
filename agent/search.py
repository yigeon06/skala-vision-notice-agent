"""공지 조회 질문을 안전한 SQL 검색 조건으로 변환한다."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from openai import APIError, AsyncOpenAI
from pydantic import BaseModel, Field, ValidationError, model_validator

from agent.schemas import EventType


SEOUL = ZoneInfo("Asia/Seoul")
SearchPeriod = Literal[
    "all", "today", "tomorrow", "this_week", "next_week", "custom"
]
SearchStatus = Literal["all", "confirmed", "needs_review"]
StatusScope = Literal["notice", "event"]


class NoticeSearchFilters(BaseModel):
    search_type: Literal["structured_search", "semantic_search"] = (
        "structured_search"
    )
    period: SearchPeriod = "all"
    start_date: date | None = None
    end_date: date | None = None
    status: SearchStatus = "all"
    status_scope: StatusScope = "notice"
    event_types: list[EventType] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_custom_period(self):
        if self.period == "custom" and self.start_date is None:
            raise ValueError("직접 지정한 기간에는 시작 날짜가 필요합니다.")
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError("검색 종료 날짜는 시작 날짜보다 빠를 수 없습니다.")
        return self


class ResolvedSearchFilters(BaseModel):
    start_at: str | None
    end_at: str | None
    status: SearchStatus
    status_scope: StatusScope
    event_types: list[EventType]
    period: SearchPeriod
    reference_date: date


class NoticeSearchError(RuntimeError):
    """검색 조건을 만들거나 검색을 완료하지 못한 경우."""


class OpenAINoticeSearchParser:
    def __init__(self, model: str, client: AsyncOpenAI):
        self.model = model
        self.client = client

    async def parse(
        self,
        messages: list[dict[str, str]],
        *,
        reference_date: date,
    ) -> NoticeSearchFilters:
        try:
            response = await self.client.responses.parse(
                model=self.model,
                input=messages,
                instructions=(
                    "당신은 공지·일정 SQL 검색 조건 추출기다. SQL은 작성하지 않는다. "
                    f"기준 날짜는 {reference_date.isoformat()}이고 시간대는 Asia/Seoul이다. "
                    "오늘, 내일, 이번 주, 다음 주는 각각 today, tomorrow, this_week, next_week로 표현한다. "
                    "명시된 날짜 범위는 custom과 start_date/end_date로 표현하고 종료 날짜도 포함한다. "
                    "기간이 없으면 all이다. '검토 필요'는 needs_review, '확인 완료'는 confirmed다. "
                    "공지 자체의 상태를 묻는 경우 status_scope는 notice, 일정 상태를 묻는 경우 event다. "
                    "신청·지원·모집 마감은 application_deadline, 서류·자료·비용 제출 마감은 submission_deadline, "
                    "행사는 event, 발표는 announcement다. '마감'이지만 종류가 불명확하면 두 마감 유형을 모두 포함한다. "
                    "'일정'처럼 유형을 한정하지 않으면 event_types는 빈 배열로 둔다."
                    " 날짜·상태·일정 유형으로 답할 수 있거나 전체 공지 목록을 요청하면 structured_search다. "
                    "특정 공지의 신청 방법·제출서류·지원 자격·우대사항처럼 본문 의미 검색이 필요하면 semantic_search다. "
                    "semantic_search인 경우 나머지 필터는 기본값으로 둔다."
                ),
                text_format=NoticeSearchFilters,
                store=False,
            )
        except (APIError, ValidationError) as exc:
            raise NoticeSearchError(
                "공지 검색 조건을 해석하지 못했습니다. 질문을 조금 더 구체적으로 입력해 주세요."
            ) from exc
        filters = response.output_parsed
        if response.status != "completed" or filters is None:
            raise NoticeSearchError(
                "공지 검색 조건 해석이 완성되지 않았습니다. 다시 시도해 주세요."
            )
        return filters


def resolve_search_filters(
    filters: NoticeSearchFilters, reference_date: date
) -> ResolvedSearchFilters:
    start_date: date | None = None
    end_date_exclusive: date | None = None
    if filters.period == "today":
        start_date = reference_date
        end_date_exclusive = reference_date + timedelta(days=1)
    elif filters.period == "tomorrow":
        start_date = reference_date + timedelta(days=1)
        end_date_exclusive = reference_date + timedelta(days=2)
    elif filters.period in {"this_week", "next_week"}:
        monday = reference_date - timedelta(days=reference_date.weekday())
        if filters.period == "next_week":
            monday += timedelta(days=7)
        start_date = monday
        end_date_exclusive = monday + timedelta(days=7)
    elif filters.period == "custom":
        start_date = filters.start_date
        inclusive_end = filters.end_date or filters.start_date
        end_date_exclusive = inclusive_end + timedelta(days=1)

    start_at = (
        datetime.combine(start_date, time.min, tzinfo=SEOUL).isoformat()
        if start_date
        else None
    )
    end_at = (
        datetime.combine(end_date_exclusive, time.min, tzinfo=SEOUL).isoformat()
        if end_date_exclusive
        else None
    )
    return ResolvedSearchFilters(
        start_at=start_at,
        end_at=end_at,
        status=filters.status,
        status_scope=filters.status_scope,
        event_types=filters.event_types,
        period=filters.period,
        reference_date=reference_date,
    )


def format_search_response(results: list[dict[str, Any]]) -> str:
    if not results:
        return "조건에 맞는 공지나 일정을 찾지 못했습니다."
    event_count = sum(len(notice["events"]) for notice in results)
    if event_count:
        return f"조건에 맞는 공지 {len(results)}건과 일정 {event_count}건을 찾았습니다."
    return f"조건에 맞는 공지 {len(results)}건을 찾았습니다."
