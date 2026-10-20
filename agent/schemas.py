"""공지 이미지에서 추출하고 저장할 구조화 데이터 스키마."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


EventType = Literal[
    "application_deadline",
    "event",
    "submission_deadline",
    "announcement",
    "other",
]


class NoticeEventExtraction(BaseModel):
    event_type: EventType = Field(
        description=(
            "신청·예약 마감은 application_deadline, 자료·비용 제출 마감은 "
            "submission_deadline, 교육·회의·행사는 event"
        )
    )
    date_text: str = Field(
        description="이미지에 적힌 날짜 표현을 생략 없이 그대로 복사"
    )
    start_at: str | None = Field(
        description="확정 가능한 경우에만 Asia/Seoul ISO 8601 시각"
    )
    end_at: str | None = Field(
        description="종료 시각이 명시된 경우에만 ISO 8601 시각"
    )
    all_day: bool
    location: str | None
    evidence_text: str = Field(
        description="일정을 판단한 이미지의 원문 한 줄을 그대로 복사"
    )
    confidence: float = Field(ge=0.0, le=1.0)


class NoticeExtraction(BaseModel):
    title: str = Field(description="공지 상단의 제목을 그대로 복사")
    target: list[str] = Field(description="공지 대상")
    action_required: list[str] = Field(description="대상이 해야 하는 일")
    application_method: str | None
    raw_text: str = Field(
        description="제목과 본문을 포함해 이미지에서 읽은 전체 원문"
    )
    events: list[NoticeEventExtraction] = Field(
        description="모든 마감과 행사 일정. 날짜가 모호해도 event를 만들고 start_at은 null",
    )
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractionValidation(BaseModel):
    status: Literal["confirmed", "needs_review"]
    issues: list[str] = Field(default_factory=list)

