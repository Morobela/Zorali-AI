from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Zorali"
    app_env: str = "local"
    secret_key: str = "change-me-in-production"

    # JWT lifetimes (read from JWT_ACCESS_MINUTES / JWT_REFRESH_DAYS)
    jwt_access_minutes: int = 30
    jwt_refresh_days: int = 30
    redis_url: str = "redis://redis:6379/0"
    ollama_host: str = "http://ollama:11434"
    ollama_model: str = "llama3.2:1b"
    cloud_api_base: str = "https://api.openai.com/v1"
    cloud_api_key: str = ""
    cloud_model: str = "gpt-4o-mini"
    provider_timeout_seconds: float = 60.0
    web_search_enabled: bool = False
    # Optional Tavily search API key — when set, deep research uses Tavily
    # instead of the DuckDuckGo instant-answer API (much richer results).
    tavily_api_key: str = ""
    # Deep research: how many of the top search hits get fetched and read.
    deep_research_max_pages: int = Field(default=3, ge=1, le=10)
    # Max characters of extracted text kept per fetched page.
    deep_research_page_chars: int = Field(default=2400, ge=200, le=20000)
    # Sandboxed code execution (artifact "Run", /run task command, code_execution
    # tool). Off by default: the sandbox is `python -I` in a subprocess with a
    # timeout — it is NOT a container and does not block network or filesystem
    # access, so only enable it on trusted single-admin deployments.
    code_execution_enabled: bool = False
    code_execution_timeout_seconds: int = Field(default=10, ge=1, le=120)
    frontend_url: str = "http://localhost:5173"
    project_root: str = "/app"

    postgres_user: str = "zorali"
    postgres_password: str = "zorali"
    postgres_db: str = "zorali_ai"
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    # Rate limiting (OpenJarvis energy/cost + vLLM multi-user)
    rate_limit_capacity: float = 60.0    # max burst tokens per client
    rate_limit_refill: float = 1.0       # tokens refilled per second

    # Inference memory pool (vLLM PagedAttention-inspired)
    memory_pool_blocks: int = 256
    memory_pool_block_size: int = 512

    # Batch processor concurrency (vLLM continuous batching)
    batch_max_concurrent: int = 8

    # Energy scoring budget (OpenJarvis cost-aware routing)
    inference_cost_budget_usd: float = 10.0

    # Local learning loop (OpenJarvis)
    learning_loop_enabled: bool = True
    learning_min_improvement_pct: float = 2.0

    # Task queue (Higgsfield experiment queue)
    task_queue_max_concurrent: int = 4
    task_queue_cost_budget_usd: float = 50.0

    # Skills system (OpenJarvis)
    skills_autoload: bool = True

    # Checkpoint persistence (TensorFlow SavedModel-inspired)
    checkpoint_enabled: bool = True

    # Hybrid retrieval (2026 production-RAG: hybrid fusion + reranking + contextual)
    rag_rerank_enabled: bool = True
    rag_candidate_pool: int = Field(default=20, ge=1, le=1000)
    rag_rrf_k: int = Field(default=60, ge=1)
    rag_rerank_weight: float = Field(default=0.5, ge=0.0, le=2.0)
    rag_ranker_guarantee: int = Field(default=5, ge=1, le=50)  # top-N per ranker always reach reranking
    rag_dense_rrf_weight: float = Field(default=3.0, ge=0.1, le=10.0)  # dense ranker weight vs 1.0 per lexical
    rag_contextual_enabled: bool = True
    rag_embeddings_enabled: bool = False
    rag_embedding_model: str = "nomic-embed-text"  # must support search_document/query prefixes

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
