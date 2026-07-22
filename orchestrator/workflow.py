"""
LangGraph multi-agent workflow for invoice processing.

Graph topology:
  START → ingest ──(success)──→ validate → approve ──(approved)──→ pay → END
               ↑(retry)                           └──(rejected)──→ reject → END
               └──(max retries)──────────────────────────────────→ reject → END
"""
from __future__ import annotations

from typing import Literal

from langgraph.graph import StateGraph, END

from agents.ingestion_agent import run_ingestion
from agents.validation_agent import run_validation
from agents.approval_agent import run_approval
from agents.payment_agent import run_payment, run_rejection
from config import Config


# ── Routing functions ─────────────────────────────────────────────────────────

def _route_after_ingest(state: dict) -> Literal["validate", "ingest", "reject"]:
    """Decide: pass to validation, retry extraction, or reject if max retries hit."""
    retry_count = state.get("retry_count", 0)
    has_required = bool(
        state.get("vendor")
        and state.get("amount") is not None
        and state.get("items")
    )

    if has_required:
        return "validate"
    if retry_count >= state.get("max_retries", Config.MAX_RETRIES):
        return "reject"
    return "ingest"  # loop back for another attempt


def _route_after_approve(state: dict) -> Literal["pay", "reject"]:
    """Route to payment if approved, rejection log otherwise."""
    return "pay" if state.get("approval_decision") == "APPROVED" else "reject"


# ── Graph assembly ─────────────────────────────────────────────────────────────

def create_workflow():
    """Build and compile the LangGraph invoice processing workflow."""
    graph = StateGraph(dict)

    graph.add_node("ingest", run_ingestion)
    graph.add_node("validate", run_validation)
    graph.add_node("approve", run_approval)
    graph.add_node("pay", run_payment)
    graph.add_node("reject", run_rejection)

    graph.set_entry_point("ingest")

    graph.add_conditional_edges(
        "ingest",
        _route_after_ingest,
        {
            "validate": "validate",
            "ingest": "ingest",
            "reject": "reject",
        },
    )

    graph.add_edge("validate", "approve")

    graph.add_conditional_edges(
        "approve",
        _route_after_approve,
        {
            "pay": "pay",
            "reject": "reject",
        },
    )

    graph.add_edge("pay", END)
    graph.add_edge("reject", END)

    return graph.compile()


# ── Initial state builder ──────────────────────────────────────────────────────

def build_initial_state(invoice_path: str) -> dict:
    return {
        "invoice_path": invoice_path,
        "current_stage": "ingesting",
        "retry_count": 0,
        "max_retries": Config.MAX_RETRIES,
        "file_format": "",
        "raw_text": "",
        "invoice_id": None,
        "vendor": None,
        "amount": None,
        "items": None,
        "due_date": None,
        "extraction_confidence": 0.0,
        "extraction_notes": "",
        "validation_passed": False,
        "validation_flags": [],
        "fraud_score": 0.0,
        "approval_decision": None,
        "approval_reasoning": "",
        "risk_score": 0.0,
        "requires_escalation": False,
        "critique_notes": "",
        "initial_approval_decision": None,
        "payment_status": None,
        "payment_transaction_id": None,
        "audit_log": [],
        "errors": [],
    }
