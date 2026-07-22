"""
Approval Agent — Stage 3
VP-level decision-making with a two-pass reflection loop:
  1. Initial decision from LLM
  2. Adversarial critique
  3. Revised final decision (if critique raises concerns)
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from config import Config
from tools.llm_client import get_llm_client
from utils.logger import logger

# ── Tool definition ────────────────────────────────────────────────────────────

APPROVAL_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "submit_approval_decision",
            "description": "Submit a formal approval or rejection decision for an invoice",
            "parameters": {
                "type": "object",
                "properties": {
                    "decision": {
                        "type": "string",
                        "enum": ["APPROVED", "REJECTED"],
                        "description": "Final approval decision",
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Detailed justification for the decision",
                    },
                    "risk_score": {
                        "type": "number",
                        "description": "0.0 (no risk) to 1.0 (maximum risk)",
                    },
                    "requires_escalation": {
                        "type": "boolean",
                        "description": "True if VP should manually review before payment",
                    },
                },
                "required": ["decision", "reasoning", "risk_score", "requires_escalation"],
            },
        },
    }
]


def run_approval(state: dict) -> dict:
    """LangGraph node: make approval decision with a reflect-critique-revise loop."""
    vendor = state.get("vendor", "Unknown")
    amount = state.get("amount", 0)
    logger.stage("APPROVE", f"{state.get('invoice_id')} — {vendor} | ${amount:,.2f}")

    high_value = amount and amount > Config.HIGH_VALUE_THRESHOLD
    if high_value:
        logger.warning("APPROVE", f"High-value invoice (${amount:,.2f} > ${Config.HIGH_VALUE_THRESHOLD:,.0f}) — activating extra scrutiny")

    llm = get_llm_client()
    context = _build_context(state)

    # ── Pass 1: Initial decision ───────────────────────────────────────────────
    logger.info("APPROVE", "Pass 1: Generating initial decision...")
    initial = _call_approval_llm(llm, context, pass_number=1)
    if initial is None:
        return _error_state(state, "LLM approval call returned no result")

    logger.info(
        "APPROVE",
        f"Initial: {initial['decision']} (risk={initial['risk_score']:.2f}) — {initial['reasoning'][:80]}..."
        if len(initial["reasoning"]) > 80
        else f"Initial: {initial['decision']} (risk={initial['risk_score']:.2f}) — {initial['reasoning']}",
    )

    # ── Pass 2: Adversarial critique ──────────────────────────────────────────
    logger.info("APPROVE", "Pass 2: Running adversarial critique...")
    critique = _call_critique_llm(llm, context, initial)

    logger.info("APPROVE", f"Critique: {critique[:120]}...")

    # ── Pass 3: Final decision (revised if critique raised concerns) ──────────
    critique_flags_issue = any(
        kw in critique.lower()
        for kw in ["questionable", "concern", "recommend rejection", "reconsider", "overlooked", "risky"]
    )

    if critique_flags_issue or high_value:
        logger.info("APPROVE", "Pass 3: Revising decision based on critique...")
        final = _call_approval_llm(llm, context, pass_number=3, critique=critique, initial=initial)
        if final is None:
            final = initial
    else:
        logger.info("APPROVE", "Pass 3: Critique found no issues — initial decision stands")
        final = initial

    decision = final["decision"]
    risk_score = final["risk_score"]
    logger.success(
        "APPROVE",
        f"FINAL DECISION: {decision} | Risk: {risk_score:.2f} | Escalation: {final.get('requires_escalation', False)}",
    )

    return {
        **state,
        "current_stage": "approving",
        "approval_decision": decision,
        "approval_reasoning": final["reasoning"],
        "risk_score": risk_score,
        "requires_escalation": final.get("requires_escalation", False),
        "critique_notes": critique,
        "initial_approval_decision": initial["decision"],
        "audit_log": state.get("audit_log", []) + [
            _audit("approve", decision.lower(), {
                "initial_decision": initial["decision"],
                "initial_risk_score": initial["risk_score"],
                "critique": critique,
                "final_decision": decision,
                "final_risk_score": risk_score,
                "reasoning": final["reasoning"],
            })
        ],
    }


# ── LLM call helpers ───────────────────────────────────────────────────────────

def _call_approval_llm(llm, context: str, pass_number: int, critique: str = "", initial: dict = None) -> dict | None:
    if pass_number == 1:
        system = _system_prompt_initial()
    else:
        system = _system_prompt_revision(critique, initial)

    try:
        response = llm.chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": context},
            ],
            tools=APPROVAL_TOOL,
            tool_choice="required",
        )
    except Exception as e:
        logger.error("APPROVE", f"LLM call failed: {e}")
        return None

    if response["type"] == "tool_call":
        return response["arguments"]
    # Fallback: parse text response
    return {"decision": "REJECTED", "reasoning": response.get("content", "LLM did not return structured output"), "risk_score": 0.5, "requires_escalation": True}


def _call_critique_llm(llm, context: str, initial: dict) -> str:
    system = (
        "You are a skeptical VP of Finance conducting a second review. "
        "Your job is to CHALLENGE the initial approval decision below. "
        "Look for red flags that were missed, logical gaps, or risks that weren't weighted properly. "
        "If the decision seems sound, say so briefly. Be direct and concise."
    )
    user = (
        f"INVOICE CONTEXT:\n{context}\n\n"
        f"INITIAL DECISION: {initial['decision']}\n"
        f"INITIAL REASONING: {initial['reasoning']}\n"
        f"INITIAL RISK SCORE: {initial['risk_score']}\n\n"
        "Critically evaluate this decision. What concerns, if any, were overlooked?"
    )
    try:
        response = llm.chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )
        return response.get("content", "No critique returned.")
    except Exception as e:
        return f"Critique unavailable: {e}"


# ── Prompt builders ────────────────────────────────────────────────────────────

def _system_prompt_initial() -> str:
    return (
        "You are the VP of Finance at Acme Corp reviewing an invoice for payment approval.\n\n"
        "Approval criteria:\n"
        "• Invoices ≤ $10,000: Approve if items are in stock and no major flags exist.\n"
        "• Invoices > $10,000: Apply extra scrutiny — verify line items are fully itemized.\n"
        "• ANY fraud indicator (structuring, suspicious vendor, zero-stock item): REJECT.\n"
        "• Data integrity errors (negative amounts, missing vendor): REJECT.\n"
        "• Inventory shortfalls: REJECT.\n"
        "• Warnings alone do not require rejection but increase risk score.\n\n"
        "Assess risk holistically and provide a clear APPROVED or REJECTED decision."
    )


def _system_prompt_revision(critique: str, initial: dict) -> str:
    return (
        "You are the VP of Finance making a FINAL determination after receiving a second opinion.\n\n"
        f"The initial decision was: {initial['decision']} (risk={initial['risk_score']:.2f})\n"
        f"The critic raised the following concerns: {critique}\n\n"
        "Consider the critique carefully. If the concerns are valid, revise the decision. "
        "If the critique is unfounded, defend the original decision. "
        "Produce a final, definitive APPROVED or REJECTED decision with your complete reasoning."
    )


def _build_context(state: dict) -> str:
    items_str = ""
    for item in (state.get("items") or []):
        items_str += f"  - {item.get('name')}: qty={item.get('quantity')}, unit_price=${item.get('unit_price') or 'N/A'}\n"

    flags = state.get("validation_flags") or []
    errors = [f for f in flags if f.get("severity") == "error"]
    warnings = [f for f in flags if f.get("severity") == "warning"]
    fraud_score = state.get("fraud_score", 0.0)

    flags_str = ""
    for f in errors:
        flags_str += f"  [ERROR][{f.get('flag_type', '')}] {f['message']}\n"
    for f in warnings:
        flags_str += f"  [WARN][{f.get('flag_type', '')}] {f['message']}\n"

    return (
        f"Invoice ID: {state.get('invoice_id', 'N/A')}\n"
        f"Vendor: {state.get('vendor', 'N/A')}\n"
        f"Amount: ${state.get('amount', 0):,.2f}\n"
        f"Due Date: {state.get('due_date', 'N/A')}\n"
        f"Extraction Confidence: {state.get('extraction_confidence', 0):.0%}\n\n"
        f"Line Items:\n{items_str or '  (none extracted)'}\n"
        f"Validation Result: {'PASS' if state.get('validation_passed') else 'FAIL'}\n"
        f"Fraud Score: {fraud_score:.2f}\n"
        f"Flags ({len(errors)} errors, {len(warnings)} warnings):\n{flags_str or '  (none)'}"
    )


def _error_state(state: dict, msg: str) -> dict:
    return {
        **state,
        "current_stage": "approving",
        "approval_decision": "REJECTED",
        "approval_reasoning": f"Approval agent error: {msg}",
        "risk_score": 1.0,
        "errors": state.get("errors", []) + [f"APPROVE_ERROR: {msg}"],
        "audit_log": state.get("audit_log", []) + [_audit("approve", "error", msg)],
    }


def _audit(stage: str, status: str, detail: Any) -> dict:
    return {"stage": stage, "status": status, "timestamp": datetime.utcnow().isoformat(), "detail": detail}
