"""Chamada ao Ollama (/api/generate) com JSON estrito e num_ctx explícito, e normalização do veredito."""
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

from .config import Settings
from .prompt_builder import PromptBundle

LIST_FIELDS = ("missingDocUpdates", "missingCodeUpdates", "inconsistencies")

# Schema enviado em `format`: o Ollama restringe a geração a esta estrutura (versões antigas só aceitam "json").
_LIST_SCHEMA = {"type": "array", "items": {"type": "string"}}
VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "isValid": {"type": "boolean"},
        "summary": {"type": "string"},
        **{name: _LIST_SCHEMA for name in LIST_FIELDS},
    },
    "required": ["isValid", "summary", *LIST_FIELDS],
}

# Lookahead: considera todas as aspas de abertura possíveis (candidatos sobrepostos),
# p.ex. quando o modelo envolve o item inteiro em aspas.
_QUOTE = re.compile(r'(?=["“«]([^"”»]{8,})["”»])')


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _has_evidence(item: str, evidence: str) -> bool:
    """O item só vale se citar entre aspas um trecho que realmente existe na documentação/diff enviados."""
    return any(_normalize(quote) in evidence for quote in _QUOTE.findall(item))


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


def parse_verdict(raw_text: str, evidence_text: Optional[str] = None) -> Dict[str, Any]:
    """Valida/normaliza o JSON da IA. isValid só é true se nenhuma lista de problemas tiver itens.

    Com `evidence_text`, descarta apontamentos que não citam um trecho literal existente nesse texto
    (anti-alucinação); a quantidade descartada fica em `discardedClaims`.
    """
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise AiValidationError(f"A IA não retornou JSON válido: {exc}") from exc
    if not isinstance(data, dict):
        raise AiValidationError("O JSON da IA não é um objeto.")

    verdict: Dict[str, Any] = {name: _as_string_list(data.get(name)) for name in LIST_FIELDS}
    verdict["summary"] = str(data.get("summary", "")).strip()
    verdict["discardedClaims"] = 0
    claimed_invalid = not data.get("isValid") or any(verdict[name] for name in LIST_FIELDS)
    if evidence_text is not None:
        evidence = _normalize(evidence_text)
        for name in LIST_FIELDS:
            kept = [item for item in verdict[name] if _has_evidence(item, evidence)]
            verdict["discardedClaims"] += len(verdict[name]) - len(kept)
            verdict[name] = kept
        if claimed_invalid and verdict["discardedClaims"] and not any(verdict[name] for name in LIST_FIELDS):
            verdict["summary"] = "Nenhuma inconsistência comprovada por trecho literal da documentação."
            claimed_invalid = False
    verdict["isValid"] = not claimed_invalid and not any(verdict[name] for name in LIST_FIELDS)
    return verdict


def _call_ollama(settings: Settings, bundle: PromptBundle, output_format: Any) -> requests.Response:
    payload = {
        "model": settings.model_name,
        "system": bundle.system,
        "prompt": bundle.prompt,
        "stream": False,
        "format": output_format,
        "options": {"num_ctx": settings.num_ctx, "temperature": 0},
    }
    try:
        return requests.post(
            f"{settings.ollama_base_url}/api/generate", json=payload, timeout=settings.ollama_timeout
        )
    except requests.RequestException as exc:
        raise AiValidationError(f"Falha ao chamar o Ollama em {settings.ollama_base_url}: {exc}") from exc


def _generate(settings: Settings, bundle: PromptBundle) -> Dict[str, Any]:
    response = _call_ollama(settings, bundle, VERDICT_SCHEMA)
    if response.status_code == 400:  # Ollama antigo sem suporte a schema em `format`
        response = _call_ollama(settings, bundle, "json")
    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        raise AiValidationError(f"Falha ao chamar o Ollama em {settings.ollama_base_url}: {exc}") from exc
    return response.json()


def validate_with_ai(settings: Settings, bundle: PromptBundle, attempts: int = 2) -> AiResult:
    last_error: Exception = AiValidationError("sem tentativas")
    for _ in range(attempts):
        body = _generate(settings, bundle)
        prompt_tokens = int(body.get("prompt_eval_count") or 0)
        # Se o prompt avaliado encostou em num_ctx, o Ollama pode ter cortado o início (a documentação).
        if prompt_tokens >= int(settings.num_ctx * 0.98):
            raise AiValidationError(
                f"Prompt de {prompt_tokens} tokens atingiu num_ctx={settings.num_ctx}; o Ollama pode ter "
                "truncado a documentação. Aumente PR_NUM_CTX (e a janela do modelo) ou reduza a documentação."
            )
        try:
            return AiResult(parse_verdict(body.get("response", ""), evidence_text=bundle.prompt), prompt_tokens)
        except AiValidationError as exc:
            last_error = exc
    raise last_error

