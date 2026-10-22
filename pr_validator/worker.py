"""Worker em background: coleta via gh, valida com a IA e grava o veredito."""
import json
import logging
import queue
import threading
from typing import Callable, Optional

from .ai_validator import AiResult, AiValidationError, validate_with_ai
from .config import Settings
from .database import ReviewRepository
from .diff_filter import filter_diff
from .docs_collector import collect_documentation
from .github_cli import GitHubCli, GitHubCliError
from .prompt_builder import PromptBundle, PromptTooLargeError, build_prompt

log = logging.getLogger("pr_validator.worker")


class ReviewWorker:
    def __init__(
        self,
        settings: Settings,
        repository: ReviewRepository,
        github: GitHubCli,
        ai: Callable[[Settings, PromptBundle], AiResult] = validate_with_ai,
    ):
        self.settings = settings
        self.repository = repository
        self.github = github
        self._ai = ai
        self._queue: "queue.Queue[Optional[int]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        for review_id in self.repository.unfinished_ids():
            self._queue.put(review_id)
        self._thread = threading.Thread(target=self._loop, name="pr-review-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._queue.put(None)

    def enqueue(self, review_id: int) -> None:
        self._queue.put(review_id)

    def _loop(self) -> None:
        while True:
            review_id = self._queue.get()
            if review_id is None:
                return
            try:
                self.process(review_id)
            except Exception:  # o worker nunca pode morrer por causa de um PR
                log.exception("Falha inesperada ao processar a revisão %s", review_id)

    def process(self, review_id: int) -> None:
        if not self.repository.claim_for_processing(review_id):
            return  # já processado por uma execução anterior ou substituído por um novo push
        review = self.repository.get(review_id)
        commit_sha = review["CommitSha"]
        try:
            diff_content, verdict_json = self._validate(review)
        except (GitHubCliError, AiValidationError, PromptTooLargeError) as exc:
            log.warning("Revisão %s falhou: %s", review_id, exc)
            self.repository.save_error(review_id, commit_sha, str(exc))
            return
        except Exception as exc:
            log.exception("Erro inesperado na revisão %s", review_id)
            self.repository.save_error(review_id, commit_sha, f"Erro inesperado: {exc}")
            return
        if not self.repository.save_result(review_id, commit_sha, diff_content, verdict_json):
            log.info("Resultado da revisão %s descartado: PR mudou durante a validação", review_id)

    def _validate(self, review: dict):
        repo, pr_number = review["Repo"], review["PrNumber"]
        info = self.github.pr_view(repo, pr_number)
        raw_diff = self.github.pr_diff(repo, pr_number)
        filtered = filter_diff(raw_diff, self.settings.diff_ignore_patterns)

        docs = collect_documentation(
            self.github,
            self.settings,
            repo,
            base_ref=info.get("baseRefName") or "main",
            head_sha=info.get("headRefOid") or review["CommitSha"],
            changed_paths=[item["path"] for item in info.get("files", [])],
        )
        bundle = build_prompt(
            title=info.get("title") or review["Title"],
            body=info.get("body") or "",
            docs=docs,
            diff_blocks=filtered.blocks,
            skipped=filtered.skipped,
            num_ctx=self.settings.num_ctx,
            output_reserve=self.settings.output_reserve_tokens,
        )
        result = self._ai(self.settings, bundle)

        warnings = []
        if bundle.omitted_diff_files:
            warnings.append(
                "Diff truncado por limite de contexto; não analisados: " + ", ".join(bundle.omitted_diff_files)
            )
        if not docs:
            warnings.append("Nenhum arquivo de documentação foi encontrado; o veredito é pouco confiável.")
        verdict = dict(result.verdict)
        discarded = verdict.pop("discardedClaims", 0)
        if discarded:
            warnings.append(
                f"{discarded} apontamento(s) da IA descartado(s) por não citarem trecho literal da documentação."
            )
        verdict["meta"] = {
            "model": self.settings.model_name,
            "numCtx": self.settings.num_ctx,
            "promptTokens": result.prompt_tokens or bundle.estimated_tokens,
            "docFiles": bundle.doc_paths,
            "skippedFiles": [{"path": s.path, "reason": s.reason} for s in filtered.skipped],
            "warnings": warnings,
        }
        return filtered.text, json.dumps(verdict, ensure_ascii=False)
