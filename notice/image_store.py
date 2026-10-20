"""업로드 이미지 검증 및 로컬 저장."""

from __future__ import annotations

import hashlib
import io
import uuid
from pathlib import Path

from PIL import Image


ALLOWED_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}


class ImageStore:
    def __init__(self, root: Path, max_bytes: int = 10 * 1024 * 1024):
        self.root = root
        self.max_bytes = max_bytes
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, data: bytes) -> dict:
        if not data:
            raise ValueError("빈 이미지입니다.")
        if len(data) > self.max_bytes:
            raise ValueError("이미지는 10MB 이하여야 합니다.")
        try:
            with Image.open(io.BytesIO(data)) as image:
                image.verify()
                image_format = image.format
        except Exception as exc:
            raise ValueError("JPEG, PNG 또는 WEBP 이미지가 아닙니다.") from exc
        if image_format not in ALLOWED_FORMATS:
            raise ValueError("지원하지 않는 이미지 형식입니다.")
        image_id = str(uuid.uuid4())
        suffix = ALLOWED_FORMATS[image_format]
        path = self.root / f"{image_id}{suffix}"
        path.write_bytes(data)
        return {
            "image_id": image_id,
            "path": str(path),
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
            "format": image_format.lower(),
        }

    def resolve(self, image_id: str) -> Path:
        try:
            normalized = str(uuid.UUID(image_id))
        except ValueError as exc:
            raise FileNotFoundError(image_id) from exc
        matches = list(self.root.glob(f"{normalized}.*"))
        if len(matches) != 1:
            raise FileNotFoundError(image_id)
        return matches[0]

