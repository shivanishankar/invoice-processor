# Acme Corp — Invoice Processing Automation

Multi-agent system that automates end-to-end invoice processing for a PE-backed manufacturing firm, reducing a 30% error rate and 5-day processing delays.

## Architecture

```
                    ┌──────────────────────────────────────────────┐
                    │           LangGraph Orchestrator             │
                    └──────────────────────────────────────────────┘
                                        │
         ┌──────────────┬───────────────┼───────────────┬──────────────┐
         ▼              ▼               ▼               ▼              ▼
   ┌───────────┐  ┌──────────┐  ┌─────────────┐  ┌─────────┐  ┌──────────┐
   │ Ingestion │  │Validation│  │  Approval   │  │ Payment │  │Rejection │
   │   Agent   │  │  Agent   │  │   Agent     │  │  Agent  │  │  Logger  │
   └───────────┘  └──────────┘  └─────────────┘  └─────────┘  └──────────┘
   • PDF/TXT/JSON  • SQLite DB   • LLM + reflect  • Mock API   • Audit log
   • Function call • Fraud score • Critique loop  • Tx ID      • Reasoning
   • Self-correct  • 9 flag types• Risk 0–1       
```

**Flow:** `START → ingest(retry) → validate → approve → pay/reject → END`

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. (Optional) Set API key in .env
cp .env.example .env
# edit .env and add XAI_API_KEY=... (or leave as mock)

# 3. Setup database
python setup_db.py

# 4. Process a single invoice
python main.py --invoice_path=data/invoices/INV-1001.txt

# 5. Process all invoices (batch mode)
python main.py --batch

# 6. Launch the Streamlit dashboard
streamlit run app.py
```

## Test Matrix

| Invoice | Scenario | Expected Outcome |
|---------|----------|-----------------|
| INV-1001 | Clean — WidgetA×5, WidgetB×3 ($1,458) | ✅ APPROVED, payment processed |
| INV-1002 | GadgetX×20 — only 5 in stock | ❌ REJECTED — stock mismatch |
| INV-1003 | FakeItem (0 stock), QuickBucks LLC, $9,999 | ❌ REJECTED — fraud indicators |
| INV-1004 | High-value $13,000 with services line | ⚠️ Extra scrutiny, conditional approval |
| INV-1005 | CSV format — clean order | ✅ APPROVED |
| INV-1006 | Alternative format — clean | ✅ APPROVED |
| INV-1007 | Missing invoice ID & vendor | 🔄 Self-correction loop → partial rejection |
| INV-1008 | SuperGizmo, MegaSprocket — unknown items | ❌ REJECTED — unknown items |
| INV-1009 | Negative quantities | ❌ REJECTED — data integrity |
| INV-1010 | Heavy typos ("Widgt A", "Wid9etB") | 🔄 LLM normalises + low confidence flag |
| INV-1011 | Duplicate of INV-1001 | ⚠️ Duplicate flag |
| INV-1012 | Large annual contract $14,098 — all in stock | ⚠️ High-value scrutiny, APPROVED |
| INV-1013 | Past due date (2026-04-01) | ⚠️ Overdue warning |
| INV-1014 | Mixed — valid items + SuperGizmo | ❌ REJECTED — unknown item |
| INV-1015 | High-value $11,975 — preferred vendor | ⚠️ Extra scrutiny, APPROVED |
| INV-1016 | WidgetC — in DB but unlisted vendor | ⚠️ Unapproved vendor flag |

## Agent Details

### 1. Ingestion Agent (`agents/ingestion_agent.py`)
- **LLM function calling** to extract: `invoice_id`, `vendor`, `amount`, `items`, `due_date`
- **Self-correction loop**: if `extraction_confidence < 0.65` or required fields missing, retries with targeted prompt (up to 3×)
- Supports PDF, TXT, JSON, CSV

### 2. Validation Agent (`agents/validation_agent.py`)
- Queries SQLite inventory for every line item
- Detects: stock mismatches, unknown items, out-of-stock, negative quantities, missing fields, past due dates
- **Fraud heuristics**: structuring ($9K–$9,999), urgency language, suspicious vendor names
- Outputs `fraud_score` (0–1) and `validation_flags[]`

### 3. Approval Agent (`agents/approval_agent.py`)
- **3-pass reflection loop**:
  1. Initial LLM decision (function calling → structured JSON)
  2. Adversarial critique ("challenge this decision")
  3. Revised final decision if critique raised valid concerns
- High-value threshold ($10K): forces extra scrutiny regardless of clean validation

### 4. Payment Agent (`agents/payment_agent.py`)
- Calls `mock_payment(vendor, amount)` → generates SHA-256 transaction ID
- On rejection: logs structured record with reasons, risk/fraud scores

## Self-Correction in Action

```
[INGEST] Attempt 1: Missing required fields (vendor, amount)
[INGEST] Self-correcting: Prompting LLM to focus on missing fields...
[INGEST] Attempt 2: ✓ Extracted — Acme Supliez | $1,200.00 (confidence: 72%)

[APPROVE] Pass 1: Initial → APPROVED (risk=0.15)
[APPROVE] Pass 2: Critique → "Urgency language 'ASAP' was not weighted"
[APPROVE] Pass 3: Revised → APPROVED (risk=0.22, no change to decision)
```

## LLM Configuration

```python
# Auto-detects from environment:
# 1. XAI_API_KEY  → xAI Grok-3  (primary)
# 2. OPENAI_API_KEY → GPT-4o    (fallback)
# 3. (none)       → Mock LLM   (regex heuristics, no key needed)
```

## Project Structure

```
├── main.py                  # CLI (single & batch modes)
├── app.py                   # Streamlit dashboard
├── config.py                # Central configuration
├── setup_db.py              # Database initialisation
├── agents/
│   ├── ingestion_agent.py   # Stage 1: extract
│   ├── validation_agent.py  # Stage 2: validate
│   ├── approval_agent.py    # Stage 3: approve (with reflection)
│   └── payment_agent.py     # Stage 4: pay/reject
├── orchestrator/
│   └── workflow.py          # LangGraph state machine
├── tools/
│   ├── extractor.py         # PDF/TXT/JSON/CSV parsing
│   ├── inventory.py         # SQLite queries
│   ├── payment.py           # Mock payment API
│   └── llm_client.py        # xAI/OpenAI/Mock abstraction
├── models/schema.py         # Pydantic data models
├── utils/
│   ├── logger.py            # Rich-coloured structured logs
│   └── metrics.py           # Batch processing metrics
└── data/invoices/           # 16 test invoices (TXT/JSON/CSV)
```

## Business Impact

| Metric | Before | After (target) |
|--------|--------|----------------|
| Error rate | 30% | <3% |
| Processing time | 5 days | <30 seconds |
| Manual touches | Every invoice | Exception-only |
| Fraud detection | Ad-hoc | Systematic 9-signal scoring |
