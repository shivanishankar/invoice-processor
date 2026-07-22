"""
Validation Agent — Stage 2
Checks extracted invoice data against the SQLite inventory database.
Also runs heuristic fraud detection before database lookups.
"""
from __future__ import annotations

import re
from datetime import datetime, date
from typing import Any

from config import Config
from tools.inventory import check_item_stock, get_vendor_info
from utils.logger import logger

# Service-type keywords that don't have inventory records — treat as warnings not errors
_SERVICE_KEYWORDS = {
    "service", "services", "consulting", "maintenance", "labor", "installation",
    "support", "training", "fee", "fees", "shipping", "freight", "handling",
}


def run_validation(state: dict) -> dict:
    """LangGraph node: validate extracted invoice data against business rules & inventory."""
    logger.stage("VALIDATE", f"Checking {state.get('invoice_id', 'unknown')} — {state.get('vendor')}")

    flags: list[dict] = []
    fraud_signals: list[str] = []

    items = state.get("items") or []
    amount = state.get("amount")
    vendor = state.get("vendor") or ""
    due_date_str = state.get("due_date") or ""

    # ── 1. Heuristic fraud detection (pre-DB) ────────────────────────────────
    fraud_signals.extend(_detect_fraud_signals(vendor, amount, due_date_str, state.get("raw_text", "")))

    # ── 2. Item-level inventory validation ───────────────────────────────────
    for item in items:
        item_flags = _validate_item(item, Config.DB_PATH)
        flags.extend(item_flags)

    # ── 3. Data integrity checks ─────────────────────────────────────────────
    flags.extend(_check_data_integrity(items, amount, due_date_str))

    # ── 4. Vendor approval check ─────────────────────────────────────────────
    flags.extend(_check_vendor(vendor, Config.DB_PATH))

    # ── 5. Add fraud signals as flags ────────────────────────────────────────
    for signal in fraud_signals:
        flags.append({
            "flag_type": "fraud_indicator",
            "item": None,
            "severity": "error",
            "message": signal,
        })

    # ── 6. Compute fraud score (0–1) ─────────────────────────────────────────
    errors = [f for f in flags if f["severity"] == "error"]
    warnings = [f for f in flags if f["severity"] == "warning"]
    fraud_score = min(1.0, len(errors) * 0.25 + len(warnings) * 0.05)

    # ── 7. Pass/fail decision ─────────────────────────────────────────────────
    # Hard errors block approval; warnings are passed to approval agent
    passed = len(errors) == 0

    _log_flags(flags)
    logger.success("VALIDATE", f"Result: {'PASS' if passed else 'FAIL'} | {len(errors)} errors, {len(warnings)} warnings | Fraud score: {fraud_score:.2f}")

    return {
        **state,
        "current_stage": "validating",
        "validation_passed": passed,
        "validation_flags": flags,
        "fraud_score": fraud_score,
        "audit_log": state.get("audit_log", []) + [
            _audit("validate", "pass" if passed else "fail", {
                "flags": flags,
                "fraud_score": fraud_score,
                "errors": len(errors),
                "warnings": len(warnings),
            })
        ],
    }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _validate_item(item: dict, db_path: str) -> list[dict]:
    flags = []
    name = item.get("name", "")
    qty = item.get("quantity", 0)

    # Skip service-line items
    if any(kw in name.lower() for kw in _SERVICE_KEYWORDS):
        flags.append({
            "flag_type": "unknown_item",
            "item": name,
            "severity": "warning",
            "message": f"'{name}' appears to be a service — not tracked in inventory.",
        })
        return flags

    # Negative quantity
    if qty < 0:
        flags.append({
            "flag_type": "negative_quantity",
            "item": name,
            "severity": "error",
            "message": f"'{name}' has negative quantity ({qty}). Possible credit memo or data error.",
        })
        return flags

    # DB lookup
    result = check_item_stock(name, db_path)
    if not result["found"]:
        flags.append({
            "flag_type": "unknown_item",
            "item": name,
            "severity": "error",
            "message": f"'{name}' not found in inventory database.",
        })
    elif result["stock"] == 0:
        flags.append({
            "flag_type": "out_of_stock",
            "item": name,
            "severity": "error",
            "message": f"'{name}' has zero stock — cannot fulfill this order.",
        })
    elif result["stock"] < qty:
        flags.append({
            "flag_type": "stock_mismatch",
            "item": name,
            "severity": "error",
            "message": (
                f"'{name}' requests {qty} units but only {result['stock']} in stock."
            ),
        })

    return flags


def _detect_fraud_signals(vendor: str, amount: Any, due_date_str: str, raw_text: str) -> list[str]:
    signals = []

    # Structuring: amount suspiciously close to approval threshold from below
    if amount and 9_000 <= amount <= 9_999:
        signals.append(
            f"Amount ${amount:,.2f} is just below the $10,000 scrutiny threshold — potential structuring."
        )

    # Urgency language
    urgency = re.search(r"\b(urgent|asap|immediate|rush|right away|pay now)\b", raw_text, re.IGNORECASE)
    if urgency:
        signals.append(f"Invoice contains urgency language: '{urgency.group()}'.")

    # Vague/suspicious vendor names
    suspicious_vendor_words = {"quickbucks", "fastpay", "cashflow", "rapidpay", "urgentcorp", "shadytransactions"}
    if any(w in vendor.lower().replace(" ", "") for w in suspicious_vendor_words):
        signals.append(f"Vendor name '{vendor}' matches suspicious patterns.")

    return signals


def _check_data_integrity(items: list[dict], amount: Any, due_date_str: str) -> list[dict]:
    flags = []

    if not items:
        flags.append({
            "flag_type": "missing_field",
            "item": None,
            "severity": "warning",
            "message": "No line items found in invoice.",
        })

    if amount is None:
        flags.append({
            "flag_type": "missing_field",
            "item": None,
            "severity": "error",
            "message": "Invoice total amount is missing.",
        })
    elif amount <= 0:
        flags.append({
            "flag_type": "data_integrity",
            "item": None,
            "severity": "error",
            "message": f"Invoice total is non-positive: ${amount}.",
        })

    if due_date_str:
        try:
            parsed = _parse_date(due_date_str)
            if parsed and parsed < date.today():
                flags.append({
                    "flag_type": "data_integrity",
                    "item": None,
                    "severity": "warning",
                    "message": f"Due date '{due_date_str}' is in the past.",
                })
        except Exception:
            pass

    return flags


def _check_vendor(vendor: str, db_path: str) -> list[dict]:
    if not vendor:
        return [{"flag_type": "missing_field", "item": None, "severity": "error", "message": "Vendor name missing."}]
    info = get_vendor_info(vendor, db_path)
    if not info["found"]:
        return [{
            "flag_type": "fraud_indicator",
            "item": None,
            "severity": "warning",
            "message": f"Vendor '{vendor}' is not in the approved vendor list.",
        }]
    return []


def _parse_date(s: str):
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y", "%B %d %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _log_flags(flags: list[dict]):
    for f in flags:
        if f["severity"] == "error":
            logger.error("VALIDATE", f"[{f['flag_type']}] {f['message']}")
        else:
            logger.warning("VALIDATE", f"[{f['flag_type']}] {f['message']}")


def _audit(stage: str, status: str, detail: Any) -> dict:
    return {"stage": stage, "status": status, "timestamp": datetime.utcnow().isoformat(), "detail": detail}
