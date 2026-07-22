"""
Streamlit Dashboard — Acme Corp Invoice Processing
Run: streamlit run app.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

from config import Config
from orchestrator.workflow import create_workflow, build_initial_state
from setup_db import setup_database

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Acme Invoice Processor",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS overrides ──────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    .stMetric > label { font-size: 0.8rem !important; }
    .status-approved { color: #22c55e; font-weight: bold; }
    .status-rejected { color: #ef4444; font-weight: bold; }
    .stage-badge {
        display: inline-block; padding: 2px 8px; border-radius: 12px;
        font-size: 0.75rem; font-weight: 600; margin: 2px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ensure_db():
    if not Path(Config.DB_PATH).exists():
        setup_database()


def _get_invoice_files():
    d = Path(Config.INVOICES_DIR)
    if not d.exists():
        return []
    return sorted(d.glob("INV-*"))


def _run_invoice(path: str) -> dict:
    workflow = create_workflow()
    state = build_initial_state(path)
    return workflow.invoke(state)


def _decision_color(decision: str) -> str:
    return "#22c55e" if decision == "APPROVED" else "#ef4444"


def _format_flags(flags: list[dict]) -> str:
    lines = []
    for f in flags:
        icon = "🔴" if f.get("severity") == "error" else "🟡"
        lines.append(f"{icon} **{f.get('flag_type', '')}**: {f.get('message', '')}")
    return "\n".join(lines) if lines else "✅ No flags"


# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/factory.png", width=64)
    st.title("Invoice Processor")
    st.caption("Acme Corp · Automated Pipeline")
    st.divider()

    _ensure_db()

    mode = st.radio("Mode", ["Single Invoice", "Batch Processing"], horizontal=True)

    if mode == "Single Invoice":
        invoice_files = _get_invoice_files()
        names = [f.name for f in invoice_files]
        selected_name = st.selectbox("Select invoice", names) if names else None
        uploaded = st.file_uploader("Or upload invoice", type=["txt", "pdf", "json", "csv"])

        process_btn = st.button("▶ Process Invoice", type="primary", use_container_width=True)

    else:
        batch_btn = st.button("▶ Run All Invoices", type="primary", use_container_width=True)

    st.divider()
    st.caption(f"LLM: `{Config.resolved_provider()}`")
    st.caption(f"DB: `{Path(Config.DB_PATH).name}`")


# ── Main area ──────────────────────────────────────────────────────────────────

st.title("🏭 Acme Corp — Invoice Processing Automation")
st.caption("Multi-agent pipeline: **Ingest → Validate → Approve → Pay**")

if mode == "Single Invoice":
    if process_btn:
        # Resolve path
        if uploaded:
            tmp = Path("/tmp") / uploaded.name
            tmp.write_bytes(uploaded.read())
            invoice_path = str(tmp)
        elif selected_name:
            invoice_path = str(Path(Config.INVOICES_DIR) / selected_name)
        else:
            st.error("No invoice selected or uploaded.")
            st.stop()

        # Show raw content
        raw_col, result_col = st.columns([1, 1])
        with raw_col:
            st.subheader("📄 Raw Invoice")
            try:
                content = Path(invoice_path).read_text(errors="replace")
                st.code(content[:2000], language="text")
            except Exception as e:
                st.warning(f"Could not preview: {e}")

        with result_col:
            st.subheader("⚙️ Processing...")
            with st.spinner("Running multi-agent pipeline..."):
                t0 = time.time()
                result = _run_invoice(invoice_path)
                elapsed = time.time() - t0

            decision = result.get("approval_decision") or "ERROR"
            payment = result.get("payment_status") or "skipped"
            color = _decision_color(decision)

            st.markdown(
                f"<h2 style='color:{color};margin:0'>"
                f"{'✓' if decision == 'APPROVED' else '✗'} {decision}</h2>",
                unsafe_allow_html=True,
            )

            m1, m2, m3 = st.columns(3)
            m1.metric("Amount", f"${result.get('amount', 0):,.2f}" if result.get("amount") else "—")
            m2.metric("Risk Score", f"{result.get('risk_score', 0):.2f}")
            m3.metric("Time", f"{elapsed*1000:.0f} ms")

            st.write("**Vendor:**", result.get("vendor") or "—")
            st.write("**Invoice ID:**", result.get("invoice_id") or "—")
            st.write("**Due Date:**", result.get("due_date") or "—")
            st.write("**Extraction Confidence:**", f"{result.get('extraction_confidence', 0):.0%}")

            if payment == "success":
                st.success(f"Payment processed · TXN: `{result.get('payment_transaction_id')}`")
            elif decision == "REJECTED":
                st.error("Payment blocked — invoice rejected")

        # Flags & reasoning
        st.divider()
        fcol, rcol = st.columns(2)
        with fcol:
            st.subheader("🚩 Validation Flags")
            st.markdown(_format_flags(result.get("validation_flags") or []))

        with rcol:
            st.subheader("💬 Approval Reasoning")
            st.info(result.get("approval_reasoning") or "—")
            if result.get("critique_notes"):
                with st.expander("🔍 Critique Notes"):
                    st.write(result["critique_notes"])

        # Audit trail
        with st.expander("📋 Full Audit Trail"):
            st.json(result.get("audit_log") or [])

    else:
        # Landing state
        if _get_invoice_files():
            st.info("Select an invoice from the sidebar and click **▶ Process Invoice** to begin.")
        else:
            st.warning("No invoices found. Run `python main.py --setup` to initialise sample data.")

elif mode == "Batch Processing":
    if "batch_results" not in st.session_state:
        st.session_state.batch_results = []

    if batch_btn:
        files = _get_invoice_files()
        if not files:
            st.error("No invoice files found.")
        else:
            results = []
            progress = st.progress(0, text="Initialising batch...")
            status_container = st.empty()

            for i, fpath in enumerate(files):
                status_container.info(f"Processing {fpath.name} ({i+1}/{len(files)})…")
                t0 = time.time()
                r = _run_invoice(str(fpath))
                r["_processing_ms"] = int((time.time() - t0) * 1000)
                results.append(r)
                progress.progress((i + 1) / len(files), text=f"{fpath.name} done")

            status_container.empty()
            st.session_state.batch_results = results
            st.success(f"Batch complete — {len(results)} invoices processed")

    if st.session_state.batch_results:
        results = st.session_state.batch_results
        approved = [r for r in results if r.get("approval_decision") == "APPROVED"]
        rejected = [r for r in results if r.get("approval_decision") != "APPROVED"]
        total_value = sum(r.get("amount", 0) or 0 for r in approved)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Processed", len(results))
        m2.metric("Approved", len(approved), delta=f"{len(approved)/len(results):.0%} rate")
        m3.metric("Rejected", len(rejected))
        m4.metric("Value Approved", f"${total_value:,.0f}")

        st.divider()

        # Summary table
        rows = []
        for r in results:
            rows.append({
                "Invoice": r.get("invoice_id") or "—",
                "Vendor": (r.get("vendor") or "—")[:30],
                "Amount": r.get("amount") or 0,
                "Decision": r.get("approval_decision") or "ERROR",
                "Risk": round(r.get("risk_score", 0), 2),
                "Fraud": round(r.get("fraud_score", 0), 2),
                "ms": r.get("_processing_ms", 0),
            })

        df = pd.DataFrame(rows)

        def _color_decision(val):
            return "color: #22c55e" if val == "APPROVED" else "color: #ef4444"

        styled = df.style.map(_color_decision, subset=["Decision"])
        st.dataframe(styled, use_container_width=True, hide_index=True)

        # Charts
        chart_col1, chart_col2 = st.columns(2)
        with chart_col1:
            fig = px.pie(
                values=[len(approved), len(rejected)],
                names=["Approved", "Rejected"],
                color_discrete_sequence=["#22c55e", "#ef4444"],
                title="Decision Distribution",
            )
            fig.update_layout(margin=dict(t=40, b=0))
            st.plotly_chart(fig, use_container_width=True)

        with chart_col2:
            fig2 = px.histogram(
                df, x="Risk", nbins=10,
                title="Risk Score Distribution",
                color_discrete_sequence=["#3b82f6"],
            )
            fig2.update_layout(margin=dict(t=40, b=0))
            st.plotly_chart(fig2, use_container_width=True)

        # Rejection breakdown
        if rejected:
            st.subheader("🔴 Rejection Details")
            for r in rejected:
                with st.expander(f"{r.get('invoice_id')} — {r.get('vendor')}"):
                    st.write("**Reasoning:**", r.get("approval_reasoning") or "—")
                    flags = r.get("validation_flags") or []
                    if flags:
                        st.markdown(_format_flags(flags))
