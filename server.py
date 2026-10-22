"""Vision 기반 사내 공지·일정 관리 API."""

from __future__ import annotations

import hashlib
import os
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

# LangGraph와 @traceable 모두 같은 안전한 추적 설정을 사용한다.
_tracing_enabled = os.environ.get(
    "LANGSMITH_TRACING", os.environ.get("LANGCHAIN_TRACING_V2", "false")
).lower() == "true"
if _tracing_enabled:
    _langsmith_key = os.environ.get("LANGSMITH_API_KEY") or os.environ.get(
        "LANGCHAIN_API_KEY", ""
    )
    if not _langsmith_key or _langsmith_key.startswith("lsv2_pt_..."):
        raise RuntimeError("LangSmith 추적을 켜려면 실제 API 키가 필요합니다.")
    os.environ["LANGSMITH_API_KEY"] = _langsmith_key
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGSMITH_HIDE_INPUTS"] = "true"
    os.environ["LANGSMITH_HIDE_OUTPUTS"] = "true"
    os.environ.setdefault(
        "LANGSMITH_PROJECT", os.environ.get("LANGCHAIN_PROJECT", "notice-schedule-agent")
    )
    os.environ.setdefault(
        "LANGSMITH_ENDPOINT",
        os.environ.get("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com"),
    )

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator, model_validator

from agent.notice_extractor import NoticeExtractor
from agent.chat_llm import ChatError, OpenAIChatLLM
from agent.embeddings import (
    EmbeddingError,
    OllamaEmbeddingProvider,
    OpenAIEmbeddingProvider,
    build_notice_chunks,
)
from agent.graph import create_agent_graph
from agent.planner import OpenAIPlanner, PlanningError
from agent.rag import NoticeRAGService, RAGError
from agent.search import NoticeSearchError, OpenAINoticeSearchParser
from agent.schemas import NoticeExtraction
from agent.structured_llm import OpenAIStructuredLLM, StructuredOutputError
from agent.vision_llm import OCRError, OllamaVisionLLM
from agent.tracing import record_trace_metadata, traceable
from notice.image_store import ImageStore
from notice.repository import NoticeRepository
from notice.service import extract_with_validation, validate_extraction


PROJECT_ROOT = Path(__file__).resolve().parent
SEOUL = ZoneInfo("Asia/Seoul")


class ExtractNoticeRequest(BaseModel):
    image_id: str
    reference_date: date | None = None


class RegisterNoticeRequest(ExtractNoticeRequest):
    request_id: str
    extraction: NoticeExtraction


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str

    @field_validator("content")
    @classmethod
    def non_empty_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("메시지를 입력해 주세요.")
        return value


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)

    @model_validator(mode="after")
    def last_message_is_user(self):
        if self.messages[-1].role != "user":
            raise ValueError("마지막 메시지는 사용자 메시지여야 합니다.")
        return self


class AgentRequest(BaseModel):
    search_mode: Literal["auto", "structured_search", "semantic_search"] = "auto"
    messages: list[ChatMessage] = Field(default_factory=list)
    image_id: str | None = None
    reference_date: date | None = None

    @model_validator(mode="after")
    def validate_agent_input(self):
        if not self.messages and not self.image_id:
            raise ValueError("메시지 또는 공지 이미지가 필요합니다.")
        if self.messages and self.messages[-1].role != "user":
            raise ValueError("마지막 메시지는 사용자 메시지여야 합니다.")
        return self


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.image_store = ImageStore(PROJECT_ROOT / "data" / "uploads")
    app.state.notice_repository = NoticeRepository(PROJECT_ROOT / "data" / "notices.db")
    vision_llm = OllamaVisionLLM(
        model=os.environ.get("OLLAMA_VISION_MODEL", "qwen3-vl:4b-instruct"),
        num_ctx=int(os.environ.get("OLLAMA_VISION_NUM_CTX", "16384")),
    )
    structured_llm = OpenAIStructuredLLM(
        model=os.environ.get("OPENAI_TEXT_MODEL", "gpt-4o-mini"),
        timeout_sec=float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "60")),
        max_retries=int(os.environ.get("OPENAI_MAX_RETRIES", "2")),
    )
    app.state.notice_extractor = NoticeExtractor(vision_llm, structured_llm)
    app.state.chat_llm = OpenAIChatLLM(
        model=os.environ.get("OPENAI_TEXT_MODEL", "gpt-4o-mini"),
        client=structured_llm.client,
    )
    app.state.planner = OpenAIPlanner(
        model=os.environ.get("OPENAI_TEXT_MODEL", "gpt-4o-mini"),
        client=structured_llm.client,
    )
    app.state.search_parser = OpenAINoticeSearchParser(
        model=os.environ.get("OPENAI_TEXT_MODEL", "gpt-4o-mini"),
        client=structured_llm.client,
    )
    embedding_provider_name = os.environ.get("EMBEDDING_PROVIDER", "ollama").lower()
    if embedding_provider_name == "ollama":
        app.state.embedding_provider = OllamaEmbeddingProvider(
            model=os.environ.get("OLLAMA_EMBEDDING_MODEL", "bge-m3"),
            base_url=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            timeout_sec=float(os.environ.get("EMBEDDING_TIMEOUT_SECONDS", "60")),
        )
    elif embedding_provider_name == "openai":
        app.state.embedding_provider = OpenAIEmbeddingProvider(
            model=os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
            client=structured_llm.client,
        )
    else:
        raise RuntimeError("EMBEDDING_PROVIDER는 ollama 또는 openai여야 합니다.")
    app.state.embedding_chunk_size = int(
        os.environ.get("EMBEDDING_CHUNK_SIZE", "1800")
    )
    app.state.embedding_chunk_overlap = int(
        os.environ.get("EMBEDDING_CHUNK_OVERLAP", "250")
    )
    app.state.rag_service = NoticeRAGService(
        embedding_provider=app.state.embedding_provider,
        repository=app.state.notice_repository,
        answer_client=structured_llm.client,
        answer_model=os.environ.get("OPENAI_TEXT_MODEL", "gpt-4o-mini"),
        top_k=int(os.environ.get("SEMANTIC_SEARCH_TOP_K", "3")),
        chunks_per_notice=int(os.environ.get("RAG_CHUNKS_PER_NOTICE", "2")),
    )
    app.state.agent_graph = create_agent_graph(
        planner=app.state.planner,
        chat_llm=app.state.chat_llm,
        extract_notice=_extract_notice,
        search_parser=app.state.search_parser,
        notice_repository=app.state.notice_repository,
        rag_service=app.state.rag_service,
    )
    yield


app = FastAPI(
    title="Vision Notice Schedule Agent",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


def _image_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@traceable(run_type="chain", name="notice.extract")
async def _extract_notice(image_id: str, reference_date: date | None):
    try:
        image_path = app.state.image_store.resolve(image_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="업로드 이미지를 찾을 수 없습니다.") from None

    effective_date = reference_date or datetime.now(SEOUL).date()
    try:
        normalized, validation, usage = await extract_with_validation(
            app.state.notice_extractor, image_path, effective_date
        )
    except OCRError as exc:
        raise HTTPException(status_code=502, detail=f"OCR 실패: {exc}") from None
    except StructuredOutputError as exc:
        raise HTTPException(status_code=502, detail=f"JSON 구조화 실패: {exc}") from None

    record_trace_metadata(
        validation_status=validation.status,
        event_count=len(normalized.events),
        elapsed_seconds=usage.get("elapsed_seconds"),
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
    )
    return image_path, normalized, validation, usage


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "vision_model": app.state.notice_extractor.vision_llm.model,
        "vision_num_ctx": app.state.notice_extractor.vision_llm.num_ctx,
        "openai_text_model": app.state.notice_extractor.structured_llm.model,
        "embedding_provider": app.state.embedding_provider.provider,
        "embedding_model": app.state.embedding_provider.model,
    }


@app.post("/images")
@traceable(run_type="chain", name="notice.upload_image")
async def upload_image(file: UploadFile = File(...)):
    data = await file.read(10 * 1024 * 1024 + 1)
    try:
        stored = app.state.image_store.save(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {**stored, "original_filename": file.filename}


@app.post("/notices/extract")
@traceable(run_type="chain", name="notice.extract_api")
async def extract_notice(req: ExtractNoticeRequest):
    _, extraction, validation, usage = await _extract_notice(
        req.image_id, req.reference_date
    )
    return {
        "extraction": extraction.model_dump(mode="json"),
        "validation": validation.model_dump(mode="json"),
        "usage": usage,
    }


@app.post("/chat")
@traceable(run_type="chain", name="notice.chat_api")
async def chat(req: ChatRequest):
    try:
        content = await app.state.chat_llm.reply(
            [message.model_dump() for message in req.messages]
        )
    except ChatError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    return {"role": "assistant", "content": content}


@app.post("/agent")
@traceable(run_type="chain", name="notice.agent_api")
async def run_agent(req: AgentRequest):
    try:
        result = await app.state.agent_graph.ainvoke(
            {
                "messages": [message.model_dump() for message in req.messages],
                "image_id": req.image_id,
                "reference_date": req.reference_date,
                "search_mode": req.search_mode,
            }
        )
    except (PlanningError, NoticeSearchError, ChatError, EmbeddingError, RAGError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    record_trace_metadata(
        route=result["route"],
        search_mode=req.search_mode,
        search_type=result.get("data", {}).get("search_type"),
    )
    return {
        "route": result["route"],
        "route_reason": result["route_reason"],
        "message": result["message"],
        "data": result.get("data", {}),
    }


@app.post("/notices/register")
@traceable(run_type="chain", name="notice.register_api")
async def register_notice(req: RegisterNoticeRequest):
    try:
        image_path = app.state.image_store.resolve(req.image_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="업로드 이미지를 찾을 수 없습니다.") from None

    extraction = req.extraction
    validation = validate_extraction(extraction)
    notice_id, created = app.state.notice_repository.save_notice(
        request_id=req.request_id,
        extraction=extraction,
        source_image_path=str(image_path),
        source_image_hash=_image_sha256(image_path),
        status=validation.status,
    )
    embedding = {
        "status": "ready",
        "provider": app.state.embedding_provider.provider,
        "model": app.state.embedding_provider.model,
    }
    try:
        chunks = build_notice_chunks(
            extraction,
            chunk_size=app.state.embedding_chunk_size,
            overlap=app.state.embedding_chunk_overlap,
        )
        vectors = await app.state.embedding_provider.embed(
            [chunk.content for chunk in chunks]
        )
        app.state.notice_repository.save_embedding_chunks(
            notice_id=notice_id,
            provider=app.state.embedding_provider.provider,
            model=app.state.embedding_provider.model,
            chunks=chunks,
            vectors=vectors,
        )
        embedding["chunk_count"] = len(chunks)
    except EmbeddingError as exc:
        embedding = {
            "status": "failed",
            "provider": app.state.embedding_provider.provider,
            "model": app.state.embedding_provider.model,
            "warning": str(exc),
        }
    record_trace_metadata(
        created=created,
        validation_status=validation.status,
        event_count=len(extraction.events),
        embedding_status=embedding["status"],
        chunk_count=embedding.get("chunk_count"),
    )
    return {
        "notice_id": notice_id,
        "created": created,
        "status": validation.status,
        "issues": validation.issues,
        "extraction": extraction.model_dump(mode="json"),
        "embedding": embedding,
        "usage": {
            "models": {},
            "elapsed_seconds": 0,
            "source": "provided_extraction",
        },
    }


@app.get("/notices")
async def list_notices():
    return {"items": app.state.notice_repository.list_notices()}


@app.get("/calendar/events")
async def calendar_events(
    year: int = Query(ge=1, le=9998), month: int = Query(ge=1, le=12)
):
    month_start = date(year, month, 1).isoformat()
    next_month_start = (
        date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    ).isoformat()
    return app.state.notice_repository.list_calendar_events(
        month_start, next_month_start
    )


@app.get("/notices/{notice_id}")
async def get_notice(notice_id: int):
    notice = app.state.notice_repository.get_notice(notice_id)
    if notice is None:
        raise HTTPException(status_code=404, detail="공지를 찾을 수 없습니다.")
    return notice


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8100, log_level="info")
