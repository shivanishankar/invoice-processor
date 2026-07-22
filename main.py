#!/usr/bin/env python3
"""
Acme Corp Invoice Processing Automation
Multi-agent pipeline: Ingest → Validate → Approve → Pay

Usage:
  python main.py --invoice_path=data/invoices/INV-1001.txt
  python main.py --batch
  python main.py --setup
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from config import Config
from orchestrator.workflow import create_workflow, build_initial_state
from setup_db import setup_database
from utils.metrics import ProcessingMetrics

console = Console()


# ── CLI ────────────────────────────────────────────────────────────────────────

@click.command()
@click.option("--invoice_path", "-i", default=None, help="Path to invoice file to process")
@click.option("--batch", "-b", is_flag=True, default=False, help="Process all invoices in data/invoices/")
@click.option("--setup", is_flag=True, default=False, help="Initialise the inventory database and exit")
@click.option("--audit", "-a", is_flag=True, default=False, help="Print full audit trail after processing")
@click.option("--save_audit", is_flag=True, default=False, help="Save audit trail JSON to data/processed/")
def main(invoice_path, batch, setup, audit, save_audit):
    """Acme Corp — Automated Invoice Processing System"""
    _print_banner()

    if setup:
        console.print("[cyan]Setting up database...[/cyan]")
        setup_database()
        console.print("[green]✓ Database ready.[/green]")
        return

    if not Path(Config.DB_PATH).exists():
        console.print("[yellow]Database not found — running setup first...[/yellow]")
        setup_database()

    if batch:
        _run_batch(show_audit=audit, save_audit=save_audit)
    elif invoice_path:
        result = _run_single(invoice_path)
        if audit:
            _print_audit(result.get("audit_log", []))
        if save_audit:
            _save_audit(result)
    else:
        console.print("[red]Provide --invoice_path or use --batch[/red]")
        console.print("  python main.py --invoice_path=data/invoices/INV-1001.txt")
        console.print("  python main.py --batch")
        sys.exit(1)


# ── Processing ─────────────────────────────────────────────────────────────────

def _run_single(invoice_path: str, quiet: bool = False) -> dict:
    if not quiet:
        console.print(Panel(
            f"[bold white]Invoice:[/bold white] {Path(invoice_path).name}",
            title="[bold cyan]Processing[/bold cyan]",
            expand=False,
        ))

    workflow = create_workflow()
    initial_state = build_initial_state(invoice_path)

    t0 = time.time()
    result = workflow.invoke(initial_state)
    elapsed_ms = int((time.time() - t0) * 1000)

    if not quiet:
        _print_result(result, elapsed_ms)

    return result


def _run_batch(show_audit: bool = False, save_audit: bool = False):
    invoices_dir = Path(Config.INVOICES_DIR)
    files = sorted(invoices_dir.glob("INV-*"))

    if not files:
        console.print(f"[red]No invoice files found in {invoices_dir}[/red]")
        return

    console.print(Panel(
        f"[bold white]Found {len(files)} invoice(s) to process[/bold white]",
        title="[bold cyan]Batch Mode[/bold cyan]",
        expand=False,
    ))

    metrics = ProcessingMetrics()
    results = []

    for i, fpath in enumerate(files, 1):
        console.print(f"\n[dim]── Invoice {i}/{len(files)} ──────────────────────────────────[/dim]")
        metrics.start_timer()
        result = _run_single(str(fpath), quiet=False)
        metrics.record(result)
        results.append(result)
        if show_audit:
            _print_audit(result.get("audit_log", []))

    _print_batch_summary(metrics)

    if save_audit:
        out = metrics.save_json(Config.PROCESSED_DIR)
        console.print(f"\n[green]Metrics saved to {out}[/green]")


# ── Display helpers ────────────────────────────────────────────────────────────

def _print_banner():
    console.print(Panel(
        "[bold cyan]Acme Corp[/bold cyan] — Invoice Processing Automation\n"
        "[dim]Multi-agent pipeline: Ingest → Validate → Approve → Pay[/dim]",
        expand=False,
    ))


def _print_result(state: dict, elapsed_ms: int):
    decision = state.get("approval_decision") or "N/A"
    payment = state.get("payment_status") or "N/A"
    errors = state.get("errors") or []

    color = "green" if decision == "APPROVED" else "red"
    icon = "✓" if decision == "APPROVED" else "✗"

    table = Table(box=box.ROUNDED, show_header=False, padding=(0, 1))
    table.add_column("Field", style="dim", width=22)
    table.add_column("Value")

    table.add_row("Invoice ID", state.get("invoice_id") or "—")
    table.add_row("Vendor", state.get("vendor") or "—")
    table.add_row("Amount", f"${state.get('amount', 0):,.2f}" if state.get("amount") else "—")
    table.add_row("Due Date", state.get("due_date") or "—")
    table.add_row("Extraction Confidence", f"{state.get('extraction_confidence', 0):.0%}")
    table.add_row("Validation", "[green]PASS[/green]" if state.get("validation_passed") else "[red]FAIL[/red]")
    table.add_row("Fraud Score", f"{state.get('fraud_score', 0.0):.2f}")
    table.add_row("Risk Score", f"{state.get('risk_score', 0.0):.2f}")
    table.add_row("Decision", f"[{color}]{icon} {decision}[/{color}]")
    table.add_row("Payment", payment.upper())
    if state.get("payment_transaction_id"):
        table.add_row("Transaction ID", state["payment_transaction_id"])
    table.add_row("Processing Time", f"{elapsed_ms} ms")
    if errors:
        table.add_row("Errors", f"[red]{len(errors)}[/red]")

    console.print(table)

    reasoning = state.get("approval_reasoning", "")
    if reasoning:
        console.print(f"[dim]Reasoning:[/dim] {reasoning[:200]}")


def _print_batch_summary(metrics: ProcessingMetrics):
    s = metrics.summary()
    if not s:
        return

    console.print("\n")
    console.print(Panel("[bold]Batch Processing Summary[/bold]", expand=False))

    table = Table(box=box.SIMPLE_HEAVY)
    table.add_column("Invoice", style="cyan")
    table.add_column("Vendor")
    table.add_column("Amount", justify="right")
    table.add_column("Decision", justify="center")
    table.add_column("Risk", justify="right")
    table.add_column("ms", justify="right")

    for r in metrics.records:
        color = "green" if r.decision == "APPROVED" else "red"
        table.add_row(
            r.invoice_id,
            (r.vendor or "—")[:25],
            f"${r.amount:,.0f}" if r.amount else "—",
            f"[{color}]{r.decision}[/{color}]",
            f"{r.risk_score:.2f}",
            str(r.processing_time_ms),
        )

    console.print(table)
    console.print(
        f"[bold]Total:[/bold] {s['total']} invoices | "
        f"[green]{s['approved']} approved[/green] | "
        f"[red]{s['rejected']} rejected[/red] | "
        f"${s['total_value_approved']:,.2f} approved value | "
        f"avg {s['avg_processing_ms']} ms/invoice"
    )


def _print_audit(audit_log: list):
    console.print("\n[bold dim]── Audit Trail ─────────────────────────────────────────────[/bold dim]")
    console.print(json.dumps(audit_log, indent=2, default=str))


def _save_audit(state: dict):
    Config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    invoice_id = state.get("invoice_id") or "unknown"
    out = Config.PROCESSED_DIR / f"{invoice_id}_audit.json"
    out.write_text(json.dumps(state, indent=2, default=str))
    console.print(f"[green]Audit saved to {out}[/green]")


if __name__ == "__main__":
    main()
