"""문자 청킹, 임베딩 저장과 공지 단위 RAG 검색을 검증한다."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from agent.embeddings import EmbeddingChunk, build_notice_chunks, split_text
from agent.rag import NO_SUPPORTED_ANSWER, NoticeRAGService, RAGAnswer
from agent.schemas import NoticeExtraction
from notice.repository import NoticeRepository


def _notice(title: str, *, cleaned_text: str = "정리된 전체 공지", raw_text: str = "원본 OCR"):
    return NoticeExtraction.model_validate(
        {
            "title": title,
            "target": ["전 임직원"],
            "action_required": ["신청하기"],
            "application_method": "사내 포털",
            "cleaned_text": cleaned_text,
            "raw_text": raw_text,
            "events": [],
            "recruitment_positions": [
                {
                    "name": "AI 개발",
                    "responsibilities": ["서비스 개발"],
                    "preferred_qualifications": ["Python"],
                }
            ],
            "additional_information": [],
            "confidence": 0.9,
        }
    )


def _save(repository: NoticeRepository, request_id: str, extraction: NoticeExtraction) -> int:
    notice_id, _ = repository.save_notice(
        request_id=request_id,
        extraction=extraction,
        source_image_path=f"{request_id}.png",
        source_image_hash=request_id,
        status="confirmed",
    )
    return notice_id


def test_notice_chunks_include_structured_cleaned_and_raw_text():
    chunks = build_notice_chunks(_notice("채용 공지"), chunk_size=1800, overlap=250)
    assert [chunk.chunk_type for chunk in chunks] == [
        "structured",
        "cleaned_text",
        "raw_text",
    ]
    assert "Python" in chunks[0].content
    assert "정리된 전체 공지" in chunks[1].content
    assert "원본 OCR" in chunks[2].content


def test_split_text_preserves_overlap_between_long_sections():
    text = "첫 번째 문장입니다.\n" + ("가" * 30) + "\n마지막 문장입니다."
    chunks = split_text(text, chunk_size=45, overlap=10)
    assert len(chunks) > 1
    assert any(part in chunks[1] for part in chunks[0].splitlines())


def test_repository_replaces_chunks_for_same_provider_and_model(tmp_path):
    repository = NoticeRepository(tmp_path / "notices.db")
    notice_id = _save(repository, "one", _notice("공지"))
    repository.save_embedding_chunks(
        notice_id=notice_id,
        provider="ollama",
        model="bge-m3",
        chunks=[EmbeddingChunk("structured", 0, "이전 내용")],
        vectors=[[1.0, 0.0]],
    )
    repository.save_embedding_chunks(
        notice_id=notice_id,
        provider="ollama",
        model="bge-m3",
        chunks=[EmbeddingChunk("structured", 0, "새 내용")],
        vectors=[[0.0, 1.0]],
    )
    chunks = repository.list_embedding_chunks(provider="ollama", model="bge-m3")
    assert len(chunks) == 1
    assert chunks[0]["content"] == "새 내용"
    assert chunks[0]["vector"] == [0.0, 1.0]


def test_rag_groups_chunks_and_returns_top_three_notices(tmp_path):
    repository = NoticeRepository(tmp_path / "notices.db")
    vectors = ([1.0, 0.0], [0.9, 0.1], [0.7, 0.3], [0.2, 0.8])
    for index, vector in enumerate(vectors):
        notice_id = _save(repository, str(index), _notice(f"공지 {index}"))
        repository.save_embedding_chunks(
            notice_id=notice_id,
            provider="fake",
            model="fake-model",
            chunks=[EmbeddingChunk("structured", 0, f"공지 {index} 근거")],
            vectors=[vector],
        )

    provider = SimpleNamespace(provider="fake", model="fake-model")
    provider.embed = AsyncMock(return_value=[[1.0, 0.0]])
    parse = AsyncMock(
        return_value=SimpleNamespace(
            status="completed",
            output_parsed=RAGAnswer(
                supported=True,
                answer="근거 기반 답변",
                source_notice_ids=[1, 3, 999],
            ),
        )
    )
    service = NoticeRAGService(
        embedding_provider=provider,
        repository=repository,
        answer_client=SimpleNamespace(responses=SimpleNamespace(parse=parse)),
        answer_model="fake-answer-model",
        top_k=3,
        chunks_per_notice=2,
    )

    result = asyncio.run(service.search("Python 우대 공지"))

    assert result["message"] == "근거 기반 답변"
    assert [source["title"] for source in result["sources"]] == ["공지 0", "공지 2"]
    assert "공지 3 근거" not in parse.call_args.kwargs["input"][0]["content"]
    assert parse.call_args.kwargs["text_format"] is RAGAnswer
    assert parse.call_args.kwargs["store"] is False


def test_rag_returns_no_sources_when_evidence_does_not_support_answer(tmp_path):
    repository = NoticeRepository(tmp_path / "notices.db")
    notice_id = _save(repository, "one", _notice("Procurement 경력사원 채용"))
    repository.save_embedding_chunks(
        notice_id=notice_id,
        provider="fake",
        model="fake-model",
        chunks=[EmbeddingChunk("structured", 0, "지원 자격: 3년 이상 경력")],
        vectors=[[1.0, 0.0]],
    )
    provider = SimpleNamespace(provider="fake", model="fake-model")
    provider.embed = AsyncMock(return_value=[[1.0, 0.0]])
    parse = AsyncMock(
        return_value=SimpleNamespace(
            status="completed",
            output_parsed=RAGAnswer(
                supported=False,
                answer="요구되는 자격증은 확인할 수 없습니다.",
                source_notice_ids=[notice_id],
            ),
        )
    )
    service = NoticeRAGService(
        embedding_provider=provider,
        repository=repository,
        answer_client=SimpleNamespace(responses=SimpleNamespace(parse=parse)),
        answer_model="fake-answer-model",
    )

    result = asyncio.run(service.search("항공회사 지원에 필요한 자격증은 뭐야?"))

    assert result == {"message": NO_SUPPORTED_ANSWER, "sources": []}
