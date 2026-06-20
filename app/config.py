import os


class Settings:
    app_name: str = os.getenv("APP_NAME", "inchand-ai-v2")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    intent_classifier_provider: str = os.getenv("INTENT_CLASSIFIER_PROVIDER", "rule")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    intent_classifier_model: str = os.getenv("INTENT_CLASSIFIER_MODEL", "gpt-4.1-mini")
    intent_classifier_temperature: float = float(
        os.getenv("INTENT_CLASSIFIER_TEMPERATURE", "0")
    )


settings = Settings()
