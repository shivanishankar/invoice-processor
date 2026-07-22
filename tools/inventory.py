"""SQLite inventory database tools exposed as callable functions."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional


def _conn(db_path: str) -> sqlite3.Connection:
    return sqlite3.connect(db_path)


def check_item_stock(item_name: str, db_path: str) -> dict:
    """
    Returns {"item": str, "stock": int|None, "found": bool}.
    stock=None when item doesn't exist.
    """
    try:
        conn = _conn(db_path)
        row = conn.execute(
            "SELECT item, stock FROM inventory WHERE item = ?", (item_name,)
        ).fetchone()
        conn.close()
        if row:
            return {"item": row[0], "stock": row[1], "found": True}
        return {"item": item_name, "stock": None, "found": False}
    except sqlite3.Error as e:
        return {"item": item_name, "stock": None, "found": False, "error": str(e)}


def get_all_items(db_path: str) -> list[dict]:
    """Return all inventory records."""
    try:
        conn = _conn(db_path)
        rows = conn.execute("SELECT item, stock FROM inventory").fetchall()
        conn.close()
        return [{"item": r[0], "stock": r[1]} for r in rows]
    except sqlite3.Error:
        return []


def get_vendor_info(vendor_name: str, db_path: str) -> dict:
    """Look up vendor in approved vendor list (if table exists)."""
    try:
        conn = _conn(db_path)
        row = conn.execute(
            "SELECT vendor_name, approved, tier FROM vendors WHERE vendor_name LIKE ?",
            (f"%{vendor_name}%",),
        ).fetchone()
        conn.close()
        if row:
            return {"vendor": row[0], "approved": bool(row[1]), "tier": row[2], "found": True}
        return {"vendor": vendor_name, "approved": False, "tier": None, "found": False}
    except sqlite3.Error:
        return {"vendor": vendor_name, "approved": False, "tier": None, "found": False}
