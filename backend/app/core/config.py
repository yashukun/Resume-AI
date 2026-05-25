from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Application
    app_name: str = "Resume AI"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"

    # Database
    database_url: str = "postgresql+asyncpg://resume_ai:resume_ai_secret@localhost:5432/resume_ai_db"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # MinIO/S3
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin123"
    minio_bucket: str = "resumes"
    minio_secure: bool = False

    # Ollama — defaults to the HOST machine running Ollama natively
    # (Metal GPU on Mac, much faster than CPU-only Docker inference).
    # Override via OLLAMA_BASE_URL env var. See docker-compose.yaml.
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model_coder: str = "qwen2.5-coder:7b"
    ollama_model_general: str = "qwen2.5:7b"
    # Fast model for structured extraction (JSON parsing) — smaller = faster
    ollama_model_fast: str = "llama3.2:3b"
    # Max concurrent LLM requests. Default 1 (safe) — increase to 2+
    # ONLY when Ollama itself is also started with the matching
    # `OLLAMA_NUM_PARALLEL=<n>` AND the host has enough VRAM to load
    # two model instances. Mismatched settings (semaphore high but
    # Ollama serial) cause client-side timeouts because the second
    # request's clock runs while it sits in Ollama's internal queue.
    ollama_parallel: int = 1

    # File Upload
    max_upload_size: int = 10 * 1024 * 1024  # 10MB
    allowed_extensions: list = [".pdf", ".docx", ".doc"]

    class Config:
        env_file = ".env"
        extra = "allow"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
