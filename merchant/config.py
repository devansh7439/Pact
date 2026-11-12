"""Merchant-service configuration.

Every external dependency is optional. With no PayPal credentials the service
runs in fixture mode; with no LLM credentials it uses templates. A clean clone
therefore runs, and its tests pass, offline — and adding credentials upgrades
those paths to live calls without a code change.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"


class Settings(BaseSettings):
    """Read from the environment or a local `.env` (see `.env.example`)."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # PayPal sandbox
    paypal_env: str = "sandbox"
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_webhook_id: str = ""
    merchant_public_url: str = "http://localhost:8100"

    # Engine controls (defaults match doc 05 §7)
    pact_mode: str = "review_first"
    ev_floor_minor: int = 50
    autonomy_ceiling_minor: int = 25_000
    max_recovery_attempts: int = 2
    offer_ttl_seconds: int = 900
    holdout_rate: float = 0.10
    holdout_salt: str = "change-me"
    contribution_margin: float = 1.0

    # Merchant identity (PRP). No signing key → an ephemeral one per process (fixture/dev).
    merchant_id: str = "mer_kettle_crumb"
    merchant_name: str = "Kettle & Crumb"
    merchant_signing_key: str = ""
    merchant_key_id: str = "mer_kettle_crumb#k1"
    web_public_url: str = "http://localhost:3000"
    buyer_public_url: str = "http://localhost:8200"
    judge_mode: bool = False

    merchant_db_path: Path = DATA_DIR / "merchant.db"
    model_path: Path = DATA_DIR / "recovery_model.joblib"

    # LLM — any OpenAI-compatible chat-completions endpoint
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_reasoning_effort: str = ""

    @property
    def paypal_live(self) -> bool:
        return bool(self.paypal_client_id and self.paypal_client_secret)

    @property
    def llm_live(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)


settings = Settings()
