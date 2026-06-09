"""
Tests for honest image-metadata verification (Phase 4 verification).

Generates real images (with and without EXIF) and asserts the extractor reports
what is actually present -- and that it makes NO manipulation/authenticity claim.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from src.api.main import app
from src.verification.metadata import ImageError, extract_image_metadata


def _png_bytes(size=(8, 8), color=(255, 0, 0)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_with_software_tag():
    buf = io.BytesIO()
    img = Image.new("RGB", (10, 10), (0, 128, 255))
    exif = img.getexif()
    exif[0x0131] = "Adobe Photoshop 25.0"  # Software tag
    exif[0x0132] = "2026:01:02 03:04:05"  # DateTime
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def test_extract_dimensions_and_format():
    meta = extract_image_metadata(_png_bytes((12, 5)))
    assert meta.format == "PNG"
    assert (meta.width, meta.height) == (12, 5)


def test_no_exif_is_reported_not_judged():
    meta = extract_image_metadata(_png_bytes())
    assert meta.exif == {}
    d = meta.to_dict()
    assert d["has_exif"] is False
    assert any("No EXIF" in o for o in d["observations"])
    # honesty: never a verdict / score
    assert "authenticity" not in str(d).lower()
    assert "score" not in str(d).lower()


def test_software_tag_observed():
    meta = extract_image_metadata(_jpeg_with_software_tag())
    assert "Software" in meta.exif
    assert any("software" in o.lower() for o in meta.observations)
    # It has a DateTime tag, so there must be NO "missing timestamp" observation.
    assert not any("No capture" in o for o in meta.observations)


def test_non_image_raises():
    with pytest.raises(ImageError):
        extract_image_metadata(b"this is not an image")


def test_api_image_metadata():
    client = TestClient(app)
    r = client.post(
        "/api/verify/image-metadata",
        files={"file": ("red.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["format"] == "PNG"
    assert body["has_exif"] is False
    assert "note" in body


def test_api_rejects_non_image():
    client = TestClient(app)
    r = client.post(
        "/api/verify/image-metadata",
        files={"file": ("x.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 400
