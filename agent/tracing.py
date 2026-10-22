"""LangSmith에 본문을 제외한 실행 메타데이터만 기록한다."""

from __future__ import annotations

from typing import Any

from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree


def record_trace_metadata(**values: Any) -> None:
    """현재 단계에 허용된 비본문 값만 추가한다."""
    run = get_current_run_tree()
    if run is None:
        return
    allowed = {
        "route", "search_mode", "search_type", "period", "status",
        "model", "provider", "prompt_tokens", "completion_tokens",
        "total_tokens", "elapsed_seconds", "attempts", "chunk_count",
        "result_count", "event_count", "created", "validation_status",
        "embedding_status", "segment_count", "source_count",
    }
    metadata = {key: value for key, value in values.items() if key in allowed and value is not None}
    if metadata:
        run.add_metadata(metadata)


__all__ = ["traceable", "record_trace_metadata"]
