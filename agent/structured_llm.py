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
from .schemas import StructuredNoticeExtraction

class StructuredOutputError(RuntimeError):
    """OpenAI 구조화 단계가 완료되지 못한 경우."""

class OpenAIStructuredLLM:
    def __init__(self, model: str = "gpt-4o-mini", timeout_sec: float = 60.0, max_retries: int = 2, client: AsyncOpenAI | None = None):
        self.model, self.timeout_sec, self.max_retries = model, timeout_sec, max_retries
        self.name = f"openai:{model}"
        self.client = client or AsyncOpenAI(timeout=timeout_sec, max_retries=max_retries)

    @traceable(run_type="llm", name="notice_structure.extract_notice")
    async def extract_notice(self, ocr_text: str, reference_date: date) -> tuple[StructuredNoticeExtraction, dict]:
        started = time.perf_counter()
        try:
            response = await self.client.responses.parse(model=self.model, input=[
                {"role": "system", "content": "당신은 한국어 사내 공지 추출기다. 제공된 OCR 원문만 사용한다. 중첩 구간에서 반복된 문장과 메뉴·푸터 같은 웹페이지 장식을 제거하고, 문맥상 명백한 OCR 오탈자만 바로잡아 cleaned_text를 작성한다. 불확실한 글자는 추측하지 말고 OCR 표현을 유지한다. 채용 공지라면 모집분야별 수행업무와 우대사항을 빠짐없이 분리한다. action_required에는 '지원하기', '신청하기', '제출하기'처럼 원문에 명시된 행동만 복사하고 기간이나 목적을 덧붙이지 않는다. 보이지 않는 값은 빈 문자열, 빈 배열 또는 null로 둔다. 신청·지원·모집 기간은 하나의 application_deadline event로 만들고 시작일과 종료일을 각각 start_at과 end_at으로 둔다. 서류전형, 면접, 합격발표처럼 날짜가 명시되지 않은 채용절차 단계는 event로 만들지 않는다. 신청 마감과 행사 일시는 별도 event로 만든다. 자료·비용 제출 마감은 submission_deadline이다. 날짜가 모호하게라도 명시된 경우에만 event를 만들며, 확정 가능한 시각만 Asia/Seoul ISO 8601로 표현하고 근거 문장을 보존한다."},
                {"role": "user", "content": f"기준 날짜: {reference_date.isoformat()}\n\nOCR 원문:\n{ocr_text}\n\n제목, 대상, 해야 할 일, 신청 방법, 정리된 전체 공지문, 모집분야별 수행업무·우대사항과 모든 일정을 추출하라. 연도가 생략된 날짜는 기준 날짜의 연도로 해석하라."},
            ], text_format=StructuredNoticeExtraction)
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
