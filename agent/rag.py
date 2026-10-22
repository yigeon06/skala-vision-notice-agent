"""저장된 공지 청크를 검색하고 근거 기반 답변을 생성한다."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np
from openai import APIError, AsyncOpenAI
from pydantic import BaseModel, Field, ValidationError

from agent.embeddings import EmbeddingError, EmbeddingProvider
from agent.tracing import record_trace_metadata, traceable
from notice.repository import NoticeRepository


class RAGError(RuntimeError):
    """사용자에게 노출 가능한 의미 검색 오류."""


class RAGAnswer(BaseModel):
    supported: bool = Field(
        description="검색 근거가 질문에 대한 답을 명시적으로 뒷받침하는지"
    )
    answer: str = Field(description="근거 안에서 작성한 한국어 답변")
    source_notice_ids: list[int] = Field(
        default_factory=list,
        description="답변에 실제로 사용한 공지 ID 목록",
    )


NO_SUPPORTED_ANSWER = "저장된 공지에서 질문에 해당하는 내용을 확인할 수 없습니다."


class NoticeRAGService:
    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider,
        repository: NoticeRepository,
        answer_client: AsyncOpenAI,
        answer_model: str,
        top_k: int = 3,
        chunks_per_notice: int = 2,
    ):
        self.embedding_provider = embedding_provider
        self.repository = repository
        self.answer_client = answer_client
        self.answer_model = answer_model
        self.top_k = top_k
        self.chunks_per_notice = chunks_per_notice

    @traceable(run_type="chain", name="notice.semantic_search")
    async def search(self, question: str) -> dict[str, Any]:
        chunks = self.repository.list_embedding_chunks(
            provider=self.embedding_provider.provider,
            model=self.embedding_provider.model,
        )
        if not chunks:
            record_trace_metadata(result_count=0, source_count=0)
            return {
                "message": "의미 검색이 준비된 공지가 없습니다. 공지를 새로 등록해 주세요.",
                "sources": [],
            }
        try:
            query_vector = (await self.embedding_provider.embed([question]))[0]
        except EmbeddingError:
            raise
        query = np.asarray(query_vector, dtype=np.float32)
        query_norm = float(np.linalg.norm(query))
        if query_norm == 0:
            raise RAGError("질문의 임베딩 벡터가 비어 있어 검색할 수 없습니다.")

        ranked: list[dict[str, Any]] = []
        for chunk in chunks:
            vector = np.asarray(chunk["vector"], dtype=np.float32)
            if vector.shape != query.shape:
                continue
            denominator = query_norm * float(np.linalg.norm(vector))
            score = float(np.dot(query, vector) / denominator) if denominator else 0.0
            ranked.append({**chunk, "score": score})
        ranked.sort(key=lambda item: item["score"], reverse=True)

        grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for chunk in ranked:
            grouped[int(chunk["notice_id"])].append(chunk)
        notice_ids = sorted(
            grouped,
            key=lambda notice_id: grouped[notice_id][0]["score"],
            reverse=True,
        )[: self.top_k]

        sources = []
        context_parts = []
        for notice_id in notice_ids:
            notice = self.repository.get_notice(notice_id)
            if notice is None:
                continue
            matched = grouped[notice_id][: self.chunks_per_notice]
            sources.append(
                {
                    "id": notice_id,
                    "title": notice["title"],
                    "status": notice["status"],
                    "target": notice["target"],
                    "action_required": notice["action_required"],
                    "application_method": notice["application_method"],
                    "created_at": notice["created_at"],
                    "events": notice["events"],
                    "score": round(matched[0]["score"], 4),
                    "matched_chunks": [
                        {
                            "chunk_type": chunk["chunk_type"],
                            "chunk_index": chunk["chunk_index"],
                            "score": round(chunk["score"], 4),
                        }
                        for chunk in matched
                    ],
                }
            )
            evidence = "\n\n".join(
                f"[근거 {index + 1} · {chunk['chunk_type']}]\n{chunk['content']}"
                for index, chunk in enumerate(matched)
            )
            context_parts.append(f"[공지 ID {notice_id} · {notice['title']}]\n{evidence}")

        if not sources:
            record_trace_metadata(result_count=0, source_count=0)
            return {"message": "질문과 관련된 공지를 찾지 못했습니다.", "sources": []}
        try:
            response = await self.answer_client.responses.parse(
                model=self.answer_model,
                instructions=(
                    "당신은 저장된 공지를 근거로 답하는 공지 도우미다. 제공된 근거에 있는 내용만 사용한다. "
                    "원본 OCR 근거는 인식 오류가 있을 수 있으므로 정리된 정보와 충돌하면 불확실성을 밝힌다. "
                    "질문의 조건이나 답이 근거에 명시되어 있을 때만 supported를 true로 설정한다. "
                    "자격증, 학력, 경력, 전공 또는 지원 가능 여부가 언급되지 않았다면 가능하다고 추론하지 않는다. "
                    "관련 단어가 있거나 비슷한 공지라는 이유만으로 근거가 있다고 판단하지 않는다. "
                    "supported가 true이면 답변에 실제로 사용한 공지 ID만 source_notice_ids에 넣는다. "
                    "근거가 부족하면 supported를 false로 하고 source_notice_ids는 비운다. "
                    "한국어로 간결하게 답한다."
                ),
                input=[
                    {
                        "role": "user",
                        "content": f"질문:\n{question}\n\n검색된 공지 근거:\n" + "\n\n".join(context_parts),
                    }
                ],
                text_format=RAGAnswer,
                store=False,
            )
        except (APIError, ValidationError):
            raise RAGError("검색 답변을 생성하지 못했습니다. 잠시 후 다시 시도해 주세요.") from None
        decision = response.output_parsed
        if response.status != "completed" or decision is None:
            raise RAGError("검색 답변이 완성되지 않았습니다. 다시 시도해 주세요.")
        usage = getattr(response, "usage", None)
        token_metadata = {
            "model": self.answer_model,
            "prompt_tokens": getattr(usage, "input_tokens", None),
            "completion_tokens": getattr(usage, "output_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }
        if not decision.supported:
            record_trace_metadata(**token_metadata, result_count=len(sources), source_count=0)
            return {"message": NO_SUPPORTED_ANSWER, "sources": []}

        cited_ids = set(decision.source_notice_ids)
        cited_sources = [source for source in sources if source["id"] in cited_ids]
        if not cited_sources or not decision.answer.strip():
            record_trace_metadata(**token_metadata, result_count=len(sources), source_count=0)
            return {"message": NO_SUPPORTED_ANSWER, "sources": []}
        record_trace_metadata(
            **token_metadata, result_count=len(sources), source_count=len(cited_sources),
        )
        return {"message": decision.answer.strip(), "sources": cited_sources}
