"""사용자 요청을 Agent 실행 경로로 분류한다."""

from __future__ import annotations

from typing import Literal

from openai import APIError, AsyncOpenAI
from pydantic import BaseModel, Field, ValidationError


AgentRoute = Literal["general_chat", "notice_register", "notice_search"]


class PlanningDecision(BaseModel):
    route: AgentRoute
    route_reason: str = Field(
        description="사용자에게 공개해도 되는 짧은 한국어 분류 근거"
    )


class PlanningError(RuntimeError):
    """planning node가 요청 경로를 결정하지 못한 경우."""


class OpenAIPlanner:
    def __init__(self, model: str, client: AsyncOpenAI):
        self.model = model
        self.client = client

    async def plan(
        self,
        messages: list[dict[str, str]],
        *,
        image_id: str | None = None,
    ) -> PlanningDecision:
        if image_id:
            return PlanningDecision(
                route="notice_register",
                route_reason="공지 이미지가 첨부되었습니다.",
            )

        try:
            response = await self.client.responses.parse(
                model=self.model,
                input=messages,
                instructions=(
                    "당신은 공지·일정 관리 Agent의 planning node다. "
                    "사용자의 마지막 요청이 일상적인 인사, 설명, 잡담이면 general_chat으로 분류한다. "
                    "저장된 공지의 내용, 대상, 신청 방법, 제출서류 또는 일정·마감일을 찾거나 묻는 요청은 notice_search로 분류한다. "
                    "텍스트만으로 공지를 등록하거나 이미지를 분석해 달라는 요청은 notice_register로 분류한다. "
                    "route_reason은 사용자의 요청에서 확인한 근거를 한 문장으로 간단히 작성하고 내부 추론은 포함하지 않는다."
                ),
                text_format=PlanningDecision,
                store=False,
            )
        except (APIError, ValidationError) as exc:
            raise PlanningError(
                "요청 유형을 판단하지 못했습니다. 잠시 후 다시 시도해 주세요."
            ) from exc

        decision = response.output_parsed
        if response.status != "completed" or decision is None:
            raise PlanningError(
                "요청 유형 판단이 완성되지 않았습니다. 다시 시도해 주세요."
            )
        return decision
