from __future__ import annotations

import base64
import re

MAX_OCR_IMAGE_BYTES = 10 * 1024 * 1024

_DATA_URL_PREFIX_RE = re.compile(r"^data:[^,]*,", re.IGNORECASE)


def normalize_base64_image_payload(image_base64: str) -> str:
    return _DATA_URL_PREFIX_RE.sub("", image_base64.strip())


def estimate_base64_decoded_bytes(image_base64: str) -> int:
    payload = normalize_base64_image_payload(image_base64)
    if not payload:
        return 0
    padding = payload.count("=")
    return max(0, (len(payload) * 3 // 4) - padding)


def decode_base64_image_payload(image_base64: str) -> bytes:
    return base64.b64decode(normalize_base64_image_payload(image_base64), validate=False)
