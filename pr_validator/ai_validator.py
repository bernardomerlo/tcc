"""Chamada ao Ollama (/api/generate) com JSON estrito e num_ctx explícito, e normalização do veredito."""
import json
from dataclasses import dataclass
from typing import Any, Dict, List

import requests

from .config import Settings
from .prompt_builder import PromptBundle

LIST_FIELDS = ("missingDocUpdates", "missingCodeUpdates", "inconsistencies")


class AiValidationError(RuntimeError):
    """Falha ao obter um veredito utilizável da IA."""


@dataclass
class AiResult:
    verdict: Dict[str, Any]
    prompt_tokens: int


def _as_string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def parse_verdict(raw_text: str) -> Dict[str, Any]:
    """Valida/normaliza o JSON da IA. isValid só é true se nenhuma lista de problemas tiver itens."""
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise AiValidationError(f"A IA não retornou JSON válido: {exc}") from exc
    if not isinstance(data, dict):
        raise AiValidationError("O JSON da IA não é um objeto.")

    verdict: Dict[str, Any] = {name: _as_string_list(data.get(name)) for name in LIST_FIELDS}
    verdict["summary"] = str(data.get("summary", "")).strip()
    has_issues = any(verdict[name] for name in LIST_FIELDS)
    verdict["isValid"] = bool(data.get("isValid")) and not has_issues
    return verdict


def _call_ollama(settings: Settings, bundle: PromptBundle) -> Dict[str, Any]:
    payload = {
        "model": settings.model_name,
        "system": bundle.system,
        "prompt": bundle.prompt,
        "stream": False,
        "format": "json",
        "options": {"num_ctx": settings.num_ctx, "temperature": 0},
    }
    try:
        response = requests.post(
            f"{settings.ollama_base_url}/api/generate", json=payload, timeout=settings.ollama_timeout
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise AiValidationError(f"Falha ao chamar o Ollama em {settings.ollama_base_url}: {exc}") from exc
    return response.json()


def validate_with_ai(settings: Settings, bundle: PromptBundle, attempts: int = 2) -> AiResult:
    last_error: Exception = AiValidationError("sem tentativas")
    for _ in range(attempts):
        body = _call_ollama(settings, bundle)
        prompt_tokens = int(body.get("prompt_eval_count") or 0)
        # Se o prompt avaliado encostou em num_ctx, o Ollama pode ter cortado o início (a documentação).
        if prompt_tokens >= int(settings.num_ctx * 0.98):
            raise AiValidationError(
                f"Prompt de {prompt_tokens} tokens atingiu num_ctx={settings.num_ctx}; o Ollama pode ter "
                "truncado a documentação. Aumente PR_NUM_CTX (e a janela do modelo) ou reduza a documentação."
            )
        try:
            return AiResult(parse_verdict(body.get("response", "")), prompt_tokens)
        except AiValidationError as exc:
            last_error = exc
    raise last_error

