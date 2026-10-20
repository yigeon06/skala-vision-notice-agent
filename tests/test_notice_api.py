from __future__ import annotations

import io
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image

import server
from agent.schemas import NoticeExtraction


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (120, 80), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_upload_register_list_and_detail(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(server, "PROJECT_ROOT", tmp_path)
    extraction = NoticeExtraction.model_validate({
        "title": "테스트 공지",
        "target": ["전 임직원"],
        "action_required": ["신청"],
        "application_method": "사내 포털",
        "raw_text": "신청 마감: 2026년 10월 25일",
        "cleaned_text": "신청 마감: 2026년 10월 25일",
        "recruitment_positions": [],
        "additional_information": [{
            "category": "notice",
            "title": "기타 유의사항",
            "items": ["우승 3,000,000원"],
            "evidence_text": "상금안내 우승 3,000,000원",
            "confidence": 0.96,
            "needs_review": False,
        }],
        "events": [{
            "event_type": "application_deadline",
            "date_text": "2026년 10월 25일",
            "start_at": "2026-10-25T00:00:00+09:00",
            "end_at": None,
            "all_day": True,
            "location": None,
            "evidence_text": "신청 마감: 2026년 10월 25일",
            "confidence": 0.99,
        }],
        "confidence": 0.99,
    })

    class FakeExtractor:
        vision_llm = SimpleNamespace(model="fake-vision", num_ctx=1)
        structured_llm = SimpleNamespace(model="fake-structured")

        async def extract_notice(self, image_path, reference_date):
            raise AssertionError("저장 중 모델 추출이 다시 실행되면 안 됩니다.")

    monkeypatch.setattr(server, "NoticeExtractor", lambda *_: FakeExtractor())
    monkeypatch.setattr(server, "OpenAIStructuredLLM", lambda **_: object())
    with TestClient(server.app) as client:
        upload = client.post(
            "/images",
            files={"file": ("notice.png", _png_bytes(), "image/png")},
        )
        assert upload.status_code == 200

        registered = client.post(
            "/notices/register",
            json={
                "image_id": upload.json()["image_id"],
                "request_id": "frontend-test-1",
                "reference_date": "2026-10-20",
                "extraction": extraction.model_dump(mode="json"),
            },
        )
        assert registered.status_code == 200
        assert registered.json()["created"] is True
        assert registered.json()["usage"]["source"] == "provided_extraction"

        listing = client.get("/notices")
        assert listing.status_code == 200
        assert listing.json()["items"][0]["event_count"] == 1

        detail = client.get(f"/notices/{registered.json()['notice_id']}")
        assert detail.status_code == 200
        assert detail.json()["title"] == "테스트 공지"
        assert len(detail.json()["events"]) == 1
        assert detail.json()["additional_information"] == [
            {
                "category": "notice",
                "title": "기타 유의사항",
                "items": ["우승 3,000,000원"],
                "evidence_text": "상금안내 우승 3,000,000원",
                "confidence": 0.96,
                "needs_review": False,
            }
        ]

        preflight = client.options(
            "/notices",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
