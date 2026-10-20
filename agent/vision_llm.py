"""Ollama qwen3-vl을 이용한 공지 이미지 OCR."""
from __future__ import annotations
import base64, io, math, os, time
from pathlib import Path
import httpx
from PIL import Image, ImageOps
try:
    from langsmith import traceable
except ImportError:  # pragma: no cover
    def traceable(*args, **kwargs):
        def _decorator(fn): return fn
        return _decorator

OLLAMA_CHAT_URL = "http://127.0.0.1:11434/api/chat"
DEFAULT_MAX_DIM = int(os.environ.get("OLLAMA_VISION_MAX_DIM", "2560"))
DEFAULT_MAX_PIXELS = int(os.environ.get("OLLAMA_VISION_MAX_PIXELS", "2200000"))
MAX_ATTEMPTS = 2

class OCRError(RuntimeError):
    """이미지 OCR 단계가 완료되지 못한 경우."""

def prepare_image_b64(image_path: Path, *, max_dim: int = DEFAULT_MAX_DIM, max_pixels: int = DEFAULT_MAX_PIXELS) -> tuple[str, dict]:
    """이미지를 RGB로 정규화하고 크기를 조정한 뒤 Base64로 인코딩한다."""
    with Image.open(image_path) as raw_img:
        img = ImageOps.exif_transpose(raw_img)
        orig_size, orig_mode = img.size, img.mode
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.split()[3]); img = background
        elif img.mode != "RGB": img = img.convert("RGB")
        width, height = img.size
        scale = min(1.0, max_dim / max(width, height))
        if (width * scale) * (height * scale) > max_pixels:
            scale = min(scale, math.sqrt(max_pixels / (width * height)))
        if scale < 1.0:
            img = img.resize((max(32, int(round(width * scale / 32) * 32)), max(32, int(round(height * scale / 32) * 32))), Image.Resampling.LANCZOS)
        buffer = io.BytesIO(); img.save(buffer, format="PNG", optimize=True)
        return base64.b64encode(buffer.getvalue()).decode("ascii"), {"original_size": list(orig_size), "original_mode": orig_mode, "processed_size": list(img.size)}

def _extract_ollama_error(response: httpx.Response) -> str:
    try:
        data = response.json()
        if isinstance(data, dict) and data.get("error"): return str(data["error"])
    except Exception: pass
    return response.text.strip() or f"HTTP {response.status_code}"

class OllamaVisionLLM:
    def __init__(self, model: str = "qwen3-vl:4b-instruct", timeout_sec: float = 300.0, num_ctx: int = 8192, max_dim: int = DEFAULT_MAX_DIM, max_pixels: int = DEFAULT_MAX_PIXELS):
        self.model, self.timeout_sec, self.num_ctx = model, timeout_sec, num_ctx
        self.max_dim, self.max_pixels, self.name = max_dim, max_pixels, f"ollama:{model}"

    @traceable(run_type="llm", name="notice_ocr.extract_text")
    async def extract_text(self, image_path: Path) -> tuple[str, dict]:
        image_b64, image_meta = prepare_image_b64(image_path, max_dim=self.max_dim, max_pixels=self.max_pixels)
        payload = {"model": self.model, "messages": [{"role": "user", "content": "이 한국어 공지 이미지에 실제로 보이는 모든 텍스트를 위에서 아래 순서로 빠짐없이 옮겨 적어라. 날짜, 시간, 장소, 연락처와 구두점을 원문대로 보존하고 설명이나 JSON, 마크다운을 추가하지 마라.", "images": [image_b64]}], "stream": False, "think": False, "options": {"temperature": 0.0, "num_predict": 4096, "num_ctx": self.num_ctx}, "keep_alive": "10m"}
        started = time.perf_counter(); prompt_tokens = completion_tokens = 0
        last_error = None; body = {}; text = ""; attempts_used = 0
        async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
            for attempt in range(MAX_ATTEMPTS):
                attempts_used = attempt + 1
                if attempt: payload["options"].update({"temperature": 0.2, "seed": 7})
                try:
                    response = await client.post(OLLAMA_CHAT_URL, json=payload)
                    if response.status_code >= 400:
                        raise httpx.HTTPStatusError(f"Ollama 오류 ({response.status_code}): {_extract_ollama_error(response)}", request=response.request, response=response)
                    body = response.json(); prompt_tokens += int(body.get("prompt_eval_count", 0)); completion_tokens += int(body.get("eval_count", 0))
                    text = str(body.get("message", {}).get("content", "")).strip()
                    if not text: raise ValueError("Ollama가 빈 OCR 텍스트를 반환했습니다.")
                    break
                except (httpx.HTTPError, ValueError) as exc: last_error = exc
        if not text: raise OCRError(f"OCR을 {MAX_ATTEMPTS}회 시도 후 완료하지 못했습니다: {last_error}") from last_error
        return text, {"model": body.get("model", self.model), "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "elapsed_seconds": round(time.perf_counter() - started, 3), "attempts": attempts_used, "image": image_meta}
