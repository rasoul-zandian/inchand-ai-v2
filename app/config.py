import os


class Settings:
    app_name: str = os.getenv("APP_NAME", "inchand-ai-v2")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()
