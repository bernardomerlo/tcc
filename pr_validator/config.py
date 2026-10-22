"""Configuração do validador de PRs, lida de variáveis de ambiente (.env)."""
import os
from dataclasses import dataclass
from typing import Tuple

from dotenv import load_dotenv

load_dotenv()

# Arquivos que estouram tokens sem agregar valor semântico à validação.
# Os padrões são comparados (case-insensitive) contra o caminho completo e o nome do arquivo.
DEFAULT_DIFF_IGNORE_PATTERNS: Tuple[str, ...] = (
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "pipfile.lock",
    "composer.lock", "cargo.lock", "go.sum", "gemfile.lock", "packages.lock.json",
    "*.designer.cs", "*modelsnapshot.cs", "*/migrations/*.cs",
    "*.min.js", "*.min.css", "*.map",
    "*.svg", "*.png", "*.jpg", "*.jpeg", "*.gif", "*.ico", "*.webp", "*.bmp",
    "*.pdf", "*.zip", "*.gz", "*.tar", "*.7z", "*.jar", "*.dll", "*.exe", "*.pyc",
    "*.woff", "*.woff2", "*.ttf", "*.eot", "*.mp3", "*.mp4", "*.sqlite3", "*.db",
)


def _csv(name: str, default: Tuple[str, ...]) -> Tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return default
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    db_path: str
    webhook_secret: str
    ollama_base_url: str
    model_name: str
    num_ctx: int
    output_reserve_tokens: int
    ollama_timeout: int
    gh_timeout: int
    docs_paths: Tuple[str, ...]
    doc_extensions: Tuple[str, ...]
    max_doc_file_bytes: int
    diff_ignore_patterns: Tuple[str, ...]

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            host=os.getenv("PR_VALIDATOR_HOST", "127.0.0.1"),
            port=int(os.getenv("PR_VALIDATOR_PORT", "5000")),
            db_path=os.getenv("PR_VALIDATOR_DB", os.path.join("data", "pr_validator.sqlite3")),
            webhook_secret=os.getenv("PR_VALIDATOR_WEBHOOK_SECRET", ""),
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
            model_name=os.getenv("PR_MODEL_NAME") or os.getenv("MODEL_NAME") or "llama3.1:8b",
            num_ctx=int(os.getenv("PR_NUM_CTX", "32768")),
            output_reserve_tokens=int(os.getenv("PR_OUTPUT_RESERVE_TOKENS", "2048")),
            ollama_timeout=int(os.getenv("PR_OLLAMA_TIMEOUT", "900")),
            gh_timeout=int(os.getenv("PR_GH_TIMEOUT", "120")),
            docs_paths=_csv("PR_DOCS_PATHS", ("docs/", "README.md")),
            doc_extensions=_csv("PR_DOC_EXTENSIONS", (".md", ".mdx", ".rst", ".txt")),
            max_doc_file_bytes=int(os.getenv("PR_MAX_DOC_FILE_BYTES", str(200_000))),
            diff_ignore_patterns=DEFAULT_DIFF_IGNORE_PATTERNS + _csv("PR_DIFF_IGNORE_EXTRA", ()),
        )

