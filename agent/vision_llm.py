"""Ollama qwen3-vl을 이용한 공지 이미지 분할 OCR."""

from __future__ import annotations

import base64
import io
import math
import os
import time
from pathlib import Path

import httpx
from PIL import Image, ImageOps

try:
    from langsmith import traceable
except ImportError:  # pragma: no cover
    def traceable(*args, **kwargs):
        def _decorator(fn):
            return fn

        return _decorator


OLLAMA_CHAT_URL = "http://127.0.0.1:11434/api/chat"
DEFAULT_MAX_DIM = int(os.environ.get("OLLAMA_VISION_MAX_DIM", "2560"))
DEFAULT_MAX_PIXELS = int(os.environ.get("OLLAMA_VISION_MAX_PIXELS", "2200000"))
SEGMENT_COUNT = 3
SEGMENT_OVERLAP_RATIO = 0.15
MAX_ATTEMPTS = 2


class OCRError(RuntimeError):
    """이미지 OCR 단계가 완료되지 못한 경우."""


def _to_rgb(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA") or (
        img.mode == "P" and "transparency" in img.info
    ):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[3])
        return background
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def _encode_png(img: Image.Image) -> str:
    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _segment_bounds(
    height: int,
    *,
    count: int = SEGMENT_COUNT,
    overlap_ratio: float = SEGMENT_OVERLAP_RATIO,
) -> list[tuple[int, int]]:
    """전체 높이를 덮는 고정 개수의 중첩 구간을 계산한다."""
    if count <= 1:
        return [(0, height)]
    segment_height = min(
        height,
        math.ceil(height / (count - (count - 1) * overlap_ratio)),
    )
    max_start = height - segment_height
    return [
        (round(max_start * index / (count - 1)), round(max_start * index / (count - 1)) + segment_height)
        for index in range(count)
    ]


def prepare_image_segments(
    image_path: Path,
    *,
    count: int = SEGMENT_COUNT,
    overlap_ratio: float = SEGMENT_OVERLAP_RATIO,
) -> tuple[list[tuple[str, dict]], dict]:
    """원본 해상도를 유지한 RGB 이미지의 세로 중첩 구간을 만든다."""
    with Image.open(image_path) as raw_img:
        img = _to_rgb(ImageOps.exif_transpose(raw_img))
        original_size = img.size
        bounds = _segment_bounds(img.height, count=count, overlap_ratio=overlap_ratio)
        segments = []
        for index, (top, bottom) in enumerate(bounds):
            crop = img.crop((0, top, img.width, bottom))
            segments.append(
                (
                    _encode_png(crop),
                    {
                        "index": index,
                        "crop_box": [0, top, img.width, bottom],
                        "size": list(crop.size),
                    },
                )
            )
        return segments, {
            "original_size": list(original_size),
            "original_mode": raw_img.mode,
            "processed_size": list(original_size),
            "resized": False,
            "segment_count": len(segments),
            "overlap_ratio": overlap_ratio,
        }


def prepare_image_b64(
    image_path: Path,
    *,
    max_dim: int = DEFAULT_MAX_DIM,
    max_pixels: int = DEFAULT_MAX_PIXELS,
) -> tuple[str, dict]:
    """진단 스크립트 호환용: 원본 크기의 전체 이미지를 인코딩한다."""
    del max_dim, max_pixels
    with Image.open(image_path) as raw_img:
        img = _to_rgb(ImageOps.exif_transpose(raw_img))
        return _encode_png(img), {
            "original_size": list(img.size),
            "original_mode": raw_img.mode,
            "processed_size": list(img.size),
            "resized": False,
        }


def _normalize_line(line: str) -> str:
    return "".join(line.split()).casefold()


def truncate_repeated_tail(
    text: str, *, repetition_threshold: int = 3
) -> tuple[str, dict]:
    """동일 문장이 연속 반복되면 반복 시작 지점부터 생성 꼬리를 제거한다."""
    lines = text.splitlines()
    run_start = 0
    previous = ""
    run_length = 0
    for index, line in enumerate(lines):
        normalized = _normalize_line(line)
        if not normalized:
            previous = ""
            run_length = 0
            continue
        if normalized == previous:
            run_length += 1
        else:
            previous = normalized
            run_start = index
            run_length = 1
        if run_length >= repetition_threshold:
            kept = "\n".join(lines[:run_start]).strip()
            return kept, {
                "repetition_truncated": True,
                "truncated_line_count": len(lines) - run_start,
                "repeated_line": lines[run_start].strip(),
            }
    return text.strip(), {
        "repetition_truncated": False,
        "truncated_line_count": 0,
        "repeated_line": None,
    }


def merge_ocr_texts(texts: list[str]) -> str:
    """인접 OCR 결과의 동일한 경계 문장을 제거하면서 순서대로 합친다."""
    merged: list[str] = []
    for text in texts:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            continue
        normalized_merged = [_normalize_line(line) for line in merged]
        normalized_lines = [_normalize_line(line) for line in lines]
        overlap = 0
        for size in range(min(len(merged), len(lines)), 0, -1):
            if normalized_merged[-size:] == normalized_lines[:size]:
                overlap = size
                break
        merged.extend(lines[overlap:])
    return "\n".join(merged)


def _extract_ollama_error(response: httpx.Response) -> str:
    try:
        data = response.json()
        if isinstance(data, dict) and data.get("error"):
            return str(data["error"])
    except Exception:
        pass
    return response.text.strip() or f"HTTP {response.status_code}"


class OllamaVisionLLM:
    def __init__(
        self,
        model: str = "qwen3-vl:4b-instruct",
        timeout_sec: float = 300.0,
        num_ctx: int = 8192,
        max_dim: int = DEFAULT_MAX_DIM,
        max_pixels: int = DEFAULT_MAX_PIXELS,
    ):
        self.model = model
        self.timeout_sec = timeout_sec
        self.num_ctx = num_ctx
        self.max_dim = max_dim
        self.max_pixels = max_pixels
        self.name = f"ollama:{model}"

    @traceable(run_type="llm", name="notice_ocr.extract_text")
    async def extract_text(self, image_path: Path) -> tuple[str, dict]:
        segments, image_meta = prepare_image_segments(image_path)
        started = time.perf_counter()
        prompt_tokens = 0
        completion_tokens = 0
        segment_texts: list[str] = []
        segment_usages: list[dict] = []

        async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
            for segment_b64, segment_meta in segments:
                text, usage = await self._extract_segment(
                    client,
                    segment_b64,
                    segment_meta,
                    len(segments),
                )
                segment_texts.append(text)
                segment_usages.append(usage)
                prompt_tokens += usage["prompt_tokens"]
                completion_tokens += usage["completion_tokens"]

        merged_text = merge_ocr_texts(segment_texts)
        if not merged_text:
            raise OCRError("모든 이미지 구간에서 빈 OCR 텍스트가 반환되었습니다.")
        return merged_text, {
            "model": self.model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "attempts": sum(item["attempts"] for item in segment_usages),
            "image": image_meta,
            "segments": segment_usages,
            "repetition_truncated": any(
                item["repetition_truncated"] for item in segment_usages
            ),
            "truncated_line_count": sum(
                item["truncated_line_count"] for item in segment_usages
            ),
        }

    @traceable(run_type="llm", name="notice_ocr.extract_segment")
    async def _extract_segment(
        self,
        client: httpx.AsyncClient,
        image_b64: str,
        segment_meta: dict,
        segment_count: int,
    ) -> tuple[str, dict]:
        segment_number = segment_meta["index"] + 1
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"이 이미지는 긴 한국어 공지의 {segment_number}/{segment_count} 구간이다. "
                        "보이는 모든 텍스트를 위에서 아래 순서로 빠짐없이 옮겨 적어라. "
                        "표에서는 모집분야, 수행업무, 우대사항과 모든 항목을 보존하라. "
                        "날짜, 시간, 장소, 연락처와 구두점을 원문대로 유지하고 설명이나 "
                        "JSON, 마크다운을 추가하지 마라. 더 읽을 내용이 없으면 즉시 "
                        "응답을 끝내고 같은 단어나 문장을 반복하지 마라."
                    ),
                    "images": [image_b64],
                }
            ],
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.0,
                "num_predict": 4096,
                "num_ctx": self.num_ctx,
            },
            "keep_alive": "10m",
        }
        started = time.perf_counter()
        prompt_tokens = 0
        completion_tokens = 0
        last_error: Exception | None = None
        attempts_used = 0

        for attempt in range(MAX_ATTEMPTS):
            attempts_used = attempt + 1
            if attempt:
                payload["options"].update({"temperature": 0.2, "seed": 7})
            try:
                response = await client.post(OLLAMA_CHAT_URL, json=payload)
                if response.status_code >= 400:
                    raise httpx.HTTPStatusError(
                        f"Ollama 오류 ({response.status_code}): "
                        f"{_extract_ollama_error(response)}",
                        request=response.request,
                        response=response,
                    )
                body = response.json()
                prompt_tokens += int(body.get("prompt_eval_count", 0))
                completion_tokens += int(body.get("eval_count", 0))
                text = str(body.get("message", {}).get("content", "")).strip()
                if not text:
                    raise ValueError("Ollama가 빈 OCR 텍스트를 반환했습니다.")
                text, repetition = truncate_repeated_tail(text)
                if not text:
                    raise ValueError("반복 생성을 제거한 뒤 OCR 텍스트가 비었습니다.")
                return text, {
                    **segment_meta,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                    "attempts": attempts_used,
                    **repetition,
                }
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc

        raise OCRError(
            f"OCR {segment_number}/{segment_count} 구간을 {MAX_ATTEMPTS}회 시도 후 "
            f"완료하지 못했습니다: {last_error}"
        ) from last_error
