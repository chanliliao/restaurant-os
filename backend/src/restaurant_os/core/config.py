"""
Application configuration via Pydantic BaseSettings.

"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central configuration object loaded from environment variables / .env file.

    All secrets (API keys, DB passwords) live here — never hardcoded elsewhere.
    Fields without defaults are required; startup fails immediately if they are absent.

    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- GLM / ZhipuAI ---
    glm_ocr_api_key: str
    """ZhipuAI API key used for both GLM-OCR and GLM-4-Flash calls."""

    glm_model: str = "glm-4-flash"
    """Chat/reasoning model name. Override in .env to pin a specific version."""

    glm_ocr_model: str = "glm-ocr"
    """OCR model name passed to the ZhipuAI vision endpoint."""

    # --- Database ---
    database_url: str
    """
    Async-compatible PostgreSQL DSN.
    Example: postgresql+asyncpg://user:pass@localhost:5432/restaurant_os
    """

    # --- Redis ---
    redis_url: str = "redis://localhost:6379"
    """Redis DSN for short-term agent session state and Celery broker."""

    # --- Auth ---
    clerk_secret_key: str
    """Clerk backend API secret key for JWT verification (Section 10)."""

    # --- API gateway ---
    cors_allowed_origins: str = "http://localhost:3000"
    """
    Comma-separated list of allowed CORS origins.
    Consumed by CORSMiddleware in api/app.py.
    """

    # --- App behaviour ---
    debug: bool = False
    """When True, FastAPI shows full tracebacks in error responses."""


# Module-level singleton — import this wherever settings are needed:
#   from restaurant_os.core.config import settings
settings = Settings()
