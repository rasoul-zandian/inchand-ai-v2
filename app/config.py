import os
from pathlib import Path


def _load_dotenv_if_present() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv_if_present()


class Settings:
    app_name: str = os.getenv("APP_NAME", "inchand-ai-v2")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    intent_classifier_provider: str = os.getenv("INTENT_CLASSIFIER_PROVIDER", "rule")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    intent_classifier_model: str = os.getenv("INTENT_CLASSIFIER_MODEL", "gpt-4.1-mini")
    intent_classifier_temperature: float = float(
        os.getenv("INTENT_CLASSIFIER_TEMPERATURE", "0")
    )
    inchand_api_base_url: str = os.getenv("INCHAND_API_BASE_URL", "")
    inchand_api_key_name: str = os.getenv("INCHAND_API_KEY_NAME", "Authorization")
    inchand_api_key_value: str = os.getenv("INCHAND_API_KEY_VALUE") or os.getenv(
        "INCHAND_INTERNAL_TOKEN", ""
    )
    inchand_order_lookup_timeout_seconds: float = float(
        os.getenv("INCHAND_ORDER_LOOKUP_TIMEOUT_SECONDS", "10")
    )


settings = Settings()
