"""
Database initialisation script.
Creates inventory.db with:
  - inventory table (seed data from case study + extensions)
  - vendors table (approved vendor list)
  - prices table (expected unit prices for fraud detection)
Run: python setup_db.py
"""
import sqlite3
from pathlib import Path

from config import Config


def setup_database(db_path: str = Config.DB_PATH):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # ── Inventory ─────────────────────────────────────────────────────────────
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS inventory "
        "(item TEXT PRIMARY KEY, stock INTEGER, category TEXT, unit_price REAL)"
    )
    cursor.executemany(
        "INSERT OR REPLACE INTO inventory VALUES (?, ?, ?, ?)",
        [
            # Required seed items from case study
            ("WidgetA",    15,  "components", 150.00),
            ("WidgetB",    10,  "components", 200.00),
            ("GadgetX",     5,  "electronics", 240.00),
            ("FakeItem",    0,  "unknown",     None),
            # Extended catalog
            ("WidgetC",    20,  "components", 175.00),
            ("GadgetY",     8,  "electronics", 320.00),
            ("SprocketA",  30,  "mechanical",   45.00),
            ("SprocketB",  25,  "mechanical",   60.00),
            ("MotorUnit",   3,  "heavy",      1800.00),
            ("ControlPCB", 12,  "electronics",  95.00),
        ],
    )

    # ── Approved vendors ──────────────────────────────────────────────────────
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS vendors "
        "(vendor_name TEXT PRIMARY KEY, approved INTEGER, tier TEXT, since TEXT)"
    )
    cursor.executemany(
        "INSERT OR REPLACE INTO vendors VALUES (?, ?, ?, ?)",
        [
            ("Acme Supplies Co.",    1, "preferred", "2020-01-01"),
            ("Acme Supplies",        1, "preferred", "2020-01-01"),
            ("TechGlobal Solutions", 1, "standard",  "2021-06-15"),
            ("TechGlobal",           1, "standard",  "2021-06-15"),
            ("MegaSupply Corp",      1, "standard",  "2022-03-01"),
            ("Reliable Parts Inc",   1, "preferred", "2019-11-01"),
            ("Northern Supplies Ltd",1, "standard",  "2023-02-14"),
            ("FutureTech Industries",0, "pending",   "2026-07-01"),
            ("Industrial Direct",    1, "standard",  "2021-09-10"),
            ("Global Components",    1, "standard",  "2020-07-20"),
        ],
    )

    conn.commit()
    conn.close()
    print(f"[setup_db] Database initialised at {db_path}")


if __name__ == "__main__":
    setup_database()
    print("[setup_db] Done.")
