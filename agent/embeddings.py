"""공지 청킹과 교체 가능한 임베딩 제공자."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Protocol

import httpx
from openai import APIError, AsyncOpenAI

from agent.schemas import NoticeExtraction
from agent.tracing import record_trace_metadata, traceable


class EmbeddingError(RuntimeError):
    """임베딩 생성 실패를 외부 서비스 세부 정보 없이 전달한다."""


class EmbeddingProvider(Protocol):
    provider: str
    model: str

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class EmbeddingChunk:
    chunk_type: str
    chunk_index: int
    content: str

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


class OllamaEmbeddingProvider:
    provider = "ollama"

    def __init__(
        self,
        model: str = "bge-m3",
        *,
        base_url: str = "http://127.0.0.1:11434",
        timeout_sec: float = 60.0,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec

    @traceable(run_type="embedding", name="notice.embed_ollama")
    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
                response = await client.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.model, "input": texts, "truncate": False},
                )
                response.raise_for_status()
                body = response.json()
                embeddings = body.get("embeddings") if isinstance(body, dict) else None
        except (httpx.HTTPError, TypeError, ValueError):
            raise EmbeddingError(
                "Ollama 임베딩을 생성하지 못했습니다. 서버와 모델을 확인해 주세요."
            ) from None
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise EmbeddingError("Ollama 임베딩 응답 형식이 올바르지 않습니다.")
        vectors = _validate_vectors(embeddings)
        record_trace_metadata(provider=self.provider, model=self.model, chunk_count=len(texts))
        return vectors


class OpenAIEmbeddingProvider:
    provider = "openai"

    def __init__(self, model: str, client: AsyncOpenAI):
        self.model = model
        self.client = client

    @traceable(run_type="embedding", name="notice.embed_openai")
    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            response = await self.client.embeddings.create(
                model=self.model,
                input=texts,
                encoding_format="float",
            )
        except APIError:
            raise EmbeddingError("OpenAI 임베딩을 생성하지 못했습니다.") from None
        ordered = sorted(response.data, key=lambda item: item.index)
        if len(ordered) != len(texts):
            raise EmbeddingError("OpenAI 임베딩 응답 개수가 일치하지 않습니다.")
        vectors = _validate_vectors([item.embedding for item in ordered])
        record_trace_metadata(provider=self.provider, model=self.model, chunk_count=len(texts))
        return vectors


def _validate_vectors(vectors: list[list[float]]) -> list[list[float]]:
    try:
        if not vectors or any(not vector for vector in vectors):
            raise EmbeddingError("빈 임베딩 벡터가 반환되었습니다.")
        dimensions = len(vectors[0])
        if any(len(vector) != dimensions for vector in vectors):
            raise EmbeddingError("임베딩 벡터 차원이 일치하지 않습니다.")
        return [[float(value) for value in vector] for vector in vectors]
    except (TypeError, ValueError):
        raise EmbeddingError("임베딩 벡터 형식이 올바르지 않습니다.") from None


def build_notice_chunks(
    extraction: NoticeExtraction,
    *,
    chunk_size: int = 1800,
    overlap: int = 250,
) -> list[EmbeddingChunk]:
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("청크 크기는 양수이고 중첩은 청크 크기보다 작아야 합니다.")

    chunks = [EmbeddingChunk("structured", 0, _structured_document(extraction))]
    for chunk_type, text in (
        ("cleaned_text", extraction.cleaned_text),
        ("raw_text", extraction.raw_text),
    ):
        for index, body in enumerate(split_text(text, chunk_size, overlap)):
            chunks.append(
                EmbeddingChunk(
                    chunk_type,
                    index,
                    f"[공지 제목]\n{extraction.title}\n\n[본문 종류]\n{chunk_type}\n\n[본문]\n{body}",
                )
            )
    return chunks


def split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """문장 경계를 우선하며 긴 단일 문장만 글자 위치로 나눈다."""
    normalized = re.sub(r"[ \t]+", " ", text or "").strip()
    if not normalized:
        return []
    units = [
        part.strip()
        for part in re.split(r"(?<=[.!?。！？])\s+|\n+", normalized)
        if part.strip()
    ]
    expanded: list[str] = []
    for unit in units:
        if len(unit) <= chunk_size:
            expanded.append(unit)
            continue
        start = 0
        step = chunk_size - overlap
        while start < len(unit):
            expanded.append(unit[start : start + chunk_size])
            start += step

    result: list[str] = []
    current: list[str] = []
    for unit in expanded:
        candidate = "\n".join([*current, unit])
        if current and len(candidate) > chunk_size:
            result.append("\n".join(current))
            current = _overlap_units(current, overlap)
            while current and len("\n".join([*current, unit])) > chunk_size:
                current.pop(0)
        current.append(unit)
    if current:
        result.append("\n".join(current))
    return result


def _overlap_units(units: list[str], overlap: int) -> list[str]:
    if overlap == 0:
        return []
    selected: list[str] = []
    length = 0
    for unit in reversed(units):
        selected.insert(0, unit)
        length += len(unit) + (1 if selected else 0)
        if length >= overlap:
            break
    return selected


def _structured_document(extraction: NoticeExtraction) -> str:
    sections = [
        ("공지 제목", [extraction.title]),
        ("대상", extraction.target),
        ("해야 할 일", extraction.action_required),
        ("신청 방법", [extraction.application_method or "별도 안내 없음"]),
    ]
    events = [
        " | ".join(
            filter(None, [event.event_type, event.date_text, event.location, event.evidence_text])
        )
        for event in extraction.events
    ]
    sections.append(("일정", events))
    positions = []
    for position in extraction.recruitment_positions:
        positions.append(
            f"{position.name}\n수행업무: {', '.join(position.responsibilities)}\n"
            f"우대사항: {', '.join(position.preferred_qualifications)}"
        )
    sections.append(("모집 분야", positions))
    additional = [
        f"{item.title} ({item.category})\n{', '.join(item.items)}\n근거: {item.evidence_text}"
        for item in extraction.additional_information
    ]
    sections.append(("기타 중요 정보", additional))
    return "\n\n".join(
        f"[{title}]\n" + ("\n".join(values) if values else "별도 안내 없음")
        for title, values in sections
    )
