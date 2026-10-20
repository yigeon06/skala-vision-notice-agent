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


class RecruitmentPosition(BaseModel):
    name: str = Field(description="이미지에 표시된 모집 분야명")
    responsibilities: list[str] = Field(description="해당 분야의 수행업무")
    preferred_qualifications: list[str] = Field(description="해당 분야의 우대사항")


AdditionalInformationCategory = Literal[
    "preferred_certification",
    "required_document",
    "disqualification",
    "notice",
    "other",
]


class AdditionalInformation(BaseModel):
    category: AdditionalInformationCategory
    title: str = Field(description="원문에 표시된 정보 영역의 제목")
    items: list[str] = Field(description="중복을 제거한 중요 정보 항목")
    evidence_text: str = Field(description="판단 근거가 된 OCR 원문")
    confidence: float = Field(ge=0.0, le=1.0)
    needs_review: bool = Field(
        description="OCR 오류나 해석 불확실성으로 사용자 확인이 필요한지 여부"
    )


class StructuredNoticeExtraction(BaseModel):
    title: str = Field(description="공지 상단의 제목을 그대로 복사")
    target: list[str] = Field(description="공지 대상")
    action_required: list[str] = Field(description="대상이 해야 하는 일")
    application_method: str | None
    cleaned_text: str = Field(
        description="OCR 중복과 명백한 오탈자를 정리한 전체 공지문"
    )
    recruitment_positions: list[RecruitmentPosition] = Field(
        description="모집분야별 수행업무와 우대사항. 채용 공지가 아니면 빈 배열"
    )
    additional_information: list[AdditionalInformation] = Field(
        description="기존 필드에 속하지 않는 자격증, 서류, 불이익, 유의사항 등의 중요 정보"
    )
    events: list[NoticeEventExtraction] = Field(
        description="모든 마감과 행사 일정. 날짜가 모호해도 event를 만들고 start_at은 null",
    )
    confidence: float = Field(ge=0.0, le=1.0)


class NoticeExtraction(StructuredNoticeExtraction):
    raw_text: str = Field(description="Ollama가 인식한 병합 전후의 원본 OCR 증거")


class ExtractionValidation(BaseModel):
    status: Literal["confirmed", "needs_review"]
    issues: list[str] = Field(default_factory=list)

