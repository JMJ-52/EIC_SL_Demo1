from __future__ import annotations

import os

import fitz

from lifecycle.extraction.models import ParsedUnit

SPARSE_TEXT_THRESHOLD = 30


def parse_pdf(path: str) -> list[ParsedUnit]:
    source_doc = os.path.basename(path)
    doc = fitz.open(path)
    units = []
    for page_number, page in enumerate(doc, start=1):
        text = page.get_text().strip()
        images: list[bytes] = []
        if len(text) < SPARSE_TEXT_THRESHOLD:
            pixmap = page.get_pixmap(dpi=150)
            images.append(pixmap.tobytes("png"))
        units.append(
            ParsedUnit(source_doc=source_doc, unit_label=f"p.{page_number}", text=text, images=images)
        )
    doc.close()
    return units

