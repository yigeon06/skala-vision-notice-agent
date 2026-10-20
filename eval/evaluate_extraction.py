"""샘플 공지 이미지의 Vision 구조화 추출 정확도를 측정한다."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import date
from pathlib import Path

from agent.notice_extractor import NoticeExtractor
from agent.structured_llm import OpenAIStructuredLLM
from agent.vision_llm import OllamaVisionLLM
from notice.date_normalizer import normalize_extraction
from notice.service import validate_extraction


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "data" / "samples"
RESULTS = ROOT / "eval" / "results"


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", "", value)


async def main() -> None:
    model = NoticeExtractor(OllamaVisionLLM(), OpenAIStructuredLLM())
    rows = []
    for expected_path in sorted(SAMPLES.glob("*.expected.json")):
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        image_path = expected_path.with_name(expected_path.name.replace(".expected.json", ".png"))
        try:
            extraction, usage = await model.extract_notice(image_path, date(2026, 10, 20))
        except Exception as exc:
            rows.append(
                {
                    "sample": image_path.name,
                    "title_ok": False,
                    "event_type_recall": 0.0,
                    "date_recall": 0.0,
                    "status_ok": False,
                    "validation": None,
                    "usage": {"elapsed_seconds": 0.0},
                    "extraction": None,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            print(f"{image_path.name}: ERROR {type(exc).__name__}: {exc}")
            continue
        extraction = normalize_extraction(extraction, date(2026, 10, 20))
        validation = validate_extraction(extraction)
        actual_types = [event.event_type for event in extraction.events]
        evidence = " ".join(
            f"{event.date_text} {event.evidence_text}" for event in extraction.events
        )
        title_ok = _normalized_text(extraction.title) == _normalized_text(expected["title"])
        type_hits = sum(1 for value in expected["event_types"] if value in actual_types)
        date_hits = sum(1 for value in expected["date_fragments"] if value in evidence)
        status_ok = validation.status == expected["expected_status"]
        row = {
            "sample": image_path.name,
            "title_ok": title_ok,
            "event_type_recall": type_hits / len(expected["event_types"]),
            "date_recall": date_hits / len(expected["date_fragments"]),
            "status_ok": status_ok,
            "validation": validation.model_dump(mode="json"),
            "usage": usage,
            "extraction": extraction.model_dump(mode="json"),
        }
        rows.append(row)
        print(
            f"{image_path.name}: title={title_ok} "
            f"types={row['event_type_recall']:.2f} dates={row['date_recall']:.2f} "
            f"status={status_ok} latency={usage['elapsed_seconds']}s"
        )
    successful_latencies = [
        row["usage"]["elapsed_seconds"]
        for row in rows
        if row["extraction"] is not None
    ]
    summary = {
        "models": {
            "vision": model.vision_llm.model,
            "structured": model.structured_llm.model,
        },
        "sample_count": len(rows),
        "failure_count": sum(row["extraction"] is None for row in rows),
        "retry_count": sum(
            max(int(row["usage"].get("attempts", 1)) - 1, 0)
            for row in rows
            if row["extraction"] is not None
        ),
        "title_accuracy": sum(row["title_ok"] for row in rows) / len(rows),
        "event_type_recall": sum(row["event_type_recall"] for row in rows) / len(rows),
        "date_recall": sum(row["date_recall"] for row in rows) / len(rows),
        "status_accuracy": sum(row["status_ok"] for row in rows) / len(rows),
        "average_latency_seconds": (
            sum(successful_latencies) / len(successful_latencies)
            if successful_latencies
            else 0.0
        ),
        "rows": rows,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    output = RESULTS / "day1_vision.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "rows"}, ensure_ascii=False, indent=2))
    print(f"saved: {output}")


if __name__ == "__main__":
    asyncio.run(main())

