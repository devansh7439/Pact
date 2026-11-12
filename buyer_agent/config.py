"""Buyer-agent configuration. Every external dependency is optional.

No LLM credentials -> template replies. No signing key -> an ephemeral key is
generated at boot (fine for local runs and tests; set BUYER_SIGNING_KEY to keep
registrations across restarts).
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    buyer_public_url: str = "http://localhost:8200"
    buyer_db_path: Path = DATA_DIR / "buyer.db"
    buyer_signing_key: str = ""  # base64url Ed25519 private key; never commit
    buyer_key_id: str = ""  # assigned at registration, e.g. agt_7f3c#k1
    judge_mode: bool = False

    # Browser origins allowed to call this API (the Next.js web app).
    web_origins: str = "http://localhost:3000"

    # Default merchant link for the demo (the merchant-api URL).
    merchant_base_url: str = "http://localhost:8100"

    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_reasoning_effort: str = ""

    @property
    def llm_live(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)


settings = Settings()
