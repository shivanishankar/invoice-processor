"""Central configuration — reads from .env or environment variables."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent


class Config:
    # ── LLM ──────────────────────────────────────────────────────────────────
    LLM_PROVIDER: str = os.environ.get("LLM_PROVIDER", "mock")

    XAI_API_KEY: str = os.environ.get("XAI_API_KEY", "")
    XAI_BASE_URL: str = "https://api.x.ai/v1"
    XAI_MODEL: str = os.environ.get("XAI_MODEL", "grok-3")

    OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.environ.get("OPENAI_MODEL", "gpt-4o")

    ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")

    # Auto-detect provider from available keys
    @classmethod
    def resolved_provider(cls) -> str:
        if cls.LLM_PROVIDER != "mock":
            return cls.LLM_PROVIDER
        if cls.XAI_API_KEY:
            return "xai"
        if cls.OPENAI_API_KEY:
            return "openai"
        return "mock"

    # ── Database ──────────────────────────────────────────────────────────────
    DB_PATH: str = str(BASE_DIR / "inventory.db")

    # ── Business rules ────────────────────────────────────────────────────────
    HIGH_VALUE_THRESHOLD: float = 10_000.0   # Invoices above this need extra scrutiny
    MAX_RETRIES: int = 3                      # Max LLM extraction attempts
    LOW_CONFIDENCE_THRESHOLD: float = 0.65   # Below this → trigger re-extraction

    # ── Paths ─────────────────────────────────────────────────────────────────
    DATA_DIR: Path = BASE_DIR / "data"
    INVOICES_DIR: Path = DATA_DIR / "invoices"
    PROCESSED_DIR: Path = DATA_DIR / "processed"
    LOGS_DIR: Path = BASE_DIR / "logs"
