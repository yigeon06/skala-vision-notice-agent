"""실제 모델 호출 없이 planning node와 /agent 계약을 검증한다."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import APIConnectionError

import server
from agent.graph import create_agent_graph
from agent.planner import OpenAIPlanner, PlanningDecision, PlanningError
from agent.search import NoticeSearchFilters
from agent.schemas import ExtractionValidation, NoticeExtraction


def _extraction() -> NoticeExtraction:
    return NoticeExtraction.model_validate(
        {
            "title": "테스트 공지",
            "target": ["전 임직원"],
            "action_required": ["신청"],
            "application_method": "사내 포털",
            "raw_text": "신청 마감: 2026년 10월 25일",
            "cleaned_text": "신청 마감: 2026년 10월 25일",
            "recruitment_positions": [],
            "additional_information": [],
            "events": [],
            "confidence": 0.99,
        }
    )


class FakePlanner:
    def __init__(self, route: str = "general_chat"):
        self.route = route
        self.calls: list[tuple[list[dict[str, str]], str | None]] = []

    async def plan(self, messages, *, image_id=None):
        self.calls.append((messages, image_id))
        if image_id:
            return PlanningDecision(
                route="notice_register",
                route_reason="공지 이미지가 첨부되었습니다.",
            )
        return PlanningDecision(
            route=self.route,
            route_reason="테스트 분류 결과입니다.",
        )


class FakeChatLLM:
    def __init__(self):
        self.messages = None

    async def reply(self, messages):
        self.messages = messages
        return "일반 대화 응답"


class FakeSearchParser:
    async def parse(self, messages, *, reference_date):
        return NoticeSearchFilters(
            period="this_week",
            event_types=["application_deadline", "submission_deadline"],
        )


class FakeRepository:
    def search_notices(self, **filters):
        return []


class FakeRAGService:
    async def search(self, question):
        return {
            "message": "보안교육은 사내 포털에서 신청합니다.",
            "sources": [{"id": 7, "title": "보안교육 안내", "score": 0.91}],
        }


@pytest.fixture
def agent_client(tmp_path, monkeypatch):
    planner = FakePlanner()
    chat_llm = FakeChatLLM()
    extract_notice = AsyncMock(
        return_value=(
            SimpleNamespace(),
            _extraction(),
            ExtractionValidation(status="needs_review", issues=["일정이 없습니다."]),
            {"elapsed_seconds": 0},
        )
    )
    graph = create_agent_graph(
        planner=planner,
        chat_llm=chat_llm,
        extract_notice=extract_notice,
        search_parser=FakeSearchParser(),
        notice_repository=FakeRepository(),
    )
    monkeypatch.setattr(server, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        server, "OpenAIStructuredLLM", lambda **_: SimpleNamespace(client=object())
    )
    monkeypatch.setattr(server, "OllamaVisionLLM", lambda **_: object())
    monkeypatch.setattr(server, "NoticeExtractor", lambda *_: object())
    monkeypatch.setattr(server, "create_agent_graph", lambda **_: graph)
    with TestClient(server.app) as client:
        yield client, planner, chat_llm, extract_notice


def test_agent_routes_general_chat(agent_client):
    client, planner, chat_llm, extract_notice = agent_client
    messages = [{"role": "user", "content": "안녕"}]
    response = client.post("/agent", json={"messages": messages})
    assert response.status_code == 200
    assert response.json() == {
        "route": "general_chat",
        "route_reason": "테스트 분류 결과입니다.",
        "message": "일반 대화 응답",
        "data": {},
    }
    assert planner.calls == [(messages, None)]
    assert chat_llm.messages == messages
    extract_notice.assert_not_awaited()


def test_agent_routes_image_to_notice_register(agent_client):
    client, planner, chat_llm, extract_notice = agent_client
    response = client.post(
        "/agent",
        json={"image_id": "image-1", "reference_date": "2026-10-21"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["route"] == "notice_register"
    assert body["data"]["image_id"] == "image-1"
    assert body["data"]["extraction"]["title"] == "테스트 공지"
    assert body["data"]["validation"]["status"] == "needs_review"
    assert planner.calls == [([], "image-1")]
    assert chat_llm.messages is None
    extract_notice.assert_awaited_once()


def test_notice_search_runs_structured_search(agent_client):
    client, planner, chat_llm, extract_notice = agent_client
    planner.route = "notice_search"
    response = client.post(
        "/agent",
        json={"messages": [{"role": "user", "content": "이번 주 마감 공지 알려줘"}]},
    )
    assert response.status_code == 200
    assert response.json()["route"] == "notice_search"
    assert response.json()["data"]["search_type"] == "structured_search"
    assert response.json()["data"]["filters"]["period"] == "this_week"
    assert response.json()["data"]["notices"] == []
    assert "찾지 못했습니다" in response.json()["message"]
    assert chat_llm.messages is None
    extract_notice.assert_not_awaited()


def test_notice_search_runs_semantic_rag():
    planner = FakePlanner(route="notice_search")
    parser = FakeSearchParser()
    parser.parse = AsyncMock(
        return_value=NoticeSearchFilters(search_type="semantic_search")
    )
    graph = create_agent_graph(
        planner=planner,
        chat_llm=FakeChatLLM(),
        extract_notice=AsyncMock(),
        search_parser=parser,
        notice_repository=FakeRepository(),
        rag_service=FakeRAGService(),
    )
    result = asyncio.run(
        graph.ainvoke(
            {"messages": [{"role": "user", "content": "보안교육 신청 방법이 뭐야?"}]}
        )
    )
    assert result["data"]["search_type"] == "semantic_search"
    assert result["data"]["available"] is True
    assert result["data"]["sources"][0]["id"] == 7
    assert "사내 포털" in result["message"]


def test_text_register_request_requires_image(agent_client):
    client, planner, chat_llm, extract_notice = agent_client
    planner.route = "notice_register"
    response = client.post(
        "/agent",
        json={"messages": [{"role": "user", "content": "공지를 등록해줘"}]},
    )
    assert response.status_code == 200
    assert response.json()["data"] == {"requires_image": True}
    assert "이미지를 첨부" in response.json()["message"]
    assert chat_llm.messages is None
    extract_notice.assert_not_awaited()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"messages": [{"role": "assistant", "content": "답변"}]},
        {"messages": [{"role": "user", "content": "  "}]},
    ],
)
def test_agent_rejects_invalid_request(agent_client, payload):
    client, planner, _, extract_notice = agent_client
    assert client.post("/agent", json=payload).status_code == 422
    assert planner.calls == []
    extract_notice.assert_not_awaited()


def test_planner_uses_structured_output_for_text_request():
    parse = AsyncMock(
        return_value=SimpleNamespace(
            status="completed",
            output_parsed=PlanningDecision(
                route="notice_search",
                route_reason="마감 공지를 묻는 요청입니다.",
            ),
        )
    )
    planner = OpenAIPlanner(
        model="fake-model",
        client=SimpleNamespace(responses=SimpleNamespace(parse=parse)),
    )
    messages = [{"role": "user", "content": "이번 주 마감 공지 알려줘"}]
    decision = asyncio.run(planner.plan(messages))
    assert decision.route == "notice_search"
    assert parse.call_args.kwargs["input"] == messages
    assert parse.call_args.kwargs["text_format"] is PlanningDecision
    assert parse.call_args.kwargs["store"] is False


def test_planner_skips_model_when_image_is_present():
    parse = AsyncMock()
    planner = OpenAIPlanner(
        model="fake-model",
        client=SimpleNamespace(responses=SimpleNamespace(parse=parse)),
    )
    decision = asyncio.run(planner.plan([], image_id="image-1"))
    assert decision.route == "notice_register"
    parse.assert_not_awaited()


def test_planner_hides_external_api_error():
    parse = AsyncMock(
        side_effect=APIConnectionError(
            message="PRIVATE_REQUEST_DETAILS",
            request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
        )
    )
    planner = OpenAIPlanner(
        model="fake-model",
        client=SimpleNamespace(responses=SimpleNamespace(parse=parse)),
    )
    with pytest.raises(PlanningError, match="요청 유형을 판단하지 못했습니다") as exc_info:
        asyncio.run(planner.plan([{"role": "user", "content": "안녕"}]))
    assert "PRIVATE_REQUEST_DETAILS" not in str(exc_info.value)
