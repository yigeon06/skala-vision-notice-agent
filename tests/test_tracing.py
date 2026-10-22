"""LangSmith 메타데이터에 공고·대화 본문이 들어가지 않는지 확인한다."""

from agent import tracing


def test_trace_metadata_allows_only_execution_fields(monkeypatch):
    captured = []

    class FakeRun:
        def add_metadata(self, metadata):
            captured.append(metadata)

    monkeypatch.setattr(tracing, "get_current_run_tree", lambda: FakeRun())
    tracing.record_trace_metadata(
        model="gpt-4o-mini",
        prompt_tokens=42,
        route="notice_search",
        question="내 이름과 지원 자격을 알려줘",
        raw_text="공지 원문",
        image_b64="secret-image",
        answer="개인 답변",
    )
    assert captured == [{
        "model": "gpt-4o-mini",
        "prompt_tokens": 42,
        "route": "notice_search",
    }]
