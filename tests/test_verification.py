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


@pytest.mark.parametrize("side", [8000, 13000])
def test_a_small_file_declaring_huge_dimensions_is_refused_before_decoding(side):
    """A ~20 KB PNG can declare 169 million pixels and decode to ~670 MB (security read,
    Lane M): the header's size is checked first, both under Pillow's own bomb limit
    (8000 x 8000 = 64 MP) and over it, and the refusal is a 400 with a reason, not a 500."""
    buf = io.BytesIO()
    Image.new("1", (side, side)).save(buf, "PNG")
    assert len(buf.getvalue()) < 100_000
    with pytest.raises(ImageError, match="too large"):
        extract_image_metadata(buf.getvalue())
    r = TestClient(app).post(
        "/api/verify/image-metadata", files={"file": ("big.png", buf.getvalue(), "image/png")}
    )
    assert r.status_code == 400 and "too large" in r.json()["detail"]


def test_the_capture_date_in_the_exif_sub_block_is_read():
    """DateTimeOriginal lives in the Exif sub-block (tag 0x8769), not the main block: a
    photo whose only date is its capture date must not read as "no date" (final read,
    Lane M), and the internal pointer itself is not listed as a tag."""
    exif = Image.Exif()
    exif[0x0110] = "Cam"  # Model
    exif.get_ifd(0x8769)[0x9003] = "2026:01:02 10:11:12"  # DateTimeOriginal
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, "JPEG", exif=exif.tobytes())
    meta = extract_image_metadata(buf.getvalue())
    assert meta.exif.get("DateTimeOriginal") == "2026:01:02 10:11:12", meta.exif
    assert "ExifOffset" not in meta.exif
    assert not any("No capture" in o for o in meta.observations)


def test_a_json_of_another_shape_is_not_a_bundle_and_not_a_500():
    r = TestClient(app).post("/api/reports/evidence/verify", json={"bundle": {"manifest": "x"}})
    assert r.status_code == 200, r.text
    assert r.json() == {
        "verified": False,
        "reason": "malformed bundle: not the shape this app exports",
    }


def test_pointers_are_not_tags_binary_is_named_and_the_main_block_wins():
    exif = Image.Exif()
    exif[0x0131] = "MainSoft"  # Software, main block
    sub = exif.get_ifd(0x8769)
    sub[0x0131] = "SubSoft"
    sub[0x927C] = b"\x00\xff" * 5000  # MakerNote
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, "JPEG", exif=exif.tobytes())
    meta = extract_image_metadata(buf.getvalue())
    assert meta.exif["Software"] == "MainSoft"
    assert meta.exif["MakerNote"] == "(10000 bytes of binary data, not shown)"
    assert not {"ExifOffset", "ExifInteroperabilityOffset"} & set(meta.exif)
