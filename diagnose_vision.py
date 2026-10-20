"""Ollama 500 원인 분리용 진단 스크립트.

프로젝트 루트(`agent` 패키지를 import 할 수 있는 위치)에서 실행한다.

    python diagnose_vision.py 잘되는이미지.png 실패하는이미지.png
    python diagnose_vision.py 실패하는이미지.png --model qwen3-vl:4b-instruct

각 이미지를 '해상도 3단계 × 구조화 출력(format) 유무'로 호출해
어떤 조건에서 500이 나는지, Ollama가 돌려준 실제 오류 문구가 무엇인지 출력한다.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import httpx
from PIL import Image

from agent.schemas import NoticeExtraction
from agent.vision_llm import (
    DEFAULT_MAX_DIM,
    DEFAULT_MAX_PIXELS,
    OLLAMA_CHAT_URL,
    prepare_image_b64,
)

PROMPT = "이 이미지에 보이는 제목과 날짜를 알려줘."

LEVELS = [
    ("현재 기본값", DEFAULT_MAX_DIM, DEFAULT_MAX_PIXELS),
    ("폴백 수준", 1600, 1_200_000),
    ("작게", 1024, 500_000),
]


def call_ollama(model: str, image_b64: str, *, use_format: bool, num_ctx: int) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT, "images": [image_b64]}],
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0.0,
            "num_predict": 1024 if use_format else 64,
            "num_ctx": num_ctx,
        },
        "keep_alive": "10m",
    }
    if use_format:
        payload["format"] = NoticeExtraction.model_json_schema()

    started = time.perf_counter()
    try:
        response = httpx.post(OLLAMA_CHAT_URL, json=payload, timeout=300.0)
    except httpx.HTTPError as exc:
        return f"요청 실패: {exc!r}"
    elapsed = time.perf_counter() - started

    if response.status_code >= 400:
        detail = response.text.strip().replace("\n", " ")[:400]
        return f"HTTP {response.status_code} ({elapsed:.1f}s) → {detail}"

    body = response.json()
    return (
        f"OK ({elapsed:.1f}s) "
        f"prompt_tokens={body.get('prompt_eval_count')} "
        f"done_reason={body.get('done_reason')}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--model", default="qwen3-vl:4b-instruct")
    parser.add_argument("--num-ctx", type=int, default=8192)
    args = parser.parse_args()

    for path in args.images:
        print(f"\n=== {path.name} ===")
        try:
            with Image.open(path) as img:
                print(
                    f"원본: format={img.format} size={img.size} "
                    f"mode={img.mode} bytes={path.stat().st_size:,}"
                )
        except Exception as exc:
            print(f"이미지를 열 수 없음: {exc!r}")
            continue

        for label, max_dim, max_pixels in LEVELS:
            try:
                image_b64, meta = prepare_image_b64(
                    path, max_dim=max_dim, max_pixels=max_pixels
                )
            except Exception as exc:
                print(f"- {label}: 전처리 실패 {exc!r}")
                continue
            print(
                f"- {label}: 처리 크기 {meta['processed_size']} "
                f"(base64 {len(image_b64) // 1024:,}KB)"
            )
            for use_format in (False, True):
                result = call_ollama(
                    args.model, image_b64, use_format=use_format, num_ctx=args.num_ctx
                )
                print(f"    format={'on ' if use_format else 'off'} → {result}")


if __name__ == "__main__":
    main()
