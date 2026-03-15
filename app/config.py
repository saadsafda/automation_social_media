"""Configuration module — loads settings from .env"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)


class Settings:
    # TikTok credentials
    TIKTOK_EMAIL: str = os.getenv("TIKTOK_EMAIL", "")
    TIKTOK_PASSWORD: str = os.getenv("TIKTOK_PASSWORD", "")

    # Chrome
    CHROME_PROFILE: str = os.getenv("CHROME_PROFILE", "openclaw")
    CHROME_USER_DATA_DIR: str = os.getenv("CHROME_USER_DATA_DIR", "")

    # API
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))
    API_SECRET_KEY: str = os.getenv("API_SECRET_KEY", "change-me")

    # OpenClaw agent configuration
    OPENCLAW_AGENT: str = os.getenv("OPENCLAW_AGENT", "main")
    OPENCLAW_TIMEOUT: int = int(os.getenv("OPENCLAW_TIMEOUT", "60"))

    # Browser mode
    HEADLESS: bool = os.getenv("HEADLESS", "false").lower() == "true"

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # TikTok URLs
    TIKTOK_COMMENT_URL: str = "https://www.tiktok.com/tiktokstudio/comment"
    TIKTOK_LOGIN_URL: str = "https://www.tiktok.com/login"

    # Branding
    BRAND_NAME: str = "CorpusIQ"
    CREATOR_HANDLE: str = "corpusiq"


settings = Settings()
