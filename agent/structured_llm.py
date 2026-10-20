"""OpenAI Structured Outputs를 이용한 OCR 텍스트 구조화."""
from __future__ import annotations
import time
from datetime import date
from openai import APIConnectionError, APIError, APITimeoutError, AsyncOpenAI, RateLimitError
from pydantic import ValidationError
try:
    from langsmith import traceable
except ImportError:  # pragma: no cover
    def traceable(*args, **kwargs):
        def _decorator(fn): return fn
        return _decorator
from .schemas import NoticeExtraction

class StructuredOutputError(RuntimeError):
    """OpenAI 구조화 단계가 완료되지 못한 경우."""

class OpenAIStructuredLLM:
    def __init__(self, model: str = "gpt-4o-mini", timeout_sec: float = 60.0, max_retries: int = 2, client: AsyncOpenAI | None = None):
        self.model, self.timeout_sec, self.max_retries = model, timeout_sec, max_retries
        self.name = f"openai:{model}"
        self.client = client or AsyncOpenAI(timeout=timeout_sec, max_retries=max_retries)

    @traceable(run_type="llm", name="notice_structure.extract_notice")
    async def extract_notice(self, ocr_text: str, reference_date: date) -> tuple[NoticeExtraction, dict]:
        started = time.perf_counter()
        try:
            response = await self.client.responses.parse(model=self.model, input=[
                {"role": "system", "content": "당신은 한국어 사내 공지 추출기다. 제공된 OCR 원문만 사용한다. 보이지 않는 값은 빈 문자열, 빈 배열 또는 null로 둔다. 신청 마감과 행사 일시는 별도 event로 만든다. 신청·예약 마감은 application_deadline, 자료·비용 제출 마감은 submission_deadline이다. 날짜가 모호해도 event를 만들고 start_at은 null로 둔다. 확정 가능한 시각만 Asia/Seoul ISO 8601로 표현하며 근거 문장을 보존한다."},
                {"role": "user", "content": f"기준 날짜: {reference_date.isoformat()}\n\nOCR 원문:\n{ocr_text}\n\n제목, 대상, 해야 할 일, 신청 방법, 전체 원문과 모든 일정을 추출하라. 연도가 생략된 날짜는 기준 날짜의 연도로 해석하라."},
            ], text_format=NoticeExtraction)
        except RateLimitError as exc: raise StructuredOutputError("OpenAI API 요청 한도에 도달했습니다.") from exc
        except APITimeoutError as exc: raise StructuredOutputError("OpenAI API 요청 시간이 초과되었습니다.") from exc
        except APIConnectionError as exc: raise StructuredOutputError("OpenAI API에 연결하지 못했습니다.") from exc
        except APIError as exc: raise StructuredOutputError(f"OpenAI API 오류: {exc}") from exc
        except ValidationError as exc: raise StructuredOutputError(f"구조화 응답 스키마 검증 실패: {exc}") from exc
        extraction = response.output_parsed
        if extraction is None:
            refusal = next((item.refusal for output in response.output for item in getattr(output, "content", []) if getattr(item, "type", None) == "refusal"), None)
            if refusal: raise StructuredOutputError(f"OpenAI가 구조화 요청을 거부했습니다: {refusal}")
            raise StructuredOutputError(f"OpenAI 구조화 응답이 불완전합니다: status={response.status!r}")
        usage = response.usage
        return extraction, {"model": self.model, "prompt_tokens": int(getattr(usage, "input_tokens", 0) or 0), "completion_tokens": int(getattr(usage, "output_tokens", 0) or 0), "total_tokens": int(getattr(usage, "total_tokens", 0) or 0), "elapsed_seconds": round(time.perf_counter() - started, 3)}
