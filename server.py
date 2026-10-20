"""Vision 기반 사내 공지·일정 관리 API."""

from __future__ import annotations

import hashlib
import os
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent.notice_extractor import NoticeExtractor
from agent.schemas import NoticeExtraction
from agent.structured_llm import OpenAIStructuredLLM, StructuredOutputError
from agent.vision_llm import OCRError, OllamaVisionLLM
from notice.date_normalizer import normalize_extraction
from notice.image_store import ImageStore
from notice.repository import NoticeRepository
from notice.service import validate_extraction


PROJECT_ROOT = Path(__file__).resolve().parent
SEOUL = ZoneInfo("Asia/Seoul")


class ExtractNoticeRequest(BaseModel):
    image_id: str
    reference_date: date | None = None


class RegisterNoticeRequest(ExtractNoticeRequest):
    request_id: str
    extraction: NoticeExtraction


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


async def _extract_notice(image_id: str, reference_date: date | None):
    try:
        image_path = app.state.image_store.resolve(image_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="업로드 이미지를 찾을 수 없습니다.") from exc

    effective_date = reference_date or datetime.now(SEOUL).date()
    try:
        extraction, usage = await app.state.notice_extractor.extract_notice(
            image_path, effective_date
        )
    except OCRError as exc:
        raise HTTPException(status_code=502, detail=f"OCR 실패: {exc}") from exc
    except StructuredOutputError as exc:
        raise HTTPException(status_code=502, detail=f"JSON 구조화 실패: {exc}") from exc

    normalized = normalize_extraction(extraction, effective_date)
    validation = validate_extraction(normalized)
    return image_path, normalized, validation, usage


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "vision_model": app.state.notice_extractor.vision_llm.model,
        "vision_num_ctx": app.state.notice_extractor.vision_llm.num_ctx,
        "openai_text_model": app.state.notice_extractor.structured_llm.model,
    }


@app.post("/images")
async def upload_image(file: UploadFile = File(...)):
    data = await file.read(10 * 1024 * 1024 + 1)
    try:
        stored = app.state.image_store.save(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**stored, "original_filename": file.filename}


@app.post("/notices/extract")
async def extract_notice(req: ExtractNoticeRequest):
    _, extraction, validation, usage = await _extract_notice(
        req.image_id, req.reference_date
    )
    return {
        "extraction": extraction.model_dump(mode="json"),
        "validation": validation.model_dump(mode="json"),
        "usage": usage,
    }


@app.post("/notices/register")
async def register_notice(req: RegisterNoticeRequest):
    try:
        image_path = app.state.image_store.resolve(req.image_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="업로드 이미지를 찾을 수 없습니다.") from exc

    extraction = req.extraction
    validation = validate_extraction(extraction)
    notice_id, created = app.state.notice_repository.save_notice(
        request_id=req.request_id,
        extraction=extraction,
        source_image_path=str(image_path),
        source_image_hash=_image_sha256(image_path),
        status=validation.status,
    )
    return {
        "notice_id": notice_id,
        "created": created,
        "status": validation.status,
        "issues": validation.issues,
        "extraction": extraction.model_dump(mode="json"),
        "usage": {
            "models": {},
            "elapsed_seconds": 0,
            "source": "provided_extraction",
        },
    }


@app.get("/notices")
async def list_notices():
    return {"items": app.state.notice_repository.list_notices()}


@app.get("/notices/{notice_id}")
async def get_notice(notice_id: int):
    notice = app.state.notice_repository.get_notice(notice_id)
    if notice is None:
        raise HTTPException(status_code=404, detail="공지를 찾을 수 없습니다.")
    return notice


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8100, log_level="info")
