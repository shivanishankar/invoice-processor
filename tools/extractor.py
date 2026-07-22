"""
Text extraction from multiple file formats.
Supports: PDF (via pdfplumber), TXT, JSON, CSV.
Falls back gracefully if PDF libraries are unavailable.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path


def extract_invoice_text(file_path: str) -> tuple[str, str]:
    """
    Return (raw_text, file_format) for any supported invoice file.
    file_format: 'pdf' | 'txt' | 'json' | 'csv'
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return _extract_pdf(path), "pdf"
    elif suffix == ".json":
        return _extract_json(path), "json"
    elif suffix == ".csv":
        return _extract_csv(path), "csv"
    else:
        return path.read_text(encoding="utf-8", errors="replace"), "txt"


def _extract_pdf(path: Path) -> str:
    """Try pdfplumber first, fall back to PyMuPDF, then raw text."""
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
        return "\n".join(pages).strip()
    except Exception:
        pass

    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(path))
        pages = [page.get_text() for page in doc]
        doc.close()
        return "\n".join(pages).strip()
    except Exception:
        pass

    # Last resort — treat as text
    return path.read_text(encoding="utf-8", errors="replace")


def _extract_json(path: Path) -> str:
    """Pretty-print JSON as text for the LLM to parse."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return json.dumps(data, indent=2)


def _extract_csv(path: Path) -> str:
    """Convert CSV rows to a readable text block."""
    text = path.read_text(encoding="utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return text

    lines = ["CSV Invoice Data:"]
    for row in rows:
        lines.append("  " + ", ".join(f"{k}: {v}" for k, v in row.items()))
    return "\n".join(lines)
