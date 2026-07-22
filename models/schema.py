"""Pydantic models for all invoice processing data structures."""
from __future__ import annotations

from typing import Annotated, Any, List, Literal, Optional
from pydantic import BaseModel, Field
import operator


# ── Invoice data ──────────────────────────────────────────────────────────────

class InvoiceItem(BaseModel):
    name: str
    quantity: float
    unit_price: Optional[float] = None
    total_price: Optional[float] = None


class InvoiceData(BaseModel):
    invoice_id: Optional[str] = None
    vendor: Optional[str] = None
    amount: Optional[float] = None
    items: List[InvoiceItem] = Field(default_factory=list)
    due_date: Optional[str] = None
    notes: Optional[str] = None
    extraction_confidence: float = 1.0
    extraction_notes: str = ""


# ── Validation ────────────────────────────────────────────────────────────────

class ValidationFlag(BaseModel):
    flag_type: Literal[
        "stock_mismatch",
        "unknown_item",
        "out_of_stock",
        "negative_quantity",
        "missing_field",
        "data_integrity",
        "fraud_indicator",
        "duplicate",
        "price_anomaly",
    ]
    item: Optional[str] = None
    severity: Literal["warning", "error"]
    message: str


class ValidationResult(BaseModel):
    passed: bool
    flags: List[ValidationFlag] = Field(default_factory=list)
    fraud_score: float = 0.0   # 0–1 composite risk signal
    notes: str = ""


# ── Approval ──────────────────────────────────────────────────────────────────

class ApprovalResult(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    reasoning: str
    risk_score: float = 0.0   # 0–1
    requires_escalation: bool = False
    critique_notes: str = ""
    initial_decision: Optional[str] = None   # for reflection audit


# ── Payment ───────────────────────────────────────────────────────────────────

class PaymentResult(BaseModel):
    status: Literal["success", "failed", "skipped"]
    transaction_id: Optional[str] = None
    message: str = ""


# ── LangGraph shared state ────────────────────────────────────────────────────

class InvoiceState(dict):
    """
    TypedDict-compatible dict used as LangGraph state.
    Keys with Annotated[List, operator.add] accumulate across nodes.
    All other keys are overwritten by each node's return dict.
    """
    # input
    invoice_path: str

    # stage tracking
    current_stage: str          # ingesting | validating | approving | paying | done | failed
    retry_count: int
    max_retries: int
    file_format: str

    # raw extraction
    raw_text: str

    # ingestion outputs
    invoice_id: Optional[str]
    vendor: Optional[str]
    amount: Optional[float]
    items: Optional[List[dict]]
    due_date: Optional[str]
    extraction_confidence: float
    extraction_notes: str

    # validation outputs
    validation_passed: bool
    validation_flags: List[dict]
    fraud_score: float

    # approval outputs
    approval_decision: Optional[str]
    approval_reasoning: str
    risk_score: float
    requires_escalation: bool
    critique_notes: str
    initial_approval_decision: Optional[str]

    # payment outputs
    payment_status: Optional[str]
    payment_transaction_id: Optional[str]

    # accumulated lists (operator.add merges them)
    audit_log: List[dict]
    errors: List[str]
