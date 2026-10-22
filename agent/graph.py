"""planning node와 기능별 실행 노드를 연결한 LangGraph."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Any, TypedDict
from zoneinfo import ZoneInfo

from langgraph.graph import END, START, StateGraph

from agent.chat_llm import OpenAIChatLLM
from agent.planner import AgentRoute, OpenAIPlanner
from agent.rag import NoticeRAGService
from agent.search import (
    OpenAINoticeSearchParser,
    SearchMode,
    format_search_response,
    resolve_search_filters,
)
from agent.tracing import record_trace_metadata
from notice.repository import NoticeRepository


SEOUL = ZoneInfo("Asia/Seoul")


class AgentState(TypedDict, total=False):
    messages: list[dict[str, str]]
    image_id: str | None
    search_mode: SearchMode
    reference_date: date | None
    route: AgentRoute
    route_reason: str
    message: str
    data: dict[str, Any]


ExtractNotice = Callable[
    [str, date | None],
    Awaitable[tuple[Any, Any, Any, dict[str, Any]]],
]


def create_agent_graph(
    *,
    planner: OpenAIPlanner,
    chat_llm: OpenAIChatLLM,
    extract_notice: ExtractNotice,
    search_parser: OpenAINoticeSearchParser,
    notice_repository: NoticeRepository,
    rag_service: NoticeRAGService | None = None,
):
    async def planning_node(state: AgentState) -> dict[str, Any]:
        mode = state.get("search_mode", "auto")
        if not state.get("image_id") and mode != "auto":
            return {
                "route": "notice_search",
                "route_reason": "사용자가 선택한 조회 방식으로 처리합니다.",
            }
        decision = await planner.plan(
            state.get("messages", []), image_id=state.get("image_id")
        )
        return decision.model_dump()

    async def general_chat_node(state: AgentState) -> dict[str, Any]:
        content = await chat_llm.reply(state["messages"])
        return {"message": content, "data": {}}

    async def notice_register_node(state: AgentState) -> dict[str, Any]:
        image_id = state.get("image_id")
        if not image_id:
            return {
                "message": "등록할 공지 이미지를 첨부해 주세요.",
                "data": {"requires_image": True},
            }
        _, extraction, validation, usage = await extract_notice(
            image_id, state.get("reference_date")
        )
        return {
            "message": "공지 내용을 정리했습니다. 확인하거나 수정한 뒤 저장해 주세요.",
            "data": {
                "image_id": image_id,
                "extraction": extraction.model_dump(mode="json"),
                "validation": validation.model_dump(mode="json"),
                "usage": usage,
            },
        }

    async def notice_search_node(state: AgentState) -> dict[str, Any]:
        reference_date = state.get("reference_date") or datetime.now(SEOUL).date()
        mode = state.get("search_mode", "auto")
        parsed = None
        if mode != "semantic_search":
            options = {"force_structured": True} if mode == "structured_search" else {}
            parsed = await search_parser.parse(
                state["messages"], reference_date=reference_date, **options
            )
        if mode == "semantic_search" or (
            mode == "auto" and parsed.search_type == "semantic_search"
        ):
            if rag_service is not None:
                result = await rag_service.search(state["messages"][-1]["content"])
                return {
                    "message": result["message"],
                    "data": {
                        "search_type": "semantic_search",
                        "available": True,
                        "sources": result["sources"],
                    },
                }
            return {
                "message": "내용·의미 기반 공지 검색은 다음 단계에서 연결할 예정입니다.",
                "data": {
                    "search_type": "semantic_search",
                    "available": False,
                },
            }
        filters = resolve_search_filters(parsed, reference_date)
        results = notice_repository.search_notices(
            start_at=filters.start_at,
            end_at=filters.end_at,
            status=filters.status,
            status_scope=filters.status_scope,
            event_types=filters.event_types,
        )
        record_trace_metadata(
            search_type="structured_search", period=filters.period,
            status=filters.status, result_count=len(results),
        )
        return {
            "message": format_search_response(results),
            "data": {
                "search_type": "structured_search",
                "filters": filters.model_dump(mode="json"),
                "notices": results,
            },
        }

    builder = StateGraph(AgentState)
    builder.add_node("planning", planning_node)
    builder.add_node("general_chat", general_chat_node)
    builder.add_node("notice_register", notice_register_node)
    builder.add_node("notice_search", notice_search_node)
    builder.add_edge(START, "planning")
    builder.add_conditional_edges(
        "planning",
        lambda state: state["route"],
        {
            "general_chat": "general_chat",
            "notice_register": "notice_register",
            "notice_search": "notice_search",
        },
    )
    builder.add_edge("general_chat", END)
    builder.add_edge("notice_register", END)
    builder.add_edge("notice_search", END)
    return builder.compile()
