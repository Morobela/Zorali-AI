from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Zorali AI"
    app_env: str = "local"
    secret_key: str = "change-me-in-production"
    redis_url: str = "redis://redis:6379/0"
    ollama_host: str = "http://ollama:11434"
    ollama_model: str = "llama3.1"
    frontend_url: str = "http://localhost:5173"
    project_root: str = "/app"

    postgres_user: str = "zorali"
    postgres_password: str = "zorali"
    postgres_db: str = "zorali_ai"
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    @property
    def postgres_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
