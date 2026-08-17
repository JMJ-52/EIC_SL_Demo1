from __future__ import annotations

import os

from lifecycle.extraction.models import ParsedUnit
from lifecycle.extraction.pdf_parser import parse_pdf
from lifecycle.extraction.pptx_parser import parse_pptx
from lifecycle.extraction.xlsx_parser import parse_xlsx

_PARSERS = {".pdf": parse_pdf, ".pptx": parse_pptx, ".xlsx": parse_xlsx}


def parse_uploaded_files(file_paths: list[str]) -> list[ParsedUnit]:
    units: list[ParsedUnit] = []
    for path in file_paths:
        ext = os.path.splitext(path)[1].lower()
        parser = _PARSERS.get(ext)
        if parser is None:
            raise ValueError(f"Unsupported file type: {path}")
        units.extend(parser(path))
    return units

