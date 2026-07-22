"""Lightweight in-memory metrics tracker for batch processing runs."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass
class InvoiceMetric:
    invoice_id: str
    vendor: str | None
    amount: float | None
    decision: str       # APPROVED | REJECTED | ERROR
    risk_score: float
    fraud_score: float
    processing_time_ms: int
    stage_reached: str
    errors: List[str]


class ProcessingMetrics:
    def __init__(self):
        self._records: List[InvoiceMetric] = []
        self._start: float = 0.0

    def start_timer(self):
        self._start = time.time()

    def record(self, state: dict):
        elapsed = int((time.time() - self._start) * 1000)
        decision = state.get("payment_status", "ERROR")
        if state.get("approval_decision") == "APPROVED":
            decision = "APPROVED"
        elif state.get("current_stage") == "failed":
            decision = "REJECTED"

        self._records.append(
            InvoiceMetric(
                invoice_id=state.get("invoice_id") or "N/A",
                vendor=state.get("vendor"),
                amount=state.get("amount"),
                decision=decision,
                risk_score=state.get("risk_score", 0.0),
                fraud_score=state.get("fraud_score", 0.0),
                processing_time_ms=elapsed,
                stage_reached=state.get("current_stage", "unknown"),
                errors=state.get("errors") or [],
            )
        )

    @property
    def records(self) -> List[InvoiceMetric]:
        return list(self._records)

    def summary(self) -> dict:
        if not self._records:
            return {}
        approved = [r for r in self._records if r.decision == "APPROVED"]
        rejected = [r for r in self._records if r.decision == "REJECTED"]
        total_value = sum(r.amount or 0 for r in approved)
        avg_ms = sum(r.processing_time_ms for r in self._records) / len(self._records)
        return {
            "total": len(self._records),
            "approved": len(approved),
            "rejected": len(rejected),
            "approval_rate": len(approved) / len(self._records),
            "total_value_approved": total_value,
            "avg_processing_ms": int(avg_ms),
            "avg_risk_score": sum(r.risk_score for r in self._records) / len(self._records),
        }

    def save_json(self, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)
        out = output_dir / "metrics.json"
        data = {
            "summary": self.summary(),
            "records": [
                {
                    "invoice_id": r.invoice_id,
                    "vendor": r.vendor,
                    "amount": r.amount,
                    "decision": r.decision,
                    "risk_score": r.risk_score,
                    "fraud_score": r.fraud_score,
                    "processing_time_ms": r.processing_time_ms,
                    "errors": r.errors,
                }
                for r in self._records
            ],
        }
        out.write_text(json.dumps(data, indent=2))
        return out
