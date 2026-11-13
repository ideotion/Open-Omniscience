"""
Honest image metadata / EXIF extraction.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

This is the genuine, honest piece revived from the quarantined Pillar 3 (see
docs/QUARANTINE_ARCHIVE.md). It reports the metadata that is *actually present* in an
image and raises plain, factual observations a journalist can verify themselves
(e.g. "an editing-software tag is present", "no capture timestamp", "GPS coords
present"). It does NOT claim to detect manipulation or output an "authenticity
score" -- metadata is evidence to weigh, not a verdict.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

from PIL import Image, UnidentifiedImageError
from PIL.ExifTags import GPSTAGS, TAGS

from src.monitoring.secret_scrub import record_text


class ImageError(ValueError):
    """The bytes could not be read as an image."""


# A few hundred KB of PNG can declare 13000 x 13000 pixels and decode to ~670 MB. The
# header gives the size before any pixel is decoded, so refuse past this many pixels
# (about 200 MB at four bytes a pixel; above any ordinary camera's 50 MP).
MAX_DECODE_PIXELS = 50_000_000


@dataclass
class ImageMetadata:
    format: str | None
    width: int
    height: int
    exif: dict
    gps: dict
    observations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "format": self.format,
            "width": self.width,
            "height": self.height,
            "has_exif": bool(self.exif),
            "exif": self.exif,
            "gps": self.gps,
            "observations": self.observations,
            "note": (
                "Metadata is evidence to weigh, not proof. Absence of EXIF is common "
                "(many platforms strip it) and does not by itself indicate tampering."
            ),
        }


def _jsonable(value):
    """Coerce EXIF values (bytes, IFDRational, tuples) into JSON-safe forms."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    try:
        # IFDRational and similar are float-able.
        return float(value) if hasattr(value, "numerator") else value
    except (TypeError, ValueError):
        return str(value)


def _parse_gps(gps_ifd: dict) -> dict:
    out = {}
    for key, val in gps_ifd.items():
        name = GPSTAGS.get(key, str(key))
        out[name] = _jsonable(val)
    return out


def extract_image_metadata(data: bytes) -> ImageMetadata:
    """Extract format, dimensions, EXIF and GPS from image bytes."""
    # (no process-wide warnings filter: this runs in a thread pool, and the cap below
    # fires before Pillow's own bomb warning; past twice that, open() itself raises)
    try:
        img = Image.open(io.BytesIO(data))
        if img.width * img.height > MAX_DECODE_PIXELS:
            raise ImageError(
                f"image too large to read here: {img.width} x {img.height} pixels "
                f"(limit {MAX_DECODE_PIXELS:,})"
            )
        img.load()
    except Image.DecompressionBombError as exc:
        raise ImageError(f"image too large to read here: {record_text(exc)}") from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageError(f"not a readable image: {record_text(exc)}") from exc

    exif_raw = img.getexif()
    exif: dict = {}
    gps: dict = {}
    if exif_raw:
        for tag_id, value in exif_raw.items():
            name = TAGS.get(tag_id, str(tag_id))
            if name == "GPSInfo":
                try:
                    gps = _parse_gps(exif_raw.get_ifd(tag_id))
                except Exception:
                    gps = {}
            elif name == "ExifOffset":
                # the pointer to the Exif sub-block, where the CAPTURE date
                # (DateTimeOriginal), exposure and lens live: read it, never list the pointer
                try:
                    for sub_id, sub_val in exif_raw.get_ifd(tag_id).items():
                        exif[TAGS.get(sub_id, str(sub_id))] = _jsonable(sub_val)
                except Exception:
                    pass
            else:
                exif[name] = _jsonable(value)

    observations: list[str] = []
    if not exif:
        observations.append("No EXIF metadata present (often stripped by platforms).")
    if "Software" in exif:
        observations.append(f"Editing/processing software tag present: {exif['Software']!r}.")
    if not any(k in exif for k in ("DateTime", "DateTimeOriginal", "DateTimeDigitized")):
        observations.append("No capture/modification timestamp in EXIF.")
    if gps:
        observations.append("GPS coordinates are embedded in the image.")
    if "Make" in exif or "Model" in exif:
        cam = " ".join(str(exif.get(k, "")) for k in ("Make", "Model")).strip()
        observations.append(f"Camera make/model recorded: {cam}.")

    return ImageMetadata(
        format=img.format,
        width=img.width,
        height=img.height,
        exif=exif,
        gps=gps,
        observations=observations,
    )
