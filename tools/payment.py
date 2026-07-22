"""Mock payment API — simulates a real bank/ERP disbursement endpoint."""
from __future__ import annotations

import hashlib
import time
from datetime import datetime


def mock_payment(vendor: str, amount: float) -> dict:
    """
    Simulate payment processing.
    Returns a result dict with status, transaction_id, and timestamp.
    """
    # Simulate brief processing latency (non-blocking)
    tx_id = _generate_tx_id(vendor, amount)

    print(f"[PaymentAPI] Processing ${amount:,.2f} to {vendor} ...")
    print(f"[PaymentAPI] Transaction {tx_id} — SUCCESS")

    return {
        "status": "success",
        "transaction_id": tx_id,
        "vendor": vendor,
        "amount": amount,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "message": f"Payment of ${amount:,.2f} to {vendor} processed successfully.",
    }


def _generate_tx_id(vendor: str, amount: float) -> str:
    raw = f"{vendor}-{amount}-{time.time()}"
    return "TXN-" + hashlib.sha256(raw.encode()).hexdigest()[:12].upper()
