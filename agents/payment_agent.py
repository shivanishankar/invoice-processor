"""
Payment Agent — Stage 4
Processes approved invoices via mock payment API.
Logs rejected invoices with structured reasoning.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from tools.payment import mock_payment
from utils.logger import logger


def run_payment(state: dict) -> dict:
    """LangGraph node: process payment for approved invoices."""
    vendor = state.get("vendor", "Unknown Vendor")
    amount = state.get("amount", 0.0)
    invoice_id = state.get("invoice_id", "N/A")

    logger.stage("PAYMENT", f"Processing {invoice_id} — ${amount:,.2f} to {vendor}")

    try:
        result = mock_payment(vendor=vendor, amount=amount)
        logger.success(
            "PAYMENT",
            f"Transaction {result['transaction_id']} — ${amount:,.2f} sent to {vendor}",
        )

        return {
            **state,
            "current_stage": "done",
            "payment_status": "success",
            "payment_transaction_id": result["transaction_id"],
            "audit_log": state.get("audit_log", []) + [
                _audit("payment", "success", {
                    "transaction_id": result["transaction_id"],
                    "vendor": vendor,
                    "amount": amount,
                    "message": result["message"],
                })
            ],
        }

    except Exception as e:
        logger.error("PAYMENT", f"Payment failed: {e}")
        return {
            **state,
            "current_stage": "failed",
            "payment_status": "failed",
            "errors": state.get("errors", []) + [f"PAYMENT_ERROR: {e}"],
            "audit_log": state.get("audit_log", []) + [_audit("payment", "failed", str(e))],
        }


def run_rejection(state: dict) -> dict:
    """LangGraph node: log structured rejection with reasons."""
    invoice_id = state.get("invoice_id", "N/A")
    vendor = state.get("vendor", "Unknown")
    amount = state.get("amount", 0.0)
    reasoning = state.get("approval_reasoning") or _infer_rejection_reason(state)

    logger.stage("REJECT", f"Recording rejection for {invoice_id}")
    logger.error("REJECT", reasoning)

    flags = state.get("validation_flags") or []
    errors = [f["message"] for f in flags if f.get("severity") == "error"]

    rejection_record = {
        "invoice_id": invoice_id,
        "vendor": vendor,
        "amount": amount,
        "reason": reasoning,
        "validation_errors": errors,
        "risk_score": state.get("risk_score", 0.0),
        "fraud_score": state.get("fraud_score", 0.0),
        "timestamp": datetime.utcnow().isoformat(),
    }

    logger.info("REJECT", f"Rejection logged: {invoice_id} | {len(errors)} validation error(s)")

    return {
        **state,
        "current_stage": "failed",
        "payment_status": "skipped",
        "audit_log": state.get("audit_log", []) + [_audit("rejection", "logged", rejection_record)],
    }


def _infer_rejection_reason(state: dict) -> str:
    """Build a human-readable rejection reason when the approval agent didn't provide one."""
    reasons = []
    flags = state.get("validation_flags") or []
    errors = [f["message"] for f in flags if f.get("severity") == "error"]
    if errors:
        reasons.extend(errors[:3])
    if state.get("extraction_confidence", 1.0) < 0.5:
        reasons.append("Invoice data could not be reliably extracted.")
    if not reasons:
        reasons.append("Invoice did not meet approval criteria.")
    return " | ".join(reasons)


def _audit(stage: str, status: str, detail: Any) -> dict:
    return {"stage": stage, "status": status, "timestamp": datetime.utcnow().isoformat(), "detail": detail}
