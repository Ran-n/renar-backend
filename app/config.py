from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    secret_key: str = "dev-only-secret-change-me-in-production-0000"
    database_url: str = "sqlite:///./xoutaim.db"
    access_token_expire_minutes: int = 60 * 24 * 7  # one week
    cors_origins: list[str] = ["http://localhost:8550", "http://127.0.0.1:8550"]
    tmdb_api_key: str = ""
    episode_check_minutes: int = 360  # how often to look for new episodes


settings = Settings()
