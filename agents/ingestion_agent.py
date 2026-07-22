"""
Ingestion Agent — Stage 1
Extracts structured invoice data from raw text using LLM function calling.
Self-corrects: if confidence is below threshold, retries with targeted prompts.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from config import Config
from tools.extractor import extract_invoice_text
from tools.llm_client import get_llm_client
from utils.logger import logger

# ── Tool definition (function calling) ────────────────────────────────────────

EXTRACT_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "extract_invoice_data",
            "description": "Extract structured fields from raw invoice text",
            "parameters": {
                "type": "object",
                "properties": {
                    "invoice_id": {"type": "string", "description": "Invoice number / ID"},
                    "vendor": {"type": "string", "description": "Vendor or supplier company name"},
                    "amount": {"type": "number", "description": "Total amount due in USD"},
                    "due_date": {
                        "type": "string",
                        "description": "Payment due date in YYYY-MM-DD or human-readable form",
                    },
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "quantity": {"type": "number"},
                                "unit_price": {"type": "number"},
                                "total_price": {"type": "number"},
                            },
                            "required": ["name", "quantity"],
                        },
                    },
                    "extraction_confidence": {
                        "type": "number",
                        "description": "0–1 confidence in extraction quality",
                    },
                    "extraction_notes": {
                        "type": "string",
                        "description": "Notes about any difficulties, typos, or missing fields",
                    },
                },
                "required": ["extraction_confidence"],
            },
        },
    }
]


def run_ingestion(state: dict) -> dict:
    """LangGraph node: extract invoice data, retry if confidence is low."""
    invoice_path = state["invoice_path"]
    retry_count = state.get("retry_count", 0)

    logger.stage("INGEST", f"Attempt {retry_count + 1}/{Config.MAX_RETRIES} — {invoice_path}")

    # ── Step 1: Extract raw text ──────────────────────────────────────────────
    try:
        raw_text, file_format = extract_invoice_text(invoice_path)
    except Exception as e:
        logger.error("INGEST", f"File read failed: {e}")
        return {
            **state,
            "current_stage": "ingesting",
            "retry_count": retry_count + 1,
            "errors": state.get("errors", []) + [f"INGEST_FILE_ERROR: {e}"],
            "audit_log": state.get("audit_log", []) + [_audit("ingest", "error", str(e))],
        }

    logger.info("INGEST", f"Read {len(raw_text)} chars from {file_format.upper()} file")

    # ── Step 2: LLM extraction via function calling ───────────────────────────
    llm = get_llm_client()
    logger.info("INGEST", f"Using {llm.provider_name}")

    system_msg = _system_prompt(retry_count, state)
    user_msg = f"Extract invoice data from the following text:\n\n{raw_text}"

    try:
        response = llm.chat(
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            tools=EXTRACT_TOOL,
            tool_choice="required",
        )
    except Exception as e:
        logger.error("INGEST", f"LLM call failed: {e}")
        return {
            **state,
            "raw_text": raw_text,
            "file_format": file_format,
            "current_stage": "ingesting",
            "retry_count": retry_count + 1,
            "errors": state.get("errors", []) + [f"INGEST_LLM_ERROR: {e}"],
            "audit_log": state.get("audit_log", []) + [_audit("ingest", "error", str(e))],
        }

    if response["type"] != "tool_call":
        extracted = {}
    else:
        extracted = response["arguments"]

    confidence = float(extracted.get("extraction_confidence", 0.0))
    logger.info("INGEST", f"Confidence: {confidence:.0%} — {extracted.get('extraction_notes', '')}")

    # ── Step 3: Log & return ──────────────────────────────────────────────────
    items = extracted.get("items") or []
    has_required = bool(
        extracted.get("vendor")
        and extracted.get("amount") is not None
        and items
    )

    if has_required:
        logger.success("INGEST", f"Extracted: {extracted.get('vendor')} | ${extracted.get('amount'):,.2f} | {len(items)} line item(s)")
    else:
        missing = [f for f, v in [("vendor", extracted.get("vendor")), ("amount", extracted.get("amount")), ("items", items or None)] if not v]
        logger.warning("INGEST", f"Missing required fields: {', '.join(missing)}")

    return {
        **state,
        "current_stage": "ingesting",
        "raw_text": raw_text,
        "file_format": file_format,
        "retry_count": retry_count + 1,
        "invoice_id": extracted.get("invoice_id"),
        "vendor": extracted.get("vendor"),
        "amount": extracted.get("amount"),
        "items": items,
        "due_date": extracted.get("due_date"),
        "extraction_confidence": confidence,
        "extraction_notes": extracted.get("extraction_notes", ""),
        "audit_log": state.get("audit_log", []) + [
            _audit("ingest", "success" if has_required else "low_confidence", extracted)
        ],
        "errors": state.get("errors", []),
    }


def _system_prompt(retry_count: int, state: dict) -> str:
    base = (
        "You are an expert invoice data extraction specialist. "
        "Extract ALL available fields from the invoice text provided. "
        "Be robust to typos, unusual formatting, and missing data. "
        "If a field cannot be determined, omit it or set it to null. "
        "Set extraction_confidence based on data quality (1.0 = perfect, 0.0 = unusable)."
    )
    if retry_count == 0:
        return base

    # Self-correction prompts for retries
    prev_notes = state.get("extraction_notes", "")
    missing = []
    if not state.get("vendor"):
        missing.append("vendor/supplier name (look for 'From:', 'Vendor:', 'Bill From:', company headers)")
    if state.get("amount") is None:
        missing.append("total amount due (look for 'TOTAL', 'Amount Due', 'Grand Total', last $ value)")
    if not state.get("items"):
        missing.append("line items (look for any product names with quantities or prices)")

    correction = f"\n\nPREVIOUS ATTEMPT ISSUES: {prev_notes or 'Some required fields were missing.'}"
    if missing:
        correction += f"\nPLEASE SPECIFICALLY LOOK FOR: {'; '.join(missing)}"
    correction += "\nBe more thorough this time — scan every line of the text."
    return base + correction


def _audit(stage: str, status: str, detail: Any) -> dict:
    return {
        "stage": stage,
        "status": status,
        "timestamp": datetime.utcnow().isoformat(),
        "detail": detail if isinstance(detail, (str, dict, list)) else str(detail),
    }
